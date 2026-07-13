from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, desc, select

from app.db import get_session
from app.intelligence.extension_recommender import (
    ExtensionFinderRequest,
    recommendation_diagnostics,
    recommend_extensions,
    serialize_recommendation,
)
from app.models import ThesisRecommendation
from app.security import AuthenticatedActor, require_reviewer

router = APIRouter(prefix="/api/recommendations", tags=["recommendations"])


@router.post("/extensions")
def create_extension_recommendations(
    request: ExtensionFinderRequest,
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, object]:
    return recommend_extensions(session, request, persist=False)


@router.get("/extensions/history")
def extension_recommendation_history(
    session: Annotated[Session, Depends(get_session)],
    _actor: Annotated[AuthenticatedActor, Depends(require_reviewer)],
    limit: int = Query(default=20, ge=1, le=100),
) -> list[dict[str, object]]:
    records = session.exec(
        select(ThesisRecommendation).order_by(desc(ThesisRecommendation.created_at)).limit(limit)
    ).all()
    return [serialize_recommendation(record) for record in records]


@router.get("/extensions/diagnostics")
def extension_recommendation_diagnostics(
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, object]:
    return recommendation_diagnostics(session)


@router.get("/extensions/{recommendation_id}")
def get_extension_recommendation(
    recommendation_id: str,
    session: Annotated[Session, Depends(get_session)],
    _actor: Annotated[AuthenticatedActor, Depends(require_reviewer)],
) -> dict[str, object]:
    record = session.get(ThesisRecommendation, recommendation_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    return serialize_recommendation(record)
