import re
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from src.controllers.chat_controller import handle_chat
from src.repositories import get_db

router = APIRouter()


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000, description="Pregunta del usuario")
    user: str = Field(min_length=1, max_length=100, description="Identificador del usuario")
    session_id: Optional[str] = Field(default=None, max_length=36)

    @field_validator("question")
    @classmethod
    def question_no_obvious_injection(cls, v: str) -> str:
        _quick_patterns = [
            r"ignore (all )?previous instructions",
            r"disregard (your )?system prompt",
            r"you are now\b",
            r"\bDAN\b",
        ]
        low = v.lower()
        for pat in _quick_patterns:
            if re.search(pat, low):
                raise ValueError("La solicitud contiene contenido no permitido.")
        return v

    @field_validator("user")
    @classmethod
    def user_alphanumeric(cls, v: str) -> str:
        if not re.match(r"^[\w@.\-]+$", v):
            raise ValueError("El campo 'user' contiene caracteres no permitidos.")
        return v


class ChatResponse(BaseModel):
    user: str
    answer: str
    session_id: str
    trace_id: str


@router.post("/api/chat", response_model=ChatResponse, tags=["chat"])
async def chat(request: ChatRequest, db: Session = Depends(get_db)) -> ChatResponse:
    result = await handle_chat(
        question=request.question,
        user=request.user,
        session_id=request.session_id,
        db=db,
    )
    return ChatResponse(**result)
