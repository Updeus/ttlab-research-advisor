from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, desc, select

from app.config import Settings, get_settings
from app.db import get_session
from app.intelligence.extension_recommender import (
    ExtensionFinderRequest,
    recommendation_diagnostics,
    recommend_extensions,
    serialize_recommendation,
)
from app.intelligence.idea_generator import (
    IdeaGenerationFailure,
    IdeaGenerationRequest,
    generate_ideas,
)
from app.indexing.retriever import sanitize_public_retrieval_warnings
from app.models import ThesisRecommendation
from app.publication import local_demo_corpus_preview_enabled
from app.security import AuthenticatedActor, require_reviewer

router = APIRouter(prefix="/api/recommendations", tags=["recommendations"])


@router.post("/ideas")
def create_ideas(
    request: IdeaGenerationRequest,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, object]:
    if "ollama" not in {provider.strip().lower() for provider in settings.allowed_llm_providers}:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "ollama_unavailable",
                "message": "Ollama idea generation is not enabled. Enable the approved local provider and retry.",
                "retryable": True,
            },
        )
    demo_preview = local_demo_corpus_preview_enabled(settings)
    try:
        response = generate_ideas(
            session,
            request,
            settings=settings,
            retrieval_scope="technical" if demo_preview else "public",
        )
    except IdeaGenerationFailure as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": str(exc), "retryable": exc.retryable},
        ) from exc
    response["warnings"] = sanitize_public_retrieval_warnings(
        list(response.get("warnings") or [])
    )
    response["demo_preview"] = demo_preview
    response["corpus_access_mode"] = (
        "unreviewed_local_demo_preview" if demo_preview else "approved_public_projection"
    )
    if demo_preview:
        response.setdefault("warnings", []).append(
            "Local demo preview uses technically eligible papers that may not be publication-approved or rights-cleared."
        )
    return response


@router.post("/extensions")
def create_extension_recommendations(
    request: ExtensionFinderRequest,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, object]:
    demo_preview = local_demo_corpus_preview_enabled(settings)
    response = recommend_extensions(
        session,
        request,
        persist=False,
        retrieval_scope="technical" if demo_preview else "public",
    )
    response["demo_preview"] = demo_preview
    response["corpus_access_mode"] = (
        "unreviewed_local_demo_preview" if demo_preview else "approved_public_projection"
    )
    if demo_preview:
        response.setdefault("warnings", []).append(
            "Local demo preview uses technically eligible papers that may not be publication-approved or rights-cleared."
        )
    return response


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
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, object]:
    return recommendation_diagnostics(
        session,
        demo_preview=local_demo_corpus_preview_enabled(settings),
    )


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
