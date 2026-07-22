from typing import Annotated
from typing import Any

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.config import Settings, get_settings
from app.db import get_session
from app.evaluation.dashboard import build_evaluation_dashboard
from app.api.public import redact_local_paths
from app.publication import local_demo_corpus_preview_enabled

router = APIRouter(prefix="/api/evaluation", tags=["evaluation"])


@router.get("/dashboard")
def evaluation_dashboard(
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, object]:
    demo_preview = local_demo_corpus_preview_enabled(settings)
    dashboard = redact_local_paths(build_evaluation_dashboard(session))
    if not demo_preview:
        return public_evaluation_projection(dashboard)
    dashboard["demo_preview"] = True
    dashboard["corpus_access_mode"] = "unreviewed_local_demo_preview"
    dashboard["overall_quality"] = {
        **dict(dashboard.get("overall_quality") or {}),
        "scope": "technical_demo",
        "operational_counts_visible": True,
        "notice": "Local demo preview includes technical-corpus and draft-output counts.",
    }
    return dashboard


def public_evaluation_projection(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep aggregate study evidence public without exposing live review operations."""

    projected = dict(payload)
    projected["overall_quality"] = {
        "scope": "public_projection",
        "operational_counts_visible": False,
        "notice": "Live technical-corpus, draft-output, and review-event counts are available only to reviewers.",
    }
    artifact = projected.get("artifact")
    if isinstance(artifact, dict):
        protected_keys = {
            "ai_reviewed_count",
            "needs_reprocess_count",
            "review_event_count",
            "artifact_count",
        }
        projected["artifact"] = {
            key: value for key, value in artifact.items() if key not in protected_keys
        } | {
            "operational_counts_visible": False,
        }
    return projected
