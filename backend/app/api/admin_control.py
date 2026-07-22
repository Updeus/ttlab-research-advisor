from __future__ import annotations

import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session, func, select

from app.admin_accounts import SENSITIVE_CONFIRMATION_MINUTES, aware, create_admin_user, public_admin, verify_password
from app.api.admin import (
    apply_review_metadata,
    artifact_correction_blockers,
    author_alias_approval_blockers,
    author_approval_blockers,
    author_topic_approval_blockers,
    create_review_event,
    paper_topic_approval_blockers,
    recommendation_correction_blockers,
    serialize_admin_review_requests,
    topic_approval_blockers,
)
from app.config import Settings, get_settings
from app.db import get_session
from app.features import FEATURE_DEFINITIONS, feature_payload, set_feature
from app.intelligence.local_llms import list_ollama_models
from app.models import Author, AuthorAlias, AuthorTopic, IngestionCandidate, Paper, PaperArtifact, PaperTopic, RAGAnswer, ThesisRecommendation, Topic
from app.models.admin import AdminSession, AdminUser, BulkOperation, OllamaModelPolicy
from app.publication import content_generation_diagnostics
from app.security import AuthenticatedActor, require_admin

router = APIRouter(
    prefix="/api/admin/control",
    tags=["admin-control"],
    dependencies=[Depends(require_admin)],
)


class FeatureUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
    disabled_message: str | None = Field(default=None, max_length=500)


class FeaturePreset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["enable_all", "disable_public"]


class CreateAdminRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    username: str = Field(min_length=3, max_length=80)
    display_name: str = Field(min_length=1, max_length=120)
    current_password: str = Field(min_length=1, max_length=256)


class AdminStateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    active: bool
    current_password: str = Field(min_length=1, max_length=256)


class PinModelsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: str | None = Field(default=None, max_length=256)


class ModelUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool | None = None
    is_default: bool | None = None


class BulkPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approval_mode: Literal["eligible", "catch_all"] = "eligible"
    item_types: list[Literal[
        "papers", "extractions", "authors", "aliases", "topics", "paper_topics",
        "author_topics", "artifacts", "answers", "recommendations",
    ]] = Field(default_factory=lambda: [
        "papers", "extractions", "authors", "aliases", "topics", "paper_topics",
        "author_topics", "artifacts", "answers", "recommendations",
    ])


class BulkExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: str
    preview_hash: str = Field(min_length=64, max_length=64)


class PublicationExecuteRequest(BulkExecuteRequest):
    rights_attested: bool
    attestation_note: str = Field(min_length=10, max_length=2_000)
    current_password: str | None = Field(default=None, max_length=256)


class CandidateImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_ids: list[str] = Field(min_length=1, max_length=200)


def now() -> datetime:
    return datetime.now(UTC)


def current_admin(session: Session, actor: AuthenticatedActor) -> AdminUser | None:
    return session.get(AdminUser, actor.actor_id) if actor.auth_method == "session" else None


def require_recent_password(session: Session, actor: AuthenticatedActor, password: str | None) -> None:
    if actor.local_demo_bypass:
        return
    verified_at = aware(actor.password_verified_at)
    if (
        actor.auth_method == "session"
        and verified_at is not None
        and verified_at >= now() - timedelta(minutes=SENSITIVE_CONFIRMATION_MINUTES)
    ):
        return
    user = current_admin(session, actor)
    if user is None or not password or not verify_password(user, password):
        raise HTTPException(
            status_code=403,
            detail="Re-enter your current administrator password; the previous confirmation is older than 15 minutes",
        )
    if actor.session_digest:
        admin_session = session.get(AdminSession, actor.session_digest)
        if admin_session is not None:
            admin_session.password_verified_at = now()
            session.add(admin_session)
            session.commit()


@router.get("/summary")
def control_summary(
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, object]:
    return {
        **feature_payload(session),
        "admin_count": int(session.exec(select(func.count()).select_from(AdminUser).where(AdminUser.active == True)).one()),  # noqa: E712
        "bulk_presets": ["approve_all_eligible"],
        "rights_attestation_required": True,
        "corpus_import_available": False,
        "corpus_import_blocker": "atomic_generation_promotion_not_implemented",
    }


@router.get("/ingestion-candidates")
def ingestion_candidates(session: Annotated[Session, Depends(get_session)]) -> dict[str, object]:
    items = session.exec(select(IngestionCandidate).order_by(IngestionCandidate.updated_at.desc())).all()
    return {
        "items": [
            {
                "candidate_id": item.candidate_id,
                "title": item.title,
                "source_url": item.source_url,
                "pdf_url": item.pdf_url,
                "comparison_status": item.comparison_status,
                "import_status": item.import_status,
                "discovered_at": item.discovered_at,
                "updated_at": item.updated_at,
            }
            for item in items
        ],
        "import_available": False,
        "import_blocker": "atomic_generation_promotion_not_implemented",
    }


@router.post("/ingestion-candidates/import")
def import_candidates(_payload: CandidateImportRequest) -> dict[str, object]:
    raise HTTPException(
        status_code=409,
        detail={
            "code": "candidate_import_blocked",
            "message": "Candidates were not imported because atomic corpus promotion and rollback are not implemented.",
            "candidate_data_preserved": True,
        },
    )


@router.patch("/features/{feature_key}")
def update_feature(
    feature_key: str,
    payload: FeatureUpdate,
    session: Annotated[Session, Depends(get_session)],
    actor: Annotated[AuthenticatedActor, Depends(require_admin)],
) -> dict[str, object]:
    try:
        item = set_feature(session, feature_key, payload.enabled, actor.actor_id, payload.disabled_message)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown feature") from exc
    return {"feature": {"key": item.feature_key, **FEATURE_DEFINITIONS[item.feature_key], "enabled": item.enabled, "disabled_message": item.disabled_message}}


@router.post("/features/preset")
def feature_preset(
    payload: FeaturePreset,
    session: Annotated[Session, Depends(get_session)],
    actor: Annotated[AuthenticatedActor, Depends(require_admin)],
) -> dict[str, object]:
    enabled = payload.action == "enable_all"
    for key in FEATURE_DEFINITIONS:
        set_feature(session, key, enabled, actor.actor_id, None if enabled else "Temporarily disabled by an administrator.")
    return feature_payload(session)


@router.get("/admins")
def list_admins(session: Annotated[Session, Depends(get_session)]) -> dict[str, object]:
    users = session.exec(select(AdminUser).order_by(AdminUser.username)).all()
    return {"items": [public_admin(user) for user in users]}


@router.post("/admins", status_code=201)
def add_admin(
    payload: CreateAdminRequest,
    session: Annotated[Session, Depends(get_session)],
    actor: Annotated[AuthenticatedActor, Depends(require_admin)],
) -> dict[str, object]:
    require_recent_password(session, actor, payload.current_password)
    temporary_password = secrets.token_urlsafe(18)
    try:
        user = create_admin_user(
            session,
            username=payload.username,
            display_name=payload.display_name,
            password=temporary_password,
            created_by=actor.actor_id,
            must_change_password=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"user": public_admin(user), "temporary_password": temporary_password, "shown_once": True}


@router.patch("/admins/{user_id}")
def set_admin_state(
    user_id: str,
    payload: AdminStateRequest,
    session: Annotated[Session, Depends(get_session)],
    actor: Annotated[AuthenticatedActor, Depends(require_admin)],
) -> dict[str, object]:
    require_recent_password(session, actor, payload.current_password)
    user = session.get(AdminUser, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Admin not found")
    if not payload.active and user_id == actor.actor_id:
        raise HTTPException(status_code=409, detail="You cannot deactivate your own account")
    if not payload.active:
        active_count = int(session.exec(select(func.count()).select_from(AdminUser).where(AdminUser.active == True)).one())  # noqa: E712
        if active_count <= 1:
            raise HTTPException(status_code=409, detail="The last active administrator cannot be deactivated")
    user.active = payload.active
    user.updated_at = now()
    session.add(user)
    session.commit()
    return {"user": public_admin(user)}


@router.get("/models")
def model_inventory(
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, object]:
    installed, warnings, reachable = list_ollama_models(base_url=settings.ollama_base_url, timeout=3.0)
    policies = {row.model_name: row for row in session.exec(select(OllamaModelPolicy)).all()}
    return {
        "provider_reachable": reachable,
        "warnings": warnings,
        "items": [
            {
                **model,
                "pinned": model.get("name") in policies,
                "enabled": policies[str(model.get("name"))].enabled if str(model.get("name")) in policies else False,
                "is_default": policies[str(model.get("name"))].is_default if str(model.get("name")) in policies else False,
                "pinned_digest": policies[str(model.get("name"))].digest if str(model.get("name")) in policies else None,
                "digest_matches": bool(
                    str(model.get("name")) in policies
                    and str(model.get("digest") or "").removeprefix("sha256:").lower() == policies[str(model.get("name"))].digest
                ),
            }
            for model in installed
        ],
    }


@router.post("/models/pin-installed")
def pin_installed_models(
    payload: PinModelsRequest,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    actor: Annotated[AuthenticatedActor, Depends(require_admin)],
) -> dict[str, object]:
    require_recent_password(session, actor, payload.current_password)
    installed, warnings, reachable = list_ollama_models(base_url=settings.ollama_base_url, timeout=5.0)
    if not reachable:
        raise HTTPException(status_code=503, detail="Ollama is not reachable")
    pinned: list[str] = []
    valid = [model for model in installed if str(model.get("name") or "") and len(str(model.get("digest") or "").removeprefix("sha256:")) == 64]
    if not valid:
        raise HTTPException(status_code=409, detail="Ollama reported no installed model with an immutable digest")
    existing = {row.model_name: row for row in session.exec(select(OllamaModelPolicy)).all()}
    for index, model in enumerate(valid):
        name = str(model["name"])
        row = existing.get(name) or OllamaModelPolicy(model_name=name, digest="0" * 64)
        row.digest = str(model["digest"]).removeprefix("sha256:").lower()
        row.enabled = True
        row.is_default = row.is_default or (not any(item.is_default for item in existing.values()) and index == 0)
        row.last_seen_at = now()
        row.updated_at = now()
        row.updated_by = actor.actor_id
        session.add(row)
        pinned.append(name)
    session.commit()
    return {"pinned": pinned, "count": len(pinned), "warnings": warnings, "future_models_automatically_allowed": False}


@router.patch("/models/{model_name:path}")
def update_model(
    model_name: str,
    payload: ModelUpdate,
    session: Annotated[Session, Depends(get_session)],
    actor: Annotated[AuthenticatedActor, Depends(require_admin)],
) -> dict[str, object]:
    row = session.get(OllamaModelPolicy, model_name)
    if row is None:
        raise HTTPException(status_code=404, detail="Pin the installed model before changing its policy")
    if payload.enabled is not None:
        row.enabled = payload.enabled
        if not row.enabled:
            row.is_default = False
    if payload.is_default:
        if not row.enabled:
            raise HTTPException(status_code=409, detail="A disabled model cannot be the default")
        for other in session.exec(select(OllamaModelPolicy).where(OllamaModelPolicy.is_default == True)).all():  # noqa: E712
            other.is_default = False
            session.add(other)
        row.is_default = True
    row.updated_by = actor.actor_id
    row.updated_at = now()
    session.add(row)
    session.commit()
    return {"model_name": row.model_name, "enabled": row.enabled, "is_default": row.is_default, "digest": row.digest}


def bulk_candidates(
    session: Session,
    requested: list[str],
    *,
    approval_mode: Literal["eligible", "catch_all"] = "eligible",
) -> dict[str, Any]:
    eligible: list[dict[str, str]] = []
    blocked: list[dict[str, object]] = []

    def consider(kind: str, item_id: str, current: str, blockers: list[str]) -> None:
        if current == "approved":
            return
        target = {"item_type": kind, "item_id": item_id}
        (blocked if blockers else eligible).append({**target, **({"blockers": blockers} if blockers else {})})

    if "papers" in requested:
        for item in session.exec(select(Paper)).all():
            blockers = (
                ["missing_pdf"]
                if approval_mode == "catch_all" and item.pdf_text_status == "missing_pdf"
                else []
                if approval_mode == "catch_all" or (item.title.strip() and item.authors)
                else ["title_or_authors_missing"]
            )
            consider("paper", item.paper_id, item.review_status, blockers)
    if "extractions" in requested:
        for item in session.exec(select(Paper)).all():
            blockers = (
                ["missing_pdf"]
                if approval_mode == "catch_all" and item.pdf_text_status == "missing_pdf"
                else []
                if approval_mode == "catch_all" or (item.pdf_text_status == "extracted" and item.chunk_count > 0 and not item.ocr_review_required)
                else ["extraction_or_chunks_not_ready"]
            )
            consider("extraction", item.paper_id, item.extraction_review_status, blockers)
    for requested_key, kind, model, status_attr, id_attr, blocker_fn in (
        ("authors", "author", Author, "identity_review_status", "id", author_approval_blockers),
        ("aliases", "author_alias", AuthorAlias, "review_status", "alias_id", author_alias_approval_blockers),
        ("topics", "topic", Topic, "review_status", "topic_id", lambda _s, x: topic_approval_blockers(x)),
        ("paper_topics", "paper_topic", PaperTopic, "review_status", "link_id", paper_topic_approval_blockers),
        ("author_topics", "author_topic", AuthorTopic, "review_status", "link_id", author_topic_approval_blockers),
        ("artifacts", "paper_artifact", PaperArtifact, "review_status", "artifact_id", lambda _s, x: artifact_correction_blockers(x)),
        ("recommendations", "thesis_recommendation", ThesisRecommendation, "review_status", "recommendation_id", lambda _s, x: recommendation_correction_blockers(x)),
    ):
        if requested_key in requested:
            for item in session.exec(select(model)).all():
                blockers = [] if approval_mode == "catch_all" else list(blocker_fn(session, item))
                consider(kind, str(getattr(item, id_attr)), str(getattr(item, status_attr)), blockers)
    if "answers" in requested:
        for item in session.exec(select(RAGAnswer)).all():
            blockers = (
                []
                if approval_mode == "catch_all" or (item.grounding_status != "unsupported" and item.citations_json)
                else ["answer_not_grounded_or_cited"]
            )
            consider("rag_answer", item.answer_id, item.review_status, blockers)
    snapshot = {
        "eligible": eligible,
        "blocked": blocked,
        "requested_item_types": requested,
        "approval_mode": approval_mode,
    }
    snapshot_hash = hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {**snapshot, "preview_hash": snapshot_hash, "eligible_count": len(eligible), "blocked_count": len(blocked)}


@router.post("/bulk/preview")
def preview_bulk(
    payload: BulkPreviewRequest,
    session: Annotated[Session, Depends(get_session)],
    actor: Annotated[AuthenticatedActor, Depends(require_admin)],
) -> dict[str, object]:
    preview = bulk_candidates(session, payload.item_types, approval_mode=payload.approval_mode)
    operation = BulkOperation(
        operation_id=str(uuid4()),
        operation_type="approve_all_except_missing_pdfs" if payload.approval_mode == "catch_all" else "approve_all_eligible",
        preview_hash=str(preview["preview_hash"]),
        request_json=payload.model_dump(),
        preview_json=preview,
        requested_by=actor.actor_id,
        expires_at=now() + timedelta(minutes=10),
    )
    session.add(operation)
    session.commit()
    return {"operation_id": operation.operation_id, "expires_at": operation.expires_at, **preview}


@router.post("/bulk/execute", dependencies=[Depends(serialize_admin_review_requests)])
def execute_bulk(
    payload: BulkExecuteRequest,
    session: Annotated[Session, Depends(get_session)],
    actor: Annotated[AuthenticatedActor, Depends(require_admin)],
) -> dict[str, object]:
    operation = session.get(BulkOperation, payload.operation_id)
    if operation is None or operation.requested_by != actor.actor_id:
        raise HTTPException(status_code=404, detail="Bulk preview not found")
    expires = operation.expires_at.replace(tzinfo=UTC) if operation.expires_at.tzinfo is None else operation.expires_at
    if operation.status != "previewed" or expires <= now():
        raise HTTPException(status_code=409, detail="Bulk preview expired or was already used")
    approval_mode = str(operation.request_json.get("approval_mode") or "eligible")
    fresh = bulk_candidates(
        session,
        list(operation.request_json.get("item_types") or []),
        approval_mode="catch_all" if approval_mode == "catch_all" else "eligible",
    )
    if payload.preview_hash != operation.preview_hash or fresh["preview_hash"] != operation.preview_hash:
        raise HTTPException(status_code=409, detail="Review state changed; create a fresh preview")
    approved: list[dict[str, str]] = []
    model_map = {
        "paper": (Paper, "review_status"),
        "extraction": (Paper, "extraction_review_status"),
        "author": (Author, "identity_review_status"),
        "author_alias": (AuthorAlias, "review_status"),
        "topic": (Topic, "review_status"),
        "paper_topic": (PaperTopic, "review_status"),
        "author_topic": (AuthorTopic, "review_status"),
        "paper_artifact": (PaperArtifact, "review_status"),
        "rag_answer": (RAGAnswer, "review_status"),
        "thesis_recommendation": (ThesisRecommendation, "review_status"),
    }
    audit_note = (
        "Approved by catch-all operation; missing-PDF papers were excluded."
        if approval_mode == "catch_all"
        else "Approved in bulk readiness operation."
    )
    for target in fresh["eligible"]:
        kind, item_id = str(target["item_type"]), str(target["item_id"])
        model, status_attr = model_map[kind]
        item = session.get(model, int(item_id) if model is Author else item_id)
        if item is None:
            raise HTTPException(status_code=409, detail="Review state changed; create a fresh preview")
        previous = str(getattr(item, status_attr))
        setattr(item, status_attr, "approved")
        if kind == "extraction":
            item.extraction_reviewer_notes = audit_note
            item.extraction_reviewed_at = now()
            item.extraction_reviewed_by = actor.actor_id
        elif kind == "author":
            item.identity_review_notes = audit_note
            item.identity_reviewed_at = now()
            item.identity_reviewed_by = actor.actor_id
        else:
            apply_review_metadata(item, "approved", audit_note, actor)
        if hasattr(item, "updated_at"):
            item.updated_at = now()
        event = create_review_event(
            session,
            item_type=kind,
            item_id=item_id,
            action="bulk_approved",
            previous_status=previous,
            new_status="approved",
            notes=audit_note,
            diff={status_attr: {"before": previous, "after": "approved"}, "bulk_operation_id": operation.operation_id},
            actor=actor,
        )
        session.add(item)
        session.add(event)
        session.flush()
        approved.append({"item_type": kind, "item_id": item_id})
    operation.status = "executed"
    operation.executed_at = now()
    operation.result_json = {"approved": approved, "blocked": fresh["blocked"]}
    session.add(operation)
    session.commit()
    return {"operation_id": operation.operation_id, "approved_count": len(approved), "approved": approved, "blocked": fresh["blocked"]}


def publication_candidates(session: Session) -> dict[str, Any]:
    eligible: list[dict[str, str]] = []
    blocked: list[dict[str, object]] = []
    from app.indexing.embedder import DEFAULT_INDEX_PATH, FEATURE_HASHING_PROVIDER, index_diagnostics
    from app.indexing.keyword_search import diagnostics as keyword_diagnostics

    indexes_ready = (
        keyword_diagnostics(session).get("status") == "ready"
        and index_diagnostics(session, DEFAULT_INDEX_PATH, FEATURE_HASHING_PROVIDER).get("status") == "ready"
    )
    for paper in session.exec(select(Paper).order_by(Paper.title)).all():
        if paper.publication_status == "published" and paper.public_access_level == "searchable":
            continue
        blockers: list[str] = []
        if paper.review_status != "approved":
            blockers.append("metadata_not_approved")
        if paper.extraction_review_status != "approved":
            blockers.append("extraction_not_approved")
        if paper.corpus_eligibility_status != "eligible":
            blockers.append("technical_corpus_not_eligible")
        blockers.extend(str(item) for item in content_generation_diagnostics(session, paper).get("blockers", []))
        if not indexes_ready:
            blockers.append("authoritative_indexes_not_ready")
        item: dict[str, object] = {"paper_id": paper.paper_id, "title": paper.title}
        if blockers:
            item["blockers"] = sorted(set(blockers))
            blocked.append(item)
        else:
            eligible.append({"paper_id": paper.paper_id, "title": paper.title})
    snapshot = {"eligible": eligible, "blocked": blocked}
    snapshot_hash = hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {**snapshot, "preview_hash": snapshot_hash, "eligible_count": len(eligible), "blocked_count": len(blocked)}


@router.post("/publication/preview")
def preview_publication(
    session: Annotated[Session, Depends(get_session)],
    actor: Annotated[AuthenticatedActor, Depends(require_admin)],
) -> dict[str, object]:
    preview = publication_candidates(session)
    operation = BulkOperation(
        operation_id=str(uuid4()),
        operation_type="attest_and_publish_eligible",
        preview_hash=str(preview["preview_hash"]),
        request_json={},
        preview_json=preview,
        requested_by=actor.actor_id,
        expires_at=now() + timedelta(minutes=10),
    )
    session.add(operation)
    session.commit()
    return {"operation_id": operation.operation_id, "expires_at": operation.expires_at, **preview}


@router.post("/publication/execute", dependencies=[Depends(serialize_admin_review_requests)])
def execute_publication(
    payload: PublicationExecuteRequest,
    session: Annotated[Session, Depends(get_session)],
    actor: Annotated[AuthenticatedActor, Depends(require_admin)],
) -> dict[str, object]:
    if not payload.rights_attested:
        raise HTTPException(status_code=422, detail="Explicit rights/publication attestation is required")
    require_recent_password(session, actor, payload.current_password)
    operation = session.get(BulkOperation, payload.operation_id)
    if operation is None or operation.operation_type != "attest_and_publish_eligible" or operation.requested_by != actor.actor_id:
        raise HTTPException(status_code=404, detail="Publication preview not found")
    expires = operation.expires_at.replace(tzinfo=UTC) if operation.expires_at.tzinfo is None else operation.expires_at
    fresh = publication_candidates(session)
    if operation.status != "previewed" or expires <= now() or payload.preview_hash != operation.preview_hash or fresh["preview_hash"] != operation.preview_hash:
        raise HTTPException(status_code=409, detail="Publication preview expired or state changed; create a fresh preview")
    published: list[str] = []
    for target in fresh["eligible"]:
        paper = session.get(Paper, str(target["paper_id"]))
        if paper is None:
            raise HTTPException(status_code=409, detail="Publication state changed; create a fresh preview")
        before = {
            "publication_status": paper.publication_status,
            "rights_status": paper.rights_status,
            "public_access_level": paper.public_access_level,
            "public_index_generation_id": paper.public_index_generation_id,
        }
        paper.publication_status = "published"
        paper.rights_status = "cleared"
        paper.public_access_level = "searchable"
        paper.public_index_generation_id = paper.chunk_generation_id
        paper.updated_at = now()
        after = {
            "publication_status": paper.publication_status,
            "rights_status": paper.rights_status,
            "public_access_level": paper.public_access_level,
            "public_index_generation_id": paper.public_index_generation_id,
        }
        event = create_review_event(
            session,
            item_type="paper_publication",
            item_id=paper.paper_id,
            action="bulk_publication_attested",
            previous_status=before["publication_status"],
            new_status="published",
            notes=payload.attestation_note,
            diff={key: {"before": before[key], "after": after[key]} for key in before if before[key] != after[key]},
            actor=actor,
        )
        session.add(paper)
        session.add(event)
        session.flush()
        published.append(paper.paper_id)
    operation.status = "executed"
    operation.executed_at = now()
    operation.result_json = {"published_paper_ids": published, "attestation_note": payload.attestation_note}
    session.add(operation)
    session.commit()
    return {"operation_id": operation.operation_id, "published_count": len(published), "published_paper_ids": published, "blocked": fresh["blocked"]}
