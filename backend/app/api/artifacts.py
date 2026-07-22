from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.config import Settings, get_settings
from app.db import get_session
from app.intelligence.paper_artifact_generator import (
    ARTIFACT_TYPES,
    artifact_diagnostics,
    batch_generate_paper_artifacts,
    generate_paper_artifacts,
    get_latest_paper_artifact,
    list_paper_artifacts,
)
from app.models import Paper
from app.publication import is_local_demo_content, is_public_content, local_demo_corpus_preview_enabled
from app.security import AuthenticatedActor, get_optional_actor, require_admin, require_reviewer

router = APIRouter(prefix="/api", tags=["artifacts"])


class GenerateArtifactsRequest(BaseModel):
    artifact_types: list[str] = Field(
        default_factory=lambda: ["paper_intelligence_bundle", "podcast_script"],
        min_length=1,
        max_length=10,
    )
    provider: str = Field(default="auto", min_length=1, max_length=40)
    max_chunks: int = Field(default=12, ge=1, le=30)
    overwrite: bool = False


class BatchGenerateArtifactsRequest(BaseModel):
    paper_ids: list[str] = Field(default_factory=list, max_length=25)
    limit: int = Field(default=5, ge=1, le=25)
    artifact_types: list[str] = Field(
        default_factory=lambda: ["paper_intelligence_bundle", "podcast_script"],
        min_length=1,
        max_length=10,
    )
    provider: str = Field(default="auto", min_length=1, max_length=40)
    max_chunks: int = Field(default=12, ge=1, le=30)
    overwrite: bool = False


@router.post("/papers/artifacts/generate-batch")
def generate_artifacts_batch(
    request: BatchGenerateArtifactsRequest,
    session: Annotated[Session, Depends(get_session)],
    _actor: Annotated[AuthenticatedActor, Depends(require_admin)],
) -> dict[str, object]:
    validate_artifact_types(request.artifact_types)
    return batch_generate_paper_artifacts(
        session,
        paper_ids=request.paper_ids,
        limit=request.limit,
        artifact_types=request.artifact_types,
        provider=request.provider,
        max_chunks=request.max_chunks,
        overwrite=request.overwrite,
    )


@router.post("/papers/{paper_id}/artifacts/generate")
def generate_artifacts_for_paper(
    paper_id: str,
    request: GenerateArtifactsRequest,
    session: Annotated[Session, Depends(get_session)],
    _actor: Annotated[AuthenticatedActor, Depends(require_reviewer)],
) -> dict[str, object]:
    if session.get(Paper, paper_id) is None:
        raise HTTPException(status_code=404, detail="Paper not found")
    validate_artifact_types(request.artifact_types)
    return generate_paper_artifacts(
        session,
        paper_id,
        request.artifact_types,
        provider=request.provider,
        max_chunks=request.max_chunks,
        overwrite=request.overwrite,
    )


@router.get("/papers/{paper_id}/artifacts")
def get_artifacts_for_paper(
    paper_id: str,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> list[dict[str, object]]:
    paper = session.get(Paper, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found")
    demo_preview = local_demo_corpus_preview_enabled(settings)
    require_eligible_paper(session, paper, demo_preview=demo_preview)
    artifacts = list_paper_artifacts(session, paper_id, public=not demo_preview)
    if demo_preview:
        for artifact in artifacts:
            mark_demo_artifact(artifact)
    return artifacts


@router.get("/papers/{paper_id}/artifacts/{artifact_type}")
def get_artifact_for_paper(
    paper_id: str,
    artifact_type: str,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, object]:
    paper = session.get(Paper, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found")
    demo_preview = local_demo_corpus_preview_enabled(settings)
    require_eligible_paper(session, paper, demo_preview=demo_preview)
    if artifact_type not in ARTIFACT_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported artifact type")
    artifact = get_latest_paper_artifact(session, paper_id, artifact_type, public=not demo_preview)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    if demo_preview:
        mark_demo_artifact(artifact)
    return artifact


@router.get("/artifacts/diagnostics")
def diagnostics(
    session: Annotated[Session, Depends(get_session)],
    _actor: Annotated[AuthenticatedActor, Depends(require_reviewer)],
) -> dict[str, object]:
    return artifact_diagnostics(session)


def validate_artifact_types(artifact_types: list[str]) -> None:
    invalid = [artifact_type for artifact_type in artifact_types if artifact_type not in ARTIFACT_TYPES]
    if invalid:
        raise HTTPException(status_code=400, detail=f"Unsupported artifact types: {', '.join(invalid)}")


def require_eligible_paper(
    session: Session,
    paper: Paper,
    *,
    demo_preview: bool = False,
) -> None:
    if not is_public_content(session, paper) and not (demo_preview and is_local_demo_content(session, paper)):
        raise HTTPException(status_code=404, detail="Paper artifacts are not publicly available")


def mark_demo_artifact(artifact: dict[str, object]) -> None:
    artifact["demo_preview"] = True
    artifact["corpus_access_mode"] = "unreviewed_local_demo_preview"
    warnings = list(artifact.get("warnings") or [])
    warnings.append("Local demo preview: this generated output may not be reviewed or approved for publication.")
    artifact["warnings"] = warnings
