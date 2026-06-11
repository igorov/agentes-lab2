import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI

from src.routes.chat import router
from src.utils.logger import get_logger

logger = get_logger(__name__)


def _init_qdrant():
    """Inicializa el vector store de Qdrant. Retorna None si las credenciales no están configuradas."""
    import os
    from qdrant_client import QdrantClient
    from langchain_qdrant import QdrantVectorStore
    from langchain_openai import OpenAIEmbeddings

    qdrant_url = os.getenv("QDRANT_URL")
    qdrant_api_key = os.getenv("QDRANT_API_KEY")
    collection_name = os.getenv("QDRANT_COLLECTION_NAME", "documents")
    if not qdrant_url or not qdrant_api_key:
        logger.info("QDRANT_URL o QDRANT_API_KEY no configurados — omitiendo tool RAG")
        return None
    client = QdrantClient(url=qdrant_url, api_key=qdrant_api_key)
    embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
    return QdrantVectorStore(client=client, collection_name=collection_name, embedding=embeddings)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: conectar a Neon MCP y Qdrant, luego reinicializar el agente con todas las tools."""
    from src.services.tools import load_neon_tools, create_retrieve_context_tool, get_all_tools
    from src.services.agent_service import init_agent

    mcp_tools = []
    try:
        mcp_tools, _ = await load_neon_tools()
        if mcp_tools:
            logger.info("Neon MCP conectado — %d tool(s) disponibles", len(mcp_tools))
    except Exception as exc:
        logger.warning("Error conectando a Neon MCP: %s. Continuando sin tools MCP.", exc)

    rag_tool = None
    try:
        qdrant_store = _init_qdrant()
        if qdrant_store is not None:
            rag_tool = create_retrieve_context_tool(qdrant_store)
            logger.info("Tool RAG con Qdrant inicializada")
    except Exception as exc:
        logger.warning("Error inicializando Qdrant RAG: %s. Continuando sin tool RAG.", exc)

    all_tools = get_all_tools(mcp_tools or None, rag_tool=rag_tool)
    init_agent(all_tools)
    logger.info("Registro de tools listo: %s", [t.name for t in all_tools])

    yield


app = FastAPI(
    title="Agente Simple",
    description="Agente conversacional con LangChain create_agent, FastAPI y PostgreSQL.",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(router)


if __name__ == "__main__":
    logger.info("Iniciando servidor en puerto 8080")
    uvicorn.run("src.main:app", host="0.0.0.0", port=8081, reload=False)
