from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from app.config import Settings, get_settings
from app.db import get_session
from app.intelligence.topic_explorer import (
    author_detail,
    explorer_overview,
    get_related_papers,
    list_authors,
    list_topics,
    topic_detail,
)
from app.publication import local_demo_corpus_preview_enabled

router = APIRouter(prefix="/api", tags=["explorer"])


@router.get("/explorer/overview")
def get_explorer_overview(
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, object]:
    return explorer_overview(session, demo_preview=local_demo_corpus_preview_enabled(settings))


@router.get("/topics")
def get_topics(
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    q: str | None = Query(default=None, max_length=500),
    min_papers: int | None = Query(default=None, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    return list_topics(
        session, q=q, min_papers=min_papers, limit=limit, offset=offset,
        demo_preview=local_demo_corpus_preview_enabled(settings),
    )


@router.get("/topics/{topic_id}")
def get_topic(
    topic_id: str,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, object]:
    detail = topic_detail(session, topic_id, demo_preview=local_demo_corpus_preview_enabled(settings))
    if detail is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    return detail


@router.get("/authors")
def get_authors(
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    q: str | None = Query(default=None, max_length=500),
    topic: str | None = Query(default=None, max_length=300),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    return list_authors(
        session, q=q, topic=topic, limit=limit, offset=offset,
        demo_preview=local_demo_corpus_preview_enabled(settings),
    )


@router.get("/authors/{author_id}")
def get_author(
    author_id: int,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, object]:
    detail = author_detail(session, author_id, demo_preview=local_demo_corpus_preview_enabled(settings))
    if detail is None:
        raise HTTPException(status_code=404, detail="Author not found")
    return detail


@router.get("/papers/{paper_id}/related")
def related_papers(
    paper_id: str,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    limit: int = Query(default=5, ge=1, le=20),
) -> list[dict[str, object]]:
    return get_related_papers(
        session, paper_id, limit=limit,
        demo_preview=local_demo_corpus_preview_enabled(settings),
    )
