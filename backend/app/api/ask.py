from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlmodel import Session, desc, func, select

from app.db import get_session
from app.api.index_health import public_index_projection_health
from app.indexing.embedder import eligible_chunks
from app.config import Settings, get_settings
from app.intelligence.rag_answerer import ask_diagnostics, ask_question, serialize_answer
from app.models import Chunk, RAGAnswer
from app.security import AuthenticatedActor, require_reviewer

router = APIRouter(prefix="/api", tags=["ask"])
PUBLIC_SOURCE_SNIPPET_MAX_CHARS = 700


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2_000)
    mode: Literal["keyword", "feature_hashing", "dense", "hybrid"] = "keyword"
    top_k: int = Field(default=5, ge=1, le=20)
    audience: str = Field(default="general", min_length=1, max_length=80)
    max_words: int = Field(default=250, ge=50, le=600)
    provider: Literal["auto", "offline_extractive", "ollama"] = "auto"
    model: str | None = Field(default=None, max_length=200)
    paper_id: str | None = Field(default=None, max_length=200)


@router.post("/ask")
def ask(
    request: AskRequest,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, object]:
    if request.provider != "auto" and request.provider not in settings.allowed_llm_providers:
        raise HTTPException(status_code=400, detail="Requested LLM provider is not enabled")
    try:
        internal_response = ask_question(
            session,
            request.question,
            mode=request.mode,
            top_k=request.top_k,
            audience=request.audience,
            max_words=request.max_words,
            provider_name=request.provider,
            model_name=request.model,
            paper_id=request.paper_id,
            persist=False,
            retrieval_scope="public",
            provider_settings=settings,
        )
        return serialize_public_ask_response(internal_response)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def bounded_public_snippet(value: object, *, max_chars: int = PUBLIC_SOURCE_SNIPPET_MAX_CHARS) -> str:
    normalized = " ".join(str(value or "").split())
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max_chars - 1].rstrip() + "…"


def serialize_public_ask_response(response: dict[str, object]) -> dict[str, object]:
    """Remove full source text after generation while retaining bounded locators."""

    public_chunks: list[dict[str, object]] = []
    for raw in list(response.get("retrieved_chunks") or []):
        if not isinstance(raw, dict):
            continue
        chunk = {key: value for key, value in raw.items() if key != "text"}
        chunk["snippet"] = bounded_public_snippet(raw.get("snippet") or raw.get("text"))
        public_chunks.append(chunk)
    public_citations: list[dict[str, object]] = []
    for raw in list(response.get("citations") or []):
        if not isinstance(raw, dict):
            continue
        citation = dict(raw)
        citation["snippet"] = bounded_public_snippet(raw.get("snippet"))
        public_citations.append(citation)
    return {
        **response,
        "retrieved_chunks": public_chunks,
        "citations": public_citations,
        "source_text_delivery": "bounded_snippets_only",
    }


@router.get("/ask/history")
def ask_history(
    session: Annotated[Session, Depends(get_session)],
    _actor: Annotated[AuthenticatedActor, Depends(require_reviewer)],
    limit: int = Query(default=20, ge=1, le=100),
) -> list[dict[str, object]]:
    answers = session.exec(select(RAGAnswer).order_by(desc(RAGAnswer.created_at)).limit(limit)).all()
    return [serialize_answer(answer) for answer in answers]


@router.get("/ask/diagnostics")
def diagnostics(
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, object]:
    base = ask_diagnostics(session, settings)
    searchable_chunks = len(eligible_chunks(session, public_only=True))
    index_health = public_index_projection_health(
        session,
        public_eligible_chunks=searchable_chunks,
    )
    return {
        **base,
        "searchable_chunks": searchable_chunks,
        "raw_chunks": None,
        "semantic_indexed_chunks": None,
        "semantic_index_deprecation": "Feature hashing is lexical, not semantic.",
        "keyword_index": index_health["keyword"],
        "feature_hashing_index": index_health["feature_hashing"],
        "dense_index": index_health["dense"],
    }


@router.get("/ask/{answer_id}")
def get_answer(
    answer_id: str,
    session: Annotated[Session, Depends(get_session)],
    _actor: Annotated[AuthenticatedActor, Depends(require_reviewer)],
) -> dict[str, object]:
    answer = session.get(RAGAnswer, answer_id)
    if answer is None:
        raise HTTPException(status_code=404, detail="Answer not found")
    return serialize_answer(answer)
