from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.indexing import embedder
from app.indexing.embedder import (
    DENSE_PROVIDER,
    DENSE_DIMENSIONS,
    DENSE_MODEL_NAME,
    DENSE_MODEL_REVISION,
    FEATURE_HASHING_PROVIDER,
    HashingEmbeddingProvider,
    IndexIntegrityError,
    SentenceTransformerEmbeddingProvider,
    index_chunks,
    load_validated_index,
    manifest_path_for,
    validate_index_manifest,
    validate_present_authoritative_indexes,
)
from app.indexing.keyword_search import (
    KeywordIndexIntegrityError,
    diagnostics as keyword_diagnostics,
    rebuild_keyword_index,
    search_keyword,
)
from app.models import Chunk, Paper


def build_session(chunk_count: int = 3) -> tuple[Session, object]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    session = Session(engine)
    paper_count = max(1, (chunk_count + 99) // 100)
    for paper_index in range(paper_count):
        session.add(
            Paper(
                paper_id=f"paper-{paper_index:03d}",
                title=f"Paper {paper_index}",
                corpus_eligibility_status="eligible",
                pdf_text_status="extracted",
            )
        )
    for index in range(chunk_count):
        paper_id = f"paper-{index // 100:03d}"
        session.add(
            Chunk(
                chunk_id=f"chunk-{index:04d}",
                paper_id=paper_id,
                chunk_index=index % 100,
                text=f"Evidence text for chunk {index}",
                source_hash=f"hash-{index:04d}",
                embedding_status="indexed:hashing" if index % 3 == 0 else "not_indexed",
            )
        )
    session.commit()
    return session, engine


def small_hashing_provider() -> HashingEmbeddingProvider:
    return HashingEmbeddingProvider(dimensions=8)


def test_complete_manifest_records_required_provenance_and_repairs_statuses(tmp_path: Path) -> None:
    session, _engine = build_session(5)
    index_path = tmp_path / "feature.json"
    try:
        result = index_chunks(session, output_path=index_path, provider_override=small_hashing_provider())
        report = validate_index_manifest(session, index_path=index_path, provider_name=FEATURE_HASHING_PROVIDER)
        statuses = {chunk.embedding_status for chunk in session.exec(select(Chunk)).all()}
    finally:
        session.close()

    assert result["indexed_chunks"] == result["eligible_chunks"] == 5
    assert result["completeness_status"] == "complete"
    assert report["valid"] is True
    assert report["corpus_snapshot_id"].startswith("corpus-")
    assert len(report["corpus_snapshot_hash"]) == 64
    assert len(report["index_sha256"]) == 64
    assert len(report["configuration_hash"]) == 64
    assert statuses == {"indexed:feature_hashing"}


def test_sequential_authoritative_providers_keep_database_statuses_synchronized(tmp_path: Path) -> None:
    """Regression for the full reproducer's feature-hashing then dense promotion."""

    session, _engine = build_session(5)
    feature_path = tmp_path / "feature.json"
    dense_path = tmp_path / "dense.json"
    dense_test_provider = HashingEmbeddingProvider(
        dimensions=8,
        name=DENSE_PROVIDER,
        model_name="deterministic-test-dense",
        model_revision="test-1",
    )
    try:
        index_chunks(
            session,
            provider_name=FEATURE_HASHING_PROVIDER,
            output_path=feature_path,
            provider_override=small_hashing_provider(),
        )
        index_chunks(
            session,
            provider_name=DENSE_PROVIDER,
            output_path=dense_path,
            provider_override=dense_test_provider,
        )
        feature_report = validate_index_manifest(
            session,
            index_path=feature_path,
            provider_name=FEATURE_HASHING_PROVIDER,
        )
        dense_report = validate_index_manifest(
            session,
            index_path=dense_path,
            provider_name=DENSE_PROVIDER,
        )
        statuses = {chunk.embedding_status for chunk in session.exec(select(Chunk)).all()}
    finally:
        session.close()

    assert feature_report["valid"] is True
    assert dense_report["valid"] is True
    assert statuses == {"indexed:dense,feature_hashing"}


def test_25_of_756_partial_build_is_isolated_and_cannot_claim_readiness(tmp_path: Path) -> None:
    session, _engine = build_session(756)
    authoritative_path = tmp_path / "authoritative.json"
    demo_path = tmp_path / "demo" / "feature.json"
    try:
        index_chunks(session, output_path=authoritative_path, provider_override=small_hashing_provider())
        authoritative_before = authoritative_path.read_bytes()
        authoritative_manifest_before = manifest_path_for(authoritative_path).read_bytes()
        with pytest.raises(ValueError, match="bounded rebuild"):
            index_chunks(
                session,
                limit=25,
                output_path=authoritative_path,
                provider_override=small_hashing_provider(),
            )
        result = index_chunks(
            session,
            limit=25,
            output_path=demo_path,
            allow_partial=True,
            update_db_status=False,
            index_role="bounded_demo",
            provider_override=small_hashing_provider(),
        )
        report = validate_index_manifest(
            None,
            index_path=demo_path,
            provider_name=FEATURE_HASHING_PROVIDER,
            require_complete=False,
            check_db_status=False,
        )
        strict = validate_index_manifest(
            None,
            index_path=demo_path,
            provider_name=FEATURE_HASHING_PROVIDER,
            require_complete=True,
            check_db_status=False,
        )
    finally:
        session.close()

    assert authoritative_path.read_bytes() == authoritative_before
    assert manifest_path_for(authoritative_path).read_bytes() == authoritative_manifest_before
    assert result["indexed_chunks"] == 25
    assert result["eligible_chunks"] == 756
    assert result["completeness_status"] == "partial"
    assert report["valid"] is True
    assert strict["valid"] is False
    assert any("partial" in error for error in strict["errors"])


def test_stale_database_status_fails_manifest_validation(tmp_path: Path) -> None:
    session, _engine = build_session(4)
    index_path = tmp_path / "feature.json"
    try:
        index_chunks(session, output_path=index_path, provider_override=small_hashing_provider())
        chunk = session.get(Chunk, "chunk-0002")
        assert chunk is not None
        chunk.embedding_status = "not_indexed"
        session.add(chunk)
        session.commit()
        report = validate_index_manifest(session, index_path=index_path, provider_name=FEATURE_HASHING_PROVIDER)
    finally:
        session.close()

    assert report["valid"] is False
    assert any("statuses disagree" in error for error in report["errors"])


def test_corpus_source_hash_change_fails_loudly(tmp_path: Path) -> None:
    session, _engine = build_session(3)
    index_path = tmp_path / "feature.json"
    try:
        index_chunks(session, output_path=index_path, provider_override=small_hashing_provider())
        chunk = session.get(Chunk, "chunk-0001")
        assert chunk is not None
        chunk.source_hash = "changed-source-hash"
        session.add(chunk)
        session.commit()
        report = validate_index_manifest(session, index_path=index_path, provider_name=FEATURE_HASHING_PROVIDER)
        with pytest.raises(IndexIntegrityError, match="snapshot"):
            load_validated_index(session, index_path=index_path, provider_name=FEATURE_HASHING_PROVIDER)
    finally:
        session.close()

    assert report["valid"] is False
    assert any("snapshot" in error for error in report["errors"])


def test_atomic_pair_write_restores_previous_files_on_second_write_failure(monkeypatch, tmp_path: Path) -> None:
    index_path = tmp_path / "feature.json"
    manifest_path = manifest_path_for(index_path)
    index_path.write_bytes(b"old-index")
    manifest_path.write_bytes(b"old-manifest")
    real_atomic_write = embedder.atomic_write_bytes
    calls = 0

    def fail_second_write(path: Path, content: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated manifest write failure")
        real_atomic_write(path, content)

    monkeypatch.setattr(embedder, "atomic_write_bytes", fail_second_write)

    with pytest.raises(OSError, match="simulated"):
        embedder.write_index_and_manifest(index_path, b"new-index", {"new": "manifest"})

    assert index_path.read_bytes() == b"old-index"
    assert manifest_path.read_bytes() == b"old-manifest"


def test_excluded_paper_chunks_are_invalidated_and_not_indexed(tmp_path: Path) -> None:
    session, _engine = build_session(3)
    index_path = tmp_path / "feature.json"
    try:
        excluded = session.get(Paper, "paper-000")
        assert excluded is not None
        excluded.corpus_eligibility_status = "excluded_pdf_metadata_mismatch"
        session.add(excluded)
        # Add a separate eligible paper so strict eligibility is active.
        session.add(Paper(paper_id="eligible-paper", title="Eligible", corpus_eligibility_status="eligible"))
        session.add(
            Chunk(
                chunk_id="eligible-chunk",
                paper_id="eligible-paper",
                chunk_index=0,
                text="Eligible evidence",
                source_hash="eligible-hash",
            )
        )
        session.commit()
        result = index_chunks(session, output_path=index_path, provider_override=small_hashing_provider())
        excluded_statuses = {
            chunk.embedding_status
            for chunk in session.exec(select(Chunk).where(Chunk.paper_id == "paper-000")).all()
        }
    finally:
        session.close()

    assert result["eligible_chunks"] == 1
    assert excluded_statuses == {"not_indexed"}


def test_dense_configuration_is_immutable_and_384_dimensional() -> None:
    assert DENSE_MODEL_NAME == "sentence-transformers/all-MiniLM-L6-v2"
    assert DENSE_MODEL_REVISION == "826711e54e001c83835913827a843d8dd0a1def9"
    assert DENSE_DIMENSIONS == 384


def test_startup_gate_allows_missing_optional_indexes_but_rejects_present_corruption(
    monkeypatch, tmp_path: Path
) -> None:
    session, _engine = build_session(2)
    feature_path = tmp_path / "feature.json"
    dense_path = tmp_path / "dense.json"
    monkeypatch.setattr(embedder, "DEFAULT_INDEX_PATH", feature_path)
    monkeypatch.setattr(embedder, "DENSE_INDEX_PATH", dense_path)
    try:
        reports = validate_present_authoritative_indexes(session)
        assert reports[FEATURE_HASHING_PROVIDER]["status"] == "missing"
        feature_path.parent.mkdir(parents=True, exist_ok=True)
        feature_path.write_text("{}", encoding="utf-8")
        with pytest.raises(IndexIntegrityError, match="manifest is missing"):
            validate_present_authoritative_indexes(session)
        feature_path.unlink()
        index_chunks(session, output_path=feature_path, provider_override=small_hashing_provider())
        feature_path.write_bytes(feature_path.read_bytes() + b"corruption")
        with pytest.raises(IndexIntegrityError, match="startup validation failed"):
            validate_present_authoritative_indexes(session)
    finally:
        session.close()


def test_dense_token_windows_cover_the_complete_chunk_with_overlap() -> None:
    class FakeTokenizer:
        def encode(self, text: str, **_kwargs):
            return [int(token) for token in text.split()]

        def decode(self, token_ids, **_kwargs):
            return " ".join(str(token) for token in token_ids)

    provider = SentenceTransformerEmbeddingProvider.__new__(SentenceTransformerEmbeddingProvider)
    provider._tokenizer = FakeTokenizer()
    provider.window_tokens = 4
    provider.window_overlap_tokens = 1

    windows = provider._windows("0 1 2 3 4 5 6 7 8 9")

    assert windows == ["0 1 2 3", "3 4 5 6", "6 7 8 9"]
    assert {int(token) for window in windows for token in window.split()} == set(range(10))


def test_keyword_index_covers_only_eligible_chunks_and_flags_corpus_change() -> None:
    session, _engine = build_session(3)
    try:
        excluded = session.get(Paper, "paper-000")
        assert excluded is not None
        excluded.corpus_eligibility_status = "excluded_pdf_metadata_mismatch"
        session.add(excluded)
        session.add(Paper(paper_id="eligible-paper", title="Eligible", corpus_eligibility_status="eligible"))
        session.add(
            Chunk(
                chunk_id="eligible-chunk",
                paper_id="eligible-paper",
                chunk_index=0,
                text="Unique eligible retrieval evidence",
                source_hash="eligible-hash",
            )
        )
        session.commit()
        result = rebuild_keyword_index(session)
        health = keyword_diagnostics(session)
        assert result["indexed_chunks"] == result["eligible_chunks"] == 1
        assert health["status"] == "ready"
        assert health["coverage_ratio"] == 1.0
        assert search_keyword(session, "unique eligible", top_k=3)[0]["chunk_id"] == "eligible-chunk"

        session.add(
            Chunk(
                chunk_id="eligible-chunk-new",
                paper_id="eligible-paper",
                chunk_index=1,
                text="New corpus evidence",
                source_hash="eligible-hash-new",
            )
        )
        session.commit()
        stale = keyword_diagnostics(session)
        assert stale["status"] == "invalid"
        with pytest.raises(KeywordIndexIntegrityError, match="snapshot"):
            search_keyword(session, "evidence", top_k=3)
    finally:
        session.close()


def test_legacy_fts_rows_without_snapshot_metadata_fail_loudly() -> None:
    session, _engine = build_session(2)
    try:
        session.exec(text("CREATE VIRTUAL TABLE chunk_fts USING fts5(chunk_id UNINDEXED, paper_id UNINDEXED, text)"))
        session.exec(
            text("INSERT INTO chunk_fts(chunk_id, paper_id, text) VALUES ('chunk-0000', 'paper-000', 'legacy evidence')")
        )
        session.commit()
        health = keyword_diagnostics(session)
        assert health["status"] == "invalid"
        with pytest.raises(KeywordIndexIntegrityError, match="without authoritative"):
            search_keyword(session, "legacy", top_k=3)
    finally:
        session.close()
