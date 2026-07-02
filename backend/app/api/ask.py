from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlmodel import Session, desc, func, select

from app.db import get_session
from app.indexing.embedder import index_diagnostics
from app.intelligence.rag_answerer import ask_diagnostics, ask_question, serialize_answer
from app.models import Chunk, RAGAnswer

router = APIRouter(prefix="/api", tags=["ask"])


class AskRequest(BaseModel):
    question: str = Field(min_length=1)
    mode: Literal["keyword", "semantic", "hybrid"] = "hybrid"
    top_k: int = Field(default=5, ge=1, le=20)
    audience: str = "general"
    max_words: int = Field(default=250, ge=50, le=600)
    provider: str = "auto"


@router.post("/ask")
def ask(request: AskRequest, session: Annotated[Session, Depends(get_session)]) -> dict[str, object]:
    return ask_question(
        session,
        request.question,
        mode=request.mode,
        top_k=request.top_k,
        audience=request.audience,
        max_words=request.max_words,
        provider_name=request.provider,
    )


@router.get("/ask/history")
def ask_history(
    session: Annotated[Session, Depends(get_session)],
    limit: int = Query(default=20, ge=1, le=100),
) -> list[dict[str, object]]:
    answers = session.exec(select(RAGAnswer).order_by(desc(RAGAnswer.created_at)).limit(limit)).all()
    return [serialize_answer(answer) for answer in answers]


@router.get("/ask/diagnostics")
def diagnostics(session: Annotated[Session, Depends(get_session)]) -> dict[str, object]:
    base = ask_diagnostics(session)
    semantic = index_diagnostics()
    searchable_chunks = session.exec(select(func.count()).select_from(Chunk)).one()
    return {
        **base,
        "searchable_chunks": searchable_chunks,
        "semantic_indexed_chunks": semantic["semantic_indexed_chunks"],
    }


@router.get("/ask/{answer_id}")
def get_answer(answer_id: str, session: Annotated[Session, Depends(get_session)]) -> dict[str, object]:
    answer = session.get(RAGAnswer, answer_id)
    if answer is None:
        raise HTTPException(status_code=404, detail="Answer not found")
    return serialize_answer(answer)
