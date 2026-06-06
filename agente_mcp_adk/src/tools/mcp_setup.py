from typing import Optional

from src.config import NEON_API_KEY
from src.utils.logger import get_logger

logger = get_logger(__name__)


def build_mcp_toolset() -> Optional[object]:
    """Crea el MCPToolset para Neon. Retorna None si NEON_API_KEY no está configurado."""
    if not NEON_API_KEY:
        logger.info("NEON_API_KEY no configurado — MCP Neon deshabilitado")
        return None

    try:
        from google.adk.tools.mcp_tool.mcp_toolset import McpToolset, StreamableHTTPConnectionParams

        toolset = McpToolset(
            connection_params=StreamableHTTPConnectionParams(
                url="https://mcp.neon.tech/mcp",
                headers={"Authorization": f"Bearer {NEON_API_KEY}"},
            )
        )
        logger.info("McpToolset Neon configurado")
        return toolset

    except Exception as exc:
        logger.warning("Error configurando Neon MCP: %s — deshabilitado", exc)
        return None
