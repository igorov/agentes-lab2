import os
import time
import uuid
from pathlib import Path
from typing import List, Optional

from langchain.agents import create_agent
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_openai import ChatOpenAI
from sqlalchemy.orm import Session

from src.repositories.history_repository import HistoryRepository
from src.repositories.models.history import History
from src.utils.environment import (
    HISTORY_LIMIT,
    LANGCHAIN_TRACING_V2,
    LANGFUSE_HOST,
    LANGFUSE_PUBLIC_KEY,
    LANGFUSE_SECRET_KEY,
    LANGSMITH_API_KEY,
    LANGSMITH_PROJECT,
    LLM_PROVIDER,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    OPENAI_API_KEY,
    OPENAI_MODEL,
)
from src.services.tools import LOCAL_TOOLS, get_all_tools
from src.utils.logger import get_logger

logger = get_logger(__name__)

os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY
if LANGSMITH_API_KEY:
    os.environ["LANGCHAIN_API_KEY"] = LANGSMITH_API_KEY
if LANGCHAIN_TRACING_V2:
    os.environ["LANGCHAIN_TRACING_V2"] = LANGCHAIN_TRACING_V2
if LANGSMITH_PROJECT:
    os.environ["LANGCHAIN_PROJECT"] = LANGSMITH_PROJECT
if LANGFUSE_PUBLIC_KEY:
    os.environ["LANGFUSE_PUBLIC_KEY"] = LANGFUSE_PUBLIC_KEY
if LANGFUSE_SECRET_KEY:
    os.environ["LANGFUSE_SECRET_KEY"] = LANGFUSE_SECRET_KEY
if LANGFUSE_HOST:
    os.environ["LANGFUSE_HOST"] = LANGFUSE_HOST


SYSTEM_PROMPT = (Path(__file__).parent / "system_prompt.txt").read_text(encoding="utf-8")


def _build_model():
    if LLM_PROVIDER == "ollama":
        if not OLLAMA_BASE_URL or not OLLAMA_MODEL:
            raise ValueError("LLM_PROVIDER=ollama requiere OLLAMA_BASE_URL y OLLAMA_MODEL configurados")
        logger.info("Usando Ollama como LLM", extra={"base_url": OLLAMA_BASE_URL, "model": OLLAMA_MODEL})
        return ChatOpenAI(
            model=OLLAMA_MODEL,
            base_url=f"{OLLAMA_BASE_URL.rstrip('/')}/v1",
            api_key="ollama",
        )
    logger.info("Usando OpenAI como LLM", extra={"model": OPENAI_MODEL})
    return f"openai:{OPENAI_MODEL}"


_agent = create_agent(
    model=_build_model(),
    tools=LOCAL_TOOLS,
    system_prompt=SYSTEM_PROMPT,
)


def init_agent(tools: list) -> None:
    """Reinicializa el agente global con el conjunto de tools provisto."""
    global _agent
    _agent = create_agent(
        model=_build_model(),
        tools=tools,
        system_prompt=SYSTEM_PROMPT,
    )
    logger.info("Agente reinicializado con %d tool(s): %s", len(tools), [t.name for t in tools])


class AgentService:
    def __init__(self, db: Session) -> None:
        self._repo = HistoryRepository(db)

    def chat(self, question: str, user: str, session_id: Optional[str]) -> dict:
        is_new_session = not session_id
        if is_new_session:
            logger.info("Creando nueva sesión")
            session_id = str(uuid.uuid4())

        trace_id = str(uuid.uuid4())

        logger.info(
            "Iniciando chat",
            extra={"session_id": session_id, "trace_id": trace_id, "user": user},
        )

        t0 = time.perf_counter()
        history_records = [] if is_new_session else self._repo.get_by_session_id(session_id, limit=HISTORY_LIMIT)
        t_history = time.perf_counter() - t0

        history_messages: List[BaseMessage] = []
        for record in history_records:
            history_messages.append(HumanMessage(content=record.question))
            history_messages.append(AIMessage(content=record.answer))

        t0 = time.perf_counter()
        result = self._run_agent(
            question=question,
            session_id=session_id,
            trace_id=trace_id,
            user=user,
            history=history_messages,
        )
        t_agent = time.perf_counter() - t0

        t0 = time.perf_counter()
        self._repo.save(
            History(
                trace_id=trace_id,
                session_id=session_id,
                question=question,
                answer=result["answer"],
                input_tokens=result["input_tokens"],
                output_tokens=result["output_tokens"],
            )
        )
        t_save = time.perf_counter() - t0

        logger.info(
            "Chat finalizado",
            extra={
                "trace_id": trace_id,
                "session_id": session_id,
                "t_history_ms": round(t_history * 1000, 2),
                "t_agent_ms": round(t_agent * 1000, 2),
                "t_save_ms": round(t_save * 1000, 2),
            },
        )

        return {
            "user": user,
            "answer": result["answer"],
            "session_id": session_id,
            "trace_id": trace_id,
        }

    def _run_agent(
        self,
        question: str,
        session_id: str,
        trace_id: str,
        user: str,
        history: List[BaseMessage],
    ) -> dict:
        messages: List[BaseMessage] = history + [HumanMessage(content=question)]
        callbacks = self._build_callbacks()

        run_config = {
            "callbacks": callbacks,
            "run_id": uuid.UUID(trace_id),
            "metadata": {
                "session_id": session_id,
                "trace_id": trace_id,
                "user": user,
            },
            "tags": [user, session_id],
        }

        logger.info(
            "Invocando agente",
            extra={"session_id": session_id, "trace_id": trace_id, "user": user},
        )

        result = self._invoke_with_langfuse(
            messages=messages,
            run_config=run_config,
            question=question,
            session_id=session_id,
            trace_id=trace_id,
            user=user,
        )

        last_message: AIMessage = result["messages"][-1]
        answer: str = last_message.content

        usage = getattr(last_message, "usage_metadata", None) or {}
        input_tokens: int = usage.get("input_tokens", 0)
        output_tokens: int = usage.get("output_tokens", 0)

        logger.info(
            "Respuesta generada",
            extra={
                "trace_id": trace_id,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            },
        )

        return {
            "answer": answer,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        }

    def _invoke_with_langfuse(
        self,
        messages: List[BaseMessage],
        run_config: dict,
        question: str,
        session_id: str,
        trace_id: str,
        user: str,
    ) -> dict:
        if not (LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY):
            return _agent.invoke({"messages": messages}, config=run_config)

        try:
            from langfuse import Langfuse, get_client, propagate_attributes
            from langfuse.langchain import CallbackHandler as LangfuseHandler

            lf = get_client()
            lf_trace_id = Langfuse.create_trace_id(seed=trace_id)
            run_config = {**run_config, "callbacks": run_config["callbacks"] + [LangfuseHandler()]}

            logger.info("Langfuse activado", extra={"lf_trace_id": lf_trace_id, "trace_id": trace_id})

            with lf.start_as_current_observation(as_type="span", name="agent-run", input=question):
                with propagate_attributes(session_id=session_id, user_id=user, tags=[user, session_id]):
                    return _agent.invoke({"messages": messages}, config=run_config)

        except Exception as exc:
            logger.warning("Error inicializando Langfuse, continuando sin él", extra={"error": str(exc)})
            return _agent.invoke({"messages": messages}, config=run_config)

    def _build_callbacks(self) -> List[BaseCallbackHandler]:
        callbacks: List[BaseCallbackHandler] = []

        if LANGSMITH_API_KEY and LANGSMITH_PROJECT:
            try:
                from langchain_core.tracers.langchain import LangChainTracer

                tracer = LangChainTracer(project_name=LANGSMITH_PROJECT)
                callbacks.append(tracer)
                logger.info("LangSmith callback activado")
            except Exception as exc:
                logger.warning("No se pudo inicializar LangSmith", extra={"error": str(exc)})

        return callbacks
