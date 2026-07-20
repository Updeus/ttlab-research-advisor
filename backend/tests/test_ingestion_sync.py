from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.config import Settings
from app.ingestion import sync as sync_module
from app.ingestion.sync import (
    acquire_sync_lease,
    execute_ttlab_sync,
    get_sync_state,
    release_sync_lease,
    request_manual_sync,
)
from app.ingestion.sync_worker import next_scheduled_run, scheduled_sync_due
from app.models import IngestionRun, Paper


def build_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


def discovered_record() -> dict[str, object]:
    return {
        "paper_id": "scheduled-paper",
        "title": "Scheduled Research Paper",
        "authors": ["Asha Singh"],
        "year": 2026,
        "publication_date_raw": "July 2026",
        "venue": "TTLAB Journal",
        "source_url": "https://example.org/source",
        "post_url": "https://lab.tt/index.php/2026/scheduled-paper/",
        "pdf_url": "https://lab.tt/wp-content/paper.pdf",
        "topics": [],
        "ingestion_status": "discovered",
        "pdf_text_status": "not_extracted",
        "review_status": "needs_review",
        "raw_scraped": {"paragraphs": ["Scheduled Research Paper"]},
    }


def test_daily_schedule_waits_until_due_and_runs_at_most_once_per_boundary() -> None:
    engine = build_engine()
    settings = Settings(sync_enabled=True, sync_cron="0 2 * * *", sync_timezone="UTC")
    with Session(engine) as session:
        assert not scheduled_sync_due(settings, session, datetime(2026, 7, 20, 1, 0, tzinfo=UTC))
        assert scheduled_sync_due(settings, session, datetime(2026, 7, 20, 3, 0, tzinfo=UTC))
        state, _accepted = request_manual_sync(session, "admin")
        state.manual_requested_at = None
        state.manual_requested_by = None
        state.last_failure_at = datetime(2026, 7, 20, 2, 30)
        session.add(state)
        session.commit()
        assert not scheduled_sync_due(settings, session, datetime(2026, 7, 20, 3, 0, tzinfo=UTC))
        assert next_scheduled_run(settings, datetime(2026, 7, 20, 3, 0, tzinfo=UTC)) == datetime(
            2026, 7, 21, 2, 0, tzinfo=UTC
        )


def test_database_lease_prevents_overlapping_workers_and_expires_cleanly() -> None:
    engine = build_engine()
    with Session(engine) as session:
        assert acquire_sync_lease(session, "worker-one", 30)
        assert not acquire_sync_lease(session, "worker-two", 30)
        release_sync_lease(session, "worker-one")
        assert acquire_sync_lease(session, "worker-two", 30)
        release_sync_lease(session, "worker-two")
        state = get_sync_state(session)
        assert state is not None
        assert state.lock_owner is None
        assert state.locked_until is None


def test_manual_request_is_idempotent_until_worker_claims_it() -> None:
    engine = build_engine()
    with Session(engine) as session:
        state, accepted = request_manual_sync(session, "admin-one")
        assert accepted
        assert state.manual_requested_by == "admin-one"
        duplicate, accepted_again = request_manual_sync(session, "admin-two")
        assert not accepted_again
        assert duplicate.manual_requested_by == "admin-one"


def test_sync_imports_only_changes_and_rebuilds_indexes_only_for_new_chunks(tmp_path, monkeypatch) -> None:
    engine = build_engine()
    settings = Settings(
        sync_seed_path=tmp_path / "ttlab-discovered.json",
        sync_dense_index_policy="never",
        sync_download_pdfs=True,
    )
    calls = {"download": 0, "extract": 0, "chunk": 0, "keyword": 0, "index": 0, "topics": 0}

    def fake_download(*_args, **_kwargs):
        calls["download"] += 1
        session = _kwargs["session"]
        for candidate in _args[0]:
            paper = session.get(Paper, candidate.paper_id)
            paper.local_pdf_path = str(tmp_path / f"{candidate.paper_id}.pdf")
            paper.pdf_text_status = "downloaded"
            session.add(paper)
        session.commit()
        return {"downloaded": 1, "failed": 0}

    def fake_extract(*_args, **_kwargs):
        calls["extract"] += 1
        session = _args[0]
        for paper_id in _kwargs["paper_ids"]:
            paper = session.get(Paper, paper_id)
            paper.pdf_text_status = "extracted"
            session.add(paper)
        session.commit()
        return {"attempted": 1, "extracted": 1, "skipped_existing": 0}

    def fake_chunk(*_args, **_kwargs):
        calls["chunk"] += 1
        session = _args[0]
        for paper_id in _kwargs["paper_ids"]:
            paper = session.get(Paper, paper_id)
            paper.chunk_count = 1
            session.add(paper)
        session.commit()
        return {"attempted": 1, "chunked": 1, "skipped_existing": 0}

    def fake_keyword(*_args, **_kwargs):
        calls["keyword"] += 1
        return {"indexed_chunks": 1, "completeness_status": "complete"}

    def fake_index(*_args, **_kwargs):
        calls["index"] += 1
        return {"indexed_chunks": 1, "index_status": "ready"}

    def fake_topics(*_args, **_kwargs):
        calls["topics"] += 1
        return {"paper_topic_links": 1}

    monkeypatch.setattr(sync_module, "download_pdfs", fake_download)
    monkeypatch.setattr(sync_module, "extract_from_db", fake_extract)
    monkeypatch.setattr(sync_module, "chunk_from_db", fake_chunk)
    monkeypatch.setattr(sync_module, "rebuild_keyword_index", fake_keyword)
    monkeypatch.setattr(sync_module, "index_chunks", fake_index)
    monkeypatch.setattr(sync_module, "rebuild_topic_index", fake_topics)
    monkeypatch.setattr(sync_module, "indexes_require_rebuild", lambda _session, *, new_chunks: new_chunks > 0)

    discoverer = lambda _url, _pages, _check: [discovered_record()]
    with Session(engine) as session:
        first = execute_ttlab_sync(session, settings=settings, trigger="scheduled", discoverer=discoverer)
        second = execute_ttlab_sync(session, settings=settings, trigger="scheduled", discoverer=discoverer)
        paper = session.get(Paper, "scheduled-paper")
        runs = list(session.exec(select(IngestionRun)).all())
        state = get_sync_state(session)

    assert first["status"] == "succeeded"
    assert first["created_count"] == 1
    assert second["status"] == "succeeded"
    assert second["created_count"] == 0
    assert second["unchanged_count"] == 1
    assert paper is not None and paper.review_status == "needs_review"
    assert len(runs) == 2
    assert calls == {"download": 1, "extract": 1, "chunk": 1, "keyword": 1, "index": 1, "topics": 1}
    assert settings.sync_seed_path.read_text(encoding="utf-8").endswith("\n")
    assert state is not None and state.lock_owner is None


def test_unchanged_failed_download_is_retried(tmp_path, monkeypatch) -> None:
    engine = build_engine()
    settings = Settings(sync_seed_path=tmp_path / "retry.json", sync_dense_index_policy="never")
    record = discovered_record()
    retry_calls: list[list[str]] = []

    monkeypatch.setattr(
        sync_module,
        "download_pdfs",
        lambda candidates, *_args, **_kwargs: retry_calls.append([item.paper_id for item in candidates])
        or {"downloaded": 0, "failed": 1},
    )
    monkeypatch.setattr(sync_module, "extract_from_db", lambda *_args, **_kwargs: {"attempted": 0, "extracted": 0})
    monkeypatch.setattr(sync_module, "chunk_from_db", lambda *_args, **_kwargs: {"attempted": 0, "chunked": 0})
    monkeypatch.setattr(sync_module, "indexes_require_rebuild", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(sync_module, "rebuild_topic_index", lambda *_args, **_kwargs: {"skipped": True})

    with Session(engine) as session:
        upsert = sync_module.upsert_papers(session, [record])
        assert upsert["created"] == 1
        paper = session.get(Paper, "scheduled-paper")
        paper.pdf_text_status = "download_failed"
        session.add(paper)
        session.commit()
        result = execute_ttlab_sync(
            session,
            settings=settings,
            discoverer=lambda _url, _pages, _check: [record],
        )

    assert result["status"] == "succeeded"
    assert result["unchanged_count"] == 1
    assert retry_calls == [["scheduled-paper"]]


def test_empty_discovery_fails_without_replacing_existing_corpus(tmp_path) -> None:
    engine = build_engine()
    settings = Settings(sync_seed_path=tmp_path / "empty.json")
    with Session(engine) as session:
        session.add(Paper(paper_id="existing", title="Existing paper"))
        session.commit()
        result = execute_ttlab_sync(
            session,
            settings=settings,
            trigger="scheduled",
            discoverer=lambda _url, _pages, _check: [],
        )
        state = get_sync_state(session)
        existing = session.get(Paper, "existing")

    assert result["status"] == "failed"
    assert "returned no publications" in str(result["error_message"])
    assert existing is not None
    assert not settings.sync_seed_path.exists()
    assert state is not None and state.lock_owner is None
