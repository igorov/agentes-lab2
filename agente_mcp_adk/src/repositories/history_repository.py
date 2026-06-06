from sqlalchemy.orm import Session

from src.repositories.models.history import History


class HistoryRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def save(self, history: History) -> History:
        self.db.add(history)
        self.db.commit()
        self.db.refresh(history)
        return history

    def get_by_session_id(self, session_id: str, limit: int = 10) -> list[History]:
        return (
            self.db.query(History)
            .filter(History.session_id == session_id)
            .order_by(History.created_at.desc())
            .limit(limit)
            .all()[::-1]
        )
