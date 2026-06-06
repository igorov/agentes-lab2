from typing import Callable, Optional

from src.config import OPENAI_API_KEY, QDRANT_API_KEY, QDRANT_COLLECTION_NAME, QDRANT_URL
from src.utils.logger import get_logger

logger = get_logger(__name__)


def build_rag_tool() -> Optional[Callable]:
    """Construye la función de RAG con Qdrant. Retorna None si no está configurado."""
    if not QDRANT_URL or not QDRANT_API_KEY:
        logger.info("QDRANT_URL o QDRANT_API_KEY no configurados — RAG deshabilitado")
        return None

    try:
        from openai import OpenAI
        from qdrant_client import QdrantClient

        openai_client = OpenAI(api_key=OPENAI_API_KEY)
        qdrant_client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
        collection = QDRANT_COLLECTION_NAME

        def retrieve_context(query: str) -> str:
            """Busca informacion en la base de conocimiento. Usala cuando el usuario pregunte sobre cursos, docentes, graduados, horarios, matriculas, programas, sedes o cualquier informacion relacionada a la academia."""
            try:
                embedding_resp = openai_client.embeddings.create(
                    model="text-embedding-3-small",
                    input=query,
                )
                embedding = embedding_resp.data[0].embedding

                results = qdrant_client.search(
                    collection_name=collection,
                    query_vector=embedding,
                    limit=5,
                )

                if not results:
                    return "No se encontro informacion relevante."

                serialized = "\n\n".join(
                    f"Fuente: {hit.payload}\nContenido: {hit.payload.get('page_content', '')}"
                    for hit in results
                )
                return serialized or "No se encontro informacion relevante."

            except Exception as exc:
                logger.error("Error en RAG tool: %s", exc)
                return "Error al buscar informacion en la base de conocimiento."

        logger.info("RAG tool inicializado con Qdrant (%s)", collection)
        return retrieve_context

    except Exception as exc:
        logger.warning("Error inicializando RAG tool: %s — deshabilitado", exc)
        return None
