from __future__ import annotations

import hashlib
import json
import os
import socket
import tempfile
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import or_, update
from sqlmodel import Session, desc, select

from app.config import Settings, get_settings
from app.indexing.chunker import chunk_from_db
from app.indexing.embedder import (
    DEFAULT_INDEX_PATH,
    DENSE_INDEX_PATH,
    DENSE_PROVIDER,
    FEATURE_HASHING_PROVIDER,
    index_diagnostics,
    index_chunks,
)
from app.indexing.keyword_search import diagnostics as keyword_diagnostics
from app.indexing.keyword_search import rebuild_keyword_index
from app.ingestion.manual_import import upsert_papers
from app.ingestion.pdf_downloader import download_pdfs, filter_records, load_records_from_db
from app.ingestion.pdf_parser import extract_from_db
from app.ingestion.ttlab_page import discover_publications
from app.intelligence.topic_explorer import rebuild_topic_index
from app.io_utils import fsync_directory
from app.models import IngestionCandidate, IngestionRun, IngestionSyncState, Paper
from app.security import require_offline_pdf_worker

SOURCE = "ttlab"
ATOMIC_GENERATION_PROMOTION_IMPLEMENTED = False
DISCOVERY_FIELDS = (
    "title",
    "authors",
    "year",
    "publication_date_raw",
    "venue",
    "source_url",
    "post_url",
    "pdf_url",
)


def utc_now() -> datetime:
    """Return a SQLite-safe naive UTC timestamp."""

    return datetime.now(UTC).replace(tzinfo=None)


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def iso_utc(value: datetime | None) -> str | None:
    normalized = as_utc(value)
    return normalized.isoformat().replace("+00:00", "Z") if normalized else None


def resolve_project_path(settings: Settings, path: Path) -> Path:
    return path if path.is_absolute() else settings.project_root / path


def get_sync_state(session: Session) -> IngestionSyncState | None:
    return session.get(IngestionSyncState, SOURCE)


def ensure_sync_state(session: Session) -> IngestionSyncState:
    state = get_sync_state(session)
    if state is None:
        state = IngestionSyncState(source=SOURCE)
        session.add(state)
        session.commit()
        session.refresh(state)
    return state


def request_manual_sync(session: Session, requested_by: str) -> tuple[IngestionSyncState, bool]:
    state = ensure_sync_state(session)
    accepted = state.manual_requested_at is None
    if accepted:
        state.manual_requested_at = utc_now()
        state.manual_requested_by = requested_by
        state.updated_at = utc_now()
        session.add(state)
        session.commit()
        session.refresh(state)
    return state, accepted


def acquire_sync_lease(session: Session, owner: str, lock_minutes: int) -> bool:
    ensure_sync_state(session)
    now = utc_now()
    result = session.execute(
        update(IngestionSyncState)
        .where(IngestionSyncState.source == SOURCE)
        .where(
            or_(
                IngestionSyncState.lock_owner.is_(None),
                IngestionSyncState.locked_until.is_(None),
                IngestionSyncState.locked_until <= now,
            )
        )
        .values(
            lock_owner=owner,
            locked_until=now + timedelta(minutes=lock_minutes),
            updated_at=now,
        )
    )
    session.commit()
    return bool(result.rowcount == 1)


def release_sync_lease(session: Session, owner: str) -> None:
    session.rollback()
    session.execute(
        update(IngestionSyncState)
        .where(IngestionSyncState.source == SOURCE)
        .where(IngestionSyncState.lock_owner == owner)
        .values(lock_owner=None, locked_until=None, updated_at=utc_now())
    )
    session.commit()


def discovery_value(record: dict[str, Any], field: str) -> Any:
    value = record.get(field)
    if field == "authors":
        return [str(item).strip() for item in value or [] if str(item).strip()]
    if isinstance(value, str):
        return " ".join(value.split()) or None
    return value


def paper_value(paper: Paper, field: str) -> Any:
    value = getattr(paper, field)
    if field == "authors":
        return [str(item).strip() for item in value or [] if str(item).strip()]
    if isinstance(value, str):
        return " ".join(value.split()) or None
    return value


def missing_discovery_value(value: Any) -> bool:
    return value is None or value == "" or (isinstance(value, list) and not value)


def record_changed(paper: Paper, record: dict[str, Any]) -> bool:
    """Treat absent scraped fields as unknown instead of destructive changes."""

    for field in DISCOVERY_FIELDS:
        incoming = discovery_value(record, field)
        if missing_discovery_value(incoming):
            continue
        if incoming != paper_value(paper, field):
            return True
    return False


def merge_discovered_record(paper: Paper, record: dict[str, Any]) -> dict[str, Any]:
    """Preserve reviewed/local values when a scrape omits a field."""

    merged = dict(record)
    for field in DISCOVERY_FIELDS:
        incoming = discovery_value(merged, field)
        if missing_discovery_value(incoming):
            merged[field] = getattr(paper, field)
    merged["local_pdf_path"] = paper.local_pdf_path
    merged["abstract"] = paper.abstract
    merged["doi"] = paper.doi
    merged["keywords"] = list(paper.keywords)
    merged["topics"] = list(paper.topics)
    return merged


def classify_discovery(
    session: Session,
    records: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    created: list[dict[str, Any]] = []
    updated: list[dict[str, Any]] = []
    unchanged = 0
    for record in records:
        paper_id = str(record.get("paper_id") or "")
        if not paper_id:
            continue
        existing = session.get(Paper, paper_id)
        if existing is None:
            created.append(record)
        elif record_changed(existing, record):
            updated.append(merge_discovered_record(existing, record))
        else:
            unchanged += 1
    return created, updated, unchanged


def atomic_write_seed(records: list[dict[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(records, indent=2, ensure_ascii=False) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=output_path.parent,
        prefix=f".{output_path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, output_path)
    fsync_directory(output_path.parent)


def lease_owner() -> str:
    token = uuid.uuid4().hex[:12]
    return f"{socket.gethostname()}:{os.getpid()}:{token}"


def should_rebuild_dense(settings: Settings) -> bool:
    if settings.sync_dense_index_policy == "always":
        return True
    if settings.sync_dense_index_policy == "never":
        return False
    return DENSE_INDEX_PATH.exists()


def retry_candidate_ids(session: Session, records: list[dict[str, Any]]) -> list[str]:
    """Return discovered papers whose interrupted processing can make progress."""

    candidates: list[str] = []
    for record in records:
        paper_id = str(record.get("paper_id") or "")
        paper = session.get(Paper, paper_id) if paper_id else None
        if paper is None:
            continue
        needs_download = bool(paper.pdf_url and not paper.local_pdf_path)
        needs_extraction = bool(
            paper.local_pdf_path and paper.pdf_text_status not in {"extracted", "no_text"}
        )
        needs_chunks = paper.pdf_text_status == "extracted" and paper.chunk_count == 0
        if needs_download or needs_extraction or needs_chunks:
            candidates.append(paper_id)
    return candidates


def indexes_require_rebuild(session: Session, *, new_chunks: int) -> bool:
    if new_chunks > 0:
        return True
    keyword_state = keyword_diagnostics(session)
    feature_state = index_diagnostics(
        session,
        index_path=DEFAULT_INDEX_PATH,
        provider_name=FEATURE_HASHING_PROVIDER,
    )
    return keyword_state["status"] != "ready" or feature_state["status"] != "ready"


def execute_ttlab_sync(
    session: Session,
    *,
    settings: Settings | None = None,
    trigger: str = "scheduled",
    requested_by: str | None = None,
    discoverer: Callable[[str, int, bool], list[dict[str, Any]]] = discover_publications,
) -> dict[str, Any]:
    settings = settings or get_settings()
    if not ATOMIC_GENERATION_PROMOTION_IMPLEMENTED:
        return {
            "run_id": None,
            "source": SOURCE,
            "trigger": trigger,
            "status": "disabled",
            "reason": "atomic_generation_promotion_not_implemented",
            "authoritative_rebuild_path": "manual_isolated_reproduce_all",
        }
    if (
        settings.sync_execution_mode != "offline_single_writer"
        or settings.security_mode == "production"
        or settings.service_role != "offline_worker"
    ):
        return {
            "run_id": None,
            "source": SOURCE,
            "trigger": trigger,
            "status": "disabled",
            "reason": "ingestion_requires_explicit_offline_single_writer_worker_mode",
        }
    require_offline_pdf_worker(settings, "TTLAB ingestion synchronization")
    owner = lease_owner()
    run_id = str(uuid.uuid4())
    if not acquire_sync_lease(session, owner, settings.sync_lock_minutes):
        return {
            "run_id": None,
            "source": SOURCE,
            "trigger": trigger,
            "status": "skipped",
            "reason": "another_sync_holds_the_lease",
        }

    run = IngestionRun(
        run_id=run_id,
        source=SOURCE,
        trigger=trigger,
        requested_by=requested_by,
        status="running",
    )
    try:
        state = ensure_sync_state(session)
        if trigger == "manual":
            requested_by = requested_by or state.manual_requested_by
            run.requested_by = requested_by
            state.manual_requested_at = None
            state.manual_requested_by = None
        state.last_run_id = run_id
        state.updated_at = utc_now()
        session.add(run)
        session.add(state)
        session.commit()

        records = discoverer(
            settings.ttlab_publications_url,
            settings.sync_max_pages,
            True,
        )
        if not records:
            raise RuntimeError("TTLAB discovery returned no publications; the existing corpus was left unchanged")

        seed_path = resolve_project_path(settings, settings.sync_seed_path)
        atomic_write_seed(records, seed_path)
        created_records, updated_records, unchanged = classify_discovery(session, records)
        changed_records = created_records + updated_records
        import_summary = (
            upsert_papers(session, changed_records)
            if changed_records
            else {"created": 0, "updated": 0, "skipped": 0, "missing_pdf": 0, "authors": 0}
        )
        changed_ids = [str(record["paper_id"]) for record in changed_records]
        processing_ids = list(dict.fromkeys(changed_ids + retry_candidate_ids(session, records)))

        if settings.sync_download_pdfs and processing_ids:
            candidates = filter_records(
                load_records_from_db(session),
                paper_ids=processing_ids,
                only_missing=True,
                output_dir=settings.project_root / "data" / "pdfs",
            )
            download_summary: dict[str, Any] = (
                download_pdfs(
                    candidates,
                    settings.project_root / "data" / "pdfs",
                    download=True,
                    session=session,
                    settings_override=settings,
                )
                if candidates
                else {"skipped": "no missing PDFs among processing candidates"}
            )
        else:
            download_summary = {
                "skipped": "disabled" if not settings.sync_download_pdfs else "no processing candidates"
            }

        extraction_summary = (
            extract_from_db(
                session,
                paper_ids=processing_ids,
                output_dir=settings.project_root / "data" / "extracted_text",
                settings_override=settings,
            )
            if processing_ids
            else {"attempted": 0, "extracted": 0, "skipped_existing": 0}
        )
        chunk_summary = (
            chunk_from_db(
                session,
                paper_ids=processing_ids,
                output_dir=settings.project_root / "data" / "chunks",
            )
            if processing_ids
            else {"attempted": 0, "chunked": 0, "skipped_existing": 0}
        )

        index_summary: dict[str, Any] = {"rebuilt": False}
        new_chunks = int(chunk_summary.get("chunked") or 0)
        if indexes_require_rebuild(session, new_chunks=new_chunks):
            index_summary = {
                "rebuilt": True,
                "keyword": rebuild_keyword_index(session),
                "feature_hashing": index_chunks(
                    session,
                    provider_name=FEATURE_HASHING_PROVIDER,
                    index_role="authoritative",
                ),
            }
            if should_rebuild_dense(settings):
                index_summary["dense"] = index_chunks(
                    session,
                    provider_name=DENSE_PROVIDER,
                    index_role="authoritative",
                    allow_model_download=settings.sync_allow_dense_model_download,
                    device=settings.dense_embedding_device,
                )
            else:
                index_summary["dense"] = {"skipped": settings.sync_dense_index_policy}

        topic_summary = (
            rebuild_topic_index(session)
            if changed_records
            else {"skipped": "no new or changed records"}
        )
        summary = {
            "seed_sha256": hashlib.sha256(seed_path.read_bytes()).hexdigest(),
            "discovery": {
                "records": len(records),
                "created": len(created_records),
                "updated": len(updated_records),
                "unchanged": unchanged,
                "processing_candidates": len(processing_ids),
            },
            "import": import_summary,
            "download": download_summary,
            "extract": extraction_summary,
            "chunk": chunk_summary,
            "indexes": index_summary,
            "topics": topic_summary,
        }

        finished_at = utc_now()
        run.status = "succeeded"
        run.discovered_count = len(records)
        run.created_count = int(import_summary.get("created") or 0)
        run.updated_count = int(import_summary.get("updated") or 0)
        run.unchanged_count = unchanged
        run.downloaded_count = int(download_summary.get("downloaded") or 0)
        run.extracted_count = int(extraction_summary.get("extracted") or 0)
        run.chunked_count = int(chunk_summary.get("chunked") or 0)
        run.summary_json = summary
        run.finished_at = finished_at
        state = ensure_sync_state(session)
        state.last_success_at = finished_at
        state.updated_at = finished_at
        session.add(run)
        session.add(state)
        session.commit()
        return serialize_ingestion_run(run)
    except Exception as exc:
        session.rollback()
        error = f"{type(exc).__name__}: {str(exc)[:500]}"
        failed_run = session.get(IngestionRun, run_id)
        if failed_run is None:
            failed_run = run
            session.add(failed_run)
        failed_run.status = "failed"
        failed_run.error_message = error
        failed_run.finished_at = utc_now()
        state = ensure_sync_state(session)
        state.last_run_id = run_id
        state.last_failure_at = failed_run.finished_at
        state.updated_at = failed_run.finished_at
        session.add(failed_run)
        session.add(state)
        session.commit()
        return serialize_ingestion_run(failed_run)
    finally:
        release_sync_lease(session, owner)


def execute_ttlab_discovery_check(
    session: Session,
    *,
    settings: Settings | None = None,
    trigger: str = "manual",
    requested_by: str | None = None,
    discoverer: Callable[[str, int, bool], list[dict[str, Any]]] = discover_publications,
) -> dict[str, Any]:
    """Discover and stage candidates without mutating the active paper corpus."""

    settings = settings or get_settings()
    if settings.sync_execution_mode != "offline_single_writer" or settings.service_role != "offline_worker":
        return {"run_id": None, "source": SOURCE, "trigger": trigger, "status": "disabled", "reason": "discovery_requires_explicit_offline_single_writer_worker_mode"}
    require_offline_pdf_worker(settings, "TTLAB publication discovery")
    owner = lease_owner()
    run_id = str(uuid.uuid4())
    if not acquire_sync_lease(session, owner, settings.sync_lock_minutes):
        return {"run_id": None, "source": SOURCE, "trigger": trigger, "status": "skipped", "reason": "another_sync_holds_the_lease"}
    run = IngestionRun(run_id=run_id, source=SOURCE, trigger=f"{trigger}_discovery", requested_by=requested_by, status="running")
    try:
        state = ensure_sync_state(session)
        if trigger == "manual":
            run.requested_by = requested_by or state.manual_requested_by
            state.manual_requested_at = None
            state.manual_requested_by = None
        state.last_run_id = run_id
        state.updated_at = utc_now()
        session.add(run)
        session.add(state)
        session.commit()
        records = discoverer(settings.ttlab_publications_url, settings.sync_max_pages, True)
        if not records:
            raise RuntimeError("TTLAB discovery returned no publications; no candidates were changed")
        atomic_write_seed(records, resolve_project_path(settings, settings.sync_seed_path))
        created, updated, unchanged = classify_discovery(session, records)
        statuses = {str(item.get("paper_id")): "new" for item in created}
        statuses.update({str(item.get("paper_id")): "changed" for item in updated})
        staged = 0
        for record in created + updated:
            source_key = str(record.get("paper_id") or record.get("post_url") or record.get("pdf_url") or record.get("title") or "").strip()
            if not source_key:
                continue
            candidate_id = hashlib.sha256(source_key.encode("utf-8")).hexdigest()[:32]
            candidate = session.get(IngestionCandidate, candidate_id) or IngestionCandidate(
                candidate_id=candidate_id,
                source_key=source_key,
                title=str(record.get("title") or "Untitled publication"),
                discovered_run_id=run_id,
            )
            candidate.title = str(record.get("title") or candidate.title)
            candidate.source_url = str(record.get("source_url") or record.get("post_url") or "") or None
            candidate.pdf_url = str(record.get("pdf_url") or "") or None
            candidate.metadata_json = record
            candidate.comparison_status = statuses.get(str(record.get("paper_id")), "changed")
            candidate.import_status = "pending"
            candidate.discovered_run_id = run_id
            candidate.updated_at = utc_now()
            session.add(candidate)
            staged += 1
        run.discovered_count = len(records)
        run.created_count = len(created)
        run.updated_count = len(updated)
        run.unchanged_count = unchanged
        run.status = "succeeded"
        run.summary_json = {"candidate_count": staged, "active_corpus_changed": False, "promotion_available": ATOMIC_GENERATION_PROMOTION_IMPLEMENTED}
        run.finished_at = utc_now()
        state.last_success_at = utc_now()
        state.updated_at = utc_now()
        session.add(run)
        session.add(state)
        session.commit()
        return {"run_id": run_id, "source": SOURCE, "trigger": trigger, "status": "succeeded", "discovered": len(records), "candidates_staged": staged, "unchanged": unchanged, "active_corpus_changed": False}
    except Exception as exc:
        session.rollback()
        failed = session.get(IngestionRun, run_id) or run
        failed.status = "failed"
        failed.error_message = f"{type(exc).__name__}: {exc}"
        failed.finished_at = utc_now()
        state = ensure_sync_state(session)
        state.last_failure_at = utc_now()
        state.updated_at = utc_now()
        session.add(failed)
        session.add(state)
        session.commit()
        return {"run_id": run_id, "source": SOURCE, "trigger": trigger, "status": "failed", "error": failed.error_message, "active_corpus_changed": False}
    finally:
        release_sync_lease(session, owner)


def serialize_ingestion_run(run: IngestionRun | None) -> dict[str, Any] | None:
    if run is None:
        return None
    return {
        "run_id": run.run_id,
        "source": run.source,
        "trigger": run.trigger,
        "requested_by": run.requested_by,
        "status": run.status,
        "discovered_count": run.discovered_count,
        "created_count": run.created_count,
        "updated_count": run.updated_count,
        "unchanged_count": run.unchanged_count,
        "downloaded_count": run.downloaded_count,
        "extracted_count": run.extracted_count,
        "chunked_count": run.chunked_count,
        "error_message": run.error_message,
        "summary": dict(run.summary_json or {}),
        "started_at": iso_utc(run.started_at),
        "finished_at": iso_utc(run.finished_at),
    }


def ingestion_sync_status(session: Session, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    state = get_sync_state(session)
    recent_runs = list(
        session.exec(
            select(IngestionRun)
            .where(IngestionRun.source == SOURCE)
            .order_by(desc(IngestionRun.started_at))
            .limit(10)
        ).all()
    )
    now = datetime.now(UTC)
    locked_until = as_utc(state.locked_until) if state else None
    worker_role_active = bool(
        settings.service_role == "offline_worker"
        and settings.sync_execution_mode == "offline_single_writer"
    )
    return {
        "source": SOURCE,
        # This status is read from the API process, while discovery must run in
        # a separate process with different role settings. `enabled` therefore
        # describes the shared queue/schedule switch, not the current process.
        "enabled": settings.sync_enabled,
        "configured_enabled": settings.sync_enabled,
        "disabled_reason": None if settings.sync_enabled else "discovery_checks_disabled",
        "discovery_check_available": settings.sync_enabled,
        "current_process_is_discovery_worker": worker_role_active,
        "candidate_import_available": ATOMIC_GENERATION_PROMOTION_IMPLEMENTED,
        "atomic_generation_promotion_implemented": ATOMIC_GENERATION_PROMOTION_IMPLEMENTED,
        "execution_mode": settings.sync_execution_mode,
        "service_role": settings.service_role,
        "api_or_production_mode_blocked": settings.service_role == "api",
        "single_writer_enforced": True,
        "network_and_process_isolation_implemented_by_application": False,
        "external_worker_controls_required": True,
        "discovery_output_path": str(resolve_project_path(settings, settings.sync_seed_path)),
        "schedule": settings.sync_cron,
        "timezone": settings.sync_timezone,
        "run_on_startup": settings.sync_run_on_startup,
        "worker_poll_seconds": settings.sync_worker_poll_seconds,
        "download_pdfs": settings.sync_download_pdfs,
        "dense_index_policy": settings.sync_dense_index_policy,
        "running": bool(state and state.lock_owner and locked_until and locked_until > now),
        "manual_request_pending": bool(state and state.manual_requested_at),
        "manual_requested_at": iso_utc(state.manual_requested_at) if state else None,
        "manual_requested_by": state.manual_requested_by if state else None,
        "last_success_at": iso_utc(state.last_success_at) if state else None,
        "last_failure_at": iso_utc(state.last_failure_at) if state else None,
        "next_scheduled_at": iso_utc(state.next_scheduled_at) if state else None,
        "last_run": serialize_ingestion_run(recent_runs[0] if recent_runs else None),
        "recent_runs": [serialize_ingestion_run(run) for run in recent_runs],
    }
