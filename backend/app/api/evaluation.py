from typing import Annotated
from typing import Any

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.db import get_session
from app.evaluation.dashboard import build_evaluation_dashboard
from app.api.public import redact_local_paths

router = APIRouter(prefix="/api/evaluation", tags=["evaluation"])


@router.get("/dashboard")
def evaluation_dashboard(session: Annotated[Session, Depends(get_session)]) -> dict[str, object]:
    return redact_local_paths(public_evaluation_projection(build_evaluation_dashboard(session)))


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
