import uuid
from typing import Callable, Optional

from src.config import DATABASE_URL
from src.repositories.database import get_session_factory
from src.repositories.history_repository import HistoryRepository
from src.repositories.models.history import History
from src.utils.logger import get_logger

logger = get_logger(__name__)


def build_history_callback() -> Optional[Callable]:
    """
    Crea el callback after_agent que persiste cada turno en PostgreSQL.
    Retorna None si DATABASE_URL no está configurado.
    """
    if not DATABASE_URL:
        logger.info("DATABASE_URL no configurado — historial no se persistirá")
        return None

    session_factory = get_session_factory()
    if session_factory is None:
        logger.warning("No se pudo inicializar la BD — historial no se persistirá")
        return None

    def after_agent_callback(callback_context) -> None:
        """Guarda el par pregunta/respuesta del turno actual en la BD."""
        try:
            invocation_ctx = callback_context.invocation_context

            # Extraer pregunta del usuario
            user_content = invocation_ctx.user_content
            if not user_content or not user_content.parts:
                return None

            question = "".join(
                part.text
                for part in user_content.parts
                if hasattr(part, "text") and part.text
            )
            if not question.strip():
                return None

            # Extraer respuesta del agente desde los eventos de la sesión
            session = invocation_ctx.session
            invocation_id = getattr(invocation_ctx, "invocation_id", None)
            agent_name = invocation_ctx.agent.name

            answer = _extract_agent_answer(session.events, agent_name, invocation_id)

            # Persistir en PostgreSQL
            db = session_factory()
            try:
                repo = HistoryRepository(db)
                repo.save(
                    History(
                        trace_id=str(uuid.uuid4()),
                        session_id=session.id,
                        question=question,
                        answer=answer or "(sin respuesta)",
                        input_tokens=0,
                        output_tokens=0,
                    )
                )
                logger.info("Historial guardado", extra={"session_id": session.id})
            finally:
                db.close()

        except Exception as exc:
            logger.warning("Error al guardar historial: %s", exc)

        return None

    return after_agent_callback


def _extract_agent_answer(events: list, agent_name: str, invocation_id: Optional[str]) -> str:
    """Busca el último texto de respuesta del agente en los eventos de la sesión."""
    for event in reversed(events):
        # Filtrar por invocación actual si está disponible
        if invocation_id and getattr(event, "invocation_id", None) != invocation_id:
            continue

        if event.author != agent_name:
            continue

        if not event.content or not event.content.parts:
            continue

        for part in event.content.parts:
            if hasattr(part, "text") and part.text:
                return part.text

    return ""
