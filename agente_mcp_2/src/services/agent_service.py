import os
import time
import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import HTTPException
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from sqlalchemy.orm import Session

from src.services.guardrails import (
    brand_safety_check,
    pii_redact,
    scan_input,
    scan_output,
)
from src.services.prompt import INSTRUCTIONS
from src.repositories.history_repository import HistoryRepository
from src.repositories.models.history import History
from src.utils.environment import (
    HISTORY_LIMIT,
    OPENAI_API_KEY,
    OPENAI_MODEL,
    LANGSMITH_API_KEY,
    LANGSMITH_PROJECT,
    LANGSMITH_ENDPOINT,
)
from src.services.tools import LOCAL_TOOLS, get_all_tools
from src.utils.logger import get_logger

logger = get_logger(__name__)

os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY

if LANGSMITH_API_KEY:
    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGSMITH_API_KEY"] = LANGSMITH_API_KEY
    os.environ["LANGSMITH_PROJECT"] = LANGSMITH_PROJECT
    os.environ["LANGSMITH_ENDPOINT"] = LANGSMITH_ENDPOINT
    _langsmith_enabled = True
else:
    os.environ["LANGSMITH_TRACING"] = "false"
    _langsmith_enabled = False


#SYSTEM_PROMPT = (Path(__file__).parent / "system_prompt.txt").read_text(encoding="utf-8")


_agent = create_agent(
    model=f"openai:{OPENAI_MODEL}",
    tools=LOCAL_TOOLS,
    system_prompt=INSTRUCTIONS,
)

logger.info(
    "LangSmith tracing %s",
    f"ACTIVADO (proyecto: {LANGSMITH_PROJECT})" if _langsmith_enabled else "DESACTIVADO",
)


def init_agent(tools: list) -> None:
    """Reinicializa el agente global con el conjunto de tools provisto."""
    global _agent
    _agent = create_agent(
        model=f"openai:{OPENAI_MODEL}",
        tools=tools,
        system_prompt=INSTRUCTIONS,
    )
    logger.info("Agente reinicializado con %d tool(s): %s", len(tools), [t.name for t in tools])


class AgentService:
    def __init__(self, db: Session) -> None:
        self._repo = HistoryRepository(db)

    async def chat(self, question: str, user: str, session_id: Optional[str]) -> dict:
        is_new_session = not session_id
        if is_new_session:
            logger.info("Creando nueva sesión")
            session_id = str(uuid.uuid4())

        trace_id = str(uuid.uuid4())

        logger.info(
            "Iniciando chat",
            extra={"session_id": session_id, "trace_id": trace_id, "user": user},
        )

        # --- Guardrail de INPUT (Lab 3 / LLM01) ---
        injection_scan = scan_input(question)
        if injection_scan["blocked"]:
            logger.warning(
                "Solicitud bloqueada por guardrail de input",
                extra={"trace_id": trace_id, "reasons": injection_scan["reasons"]},
            )
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "solicitud_bloqueada",
                    "message": "Tu solicitud no pudo procesarse por razones de seguridad.",
                    "trace_id": trace_id,
                },
            )

        # Redactar PII del input antes de enviarlo al agente (Lab 4 / LLM02)
        safe_question = pii_redact(question, apply_to="input")

        t0 = time.perf_counter()
        history_records = [] if is_new_session else self._repo.get_by_session_id(session_id, limit=HISTORY_LIMIT)
        t_history = time.perf_counter() - t0

        history_messages: List[BaseMessage] = []
        for record in history_records:
            history_messages.append(HumanMessage(content=record.question))
            history_messages.append(AIMessage(content=record.answer))

        t0 = time.perf_counter()
        result = await self._run_agent(
            question=safe_question,
            session_id=session_id,
            trace_id=trace_id,
            user=user,
            history=history_messages,
        )
        t_agent = time.perf_counter() - t0

        # --- Guardrails de OUTPUT (Lab 3 + Lab 5 / LLM07, LLM09) ---
        raw_answer: str = result["answer"]

        output_scan = scan_output(raw_answer)
        if output_scan["blocked"]:
            logger.warning(
                "Respuesta bloqueada por guardrail de output",
                extra={"trace_id": trace_id, "reasons": output_scan["reasons"]},
            )
            raw_answer = "Lo siento, no puedo proporcionar esa información."

        brand_check = brand_safety_check(raw_answer)
        if not brand_check["safe"]:
            logger.warning(
                "Respuesta bloqueada por brand safety",
                extra={"trace_id": trace_id, "violations": brand_check["violations"]},
            )
            raw_answer = "Lo siento, no puedo proporcionar esa información."

        # Redactar PII del output antes de devolverlo al usuario (Lab 4 / LLM02)
        final_answer = pii_redact(raw_answer, apply_to="output")

        t0 = time.perf_counter()
        # Guardamos la pregunta con PII redactado (GDPR: minimización de datos)
        self._repo.save(
            History(
                trace_id=trace_id,
                session_id=session_id,
                question=safe_question,
                answer=final_answer,
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
            "answer": final_answer,
            "session_id": session_id,
            "trace_id": trace_id,
        }

    async def _run_agent(
        self,
        question: str,
        session_id: str,
        trace_id: str,
        user: str,
        history: List[BaseMessage],
    ) -> dict:
        messages: List[BaseMessage] = history + [HumanMessage(content=question)]

        run_config = {
            "callbacks": [],
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

        result = await _agent.ainvoke({"messages": messages}, config=run_config)

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

