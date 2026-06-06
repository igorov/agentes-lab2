from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.config import DATABASE_URL
from src.repositories.models.history import Base
from src.utils.logger import get_logger

logger = get_logger(__name__)

_engine = None
_SessionLocal = None


def get_engine():
    global _engine
    if _engine is None and DATABASE_URL:
        _engine = create_engine(DATABASE_URL, pool_pre_ping=True)
        Base.metadata.create_all(_engine)
        logger.info("Motor de base de datos inicializado y tablas creadas")
    return _engine


def get_session_factory():
    global _SessionLocal
    engine = get_engine()
    if engine is not None and _SessionLocal is None:
        _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return _SessionLocal
