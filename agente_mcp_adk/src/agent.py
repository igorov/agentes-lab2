"""
Agente ADK — migración de agente_mcp de LangChain/LangGraph a Google ADK.

Ejecutar la interfaz nativa de desarrollo desde claude_agente_mcp_adk/:
    adk web .

Variables de entorno requeridas (ver .env.example):
    OPENAI_API_KEY, OPENAI_MODEL
Opcionales:
    DATABASE_URL (historial PostgreSQL)
    QDRANT_URL, QDRANT_API_KEY, QDRANT_COLLECTION_NAME (RAG)
    NEON_API_KEY (MCP Neon BD)
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Agrega claude_agente_mcp_adk/ al path para que src.* sea importable
_project_root = Path(__file__).parent.parent
sys.path.insert(0, str(_project_root))

# Carga .env desde la raíz del proyecto (ADK ya lo hace, pero esto es por si se ejecuta directamente)
load_dotenv(_project_root / ".env")

from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm

from src.callbacks.history_callback import build_history_callback
from src.config import OPENAI_API_KEY, OPENAI_MODEL
from src.tools.local_tools import get_current_date
from src.tools.mcp_setup import build_mcp_toolset
from src.tools.rag_tool import build_rag_tool
from src.utils.logger import get_logger

logger = get_logger(__name__)

# LiteLLM lee OPENAI_API_KEY del entorno
os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY

SYSTEM_INSTRUCTION = (
    "Eres un asistente útil y amigable, tu nombre es Pan. "
    "Responde siempre de forma clara y concisa."
)

# --- Herramientas ---
_tools: list = [get_current_date]

_mcp = build_mcp_toolset()
if _mcp is not None:
    _tools.append(_mcp)
    logger.info("Herramienta MCP Neon agregada al agente")

_rag = build_rag_tool()
if _rag is not None:
    _tools.append(_rag)
    logger.info("Herramienta RAG (Qdrant) agregada al agente")

# --- Callback de historial ---
_after_agent_cb = build_history_callback()

# --- Modelo: OpenAI vía LiteLLM ---
_model_id = OPENAI_MODEL if OPENAI_MODEL.startswith("openai/") else f"openai/{OPENAI_MODEL}"

# --- Agente raíz (requerido por adk web) ---
root_agent = LlmAgent(
    name="Pan",
    model=LiteLlm(model=_model_id),
    description="Asistente conversacional con acceso a BD vía MCP y búsqueda en base de conocimiento",
    instruction=SYSTEM_INSTRUCTION,
    tools=_tools,
    after_agent_callback=_after_agent_cb,
)

logger.info(
    "Agente inicializado",
    extra={"model": _model_id, "tools": len(_tools), "history_enabled": _after_agent_cb is not None},
)
