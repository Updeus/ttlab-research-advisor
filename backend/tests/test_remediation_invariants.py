from __future__ import annotations

import hashlib
import json
from pathlib import Path

import fitz
import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.api.admin import (
    ArtifactCorrectionRequest,
    ArtifactReviewRequest,
    RecommendationCorrectionRequest,
    RecommendationReviewRequest,
    review_artifact,
    review_recommendation,
    save_artifact_correction,
    save_recommendation_correction,
)
from app.api.ask import AskRequest
from app.api.index_health import _project_health
from app.config import Settings
from app.db import (
    assert_sqlite_json_integrity,
    initialize_sqlite_durability,
    install_sqlite_connection_pragmas,
    sqlite_integrity_diagnostics,
    sqlite_json_integrity_violations,
)
from app.evaluation import dashboard as dashboard_module
from app.indexing import retriever as retriever_module
from app.indexing.chunker import (
    canonical_chunks_sha256,
    chunk_from_db,
    chunk_manifest_path,
    db_chunk_payload,
    validate_extraction_artifact_link,
)
from app.indexing.embedder import IndexIntegrityError, eligible_chunks, index_writer_lock
from app.indexing.retriever import retrieve
from app.ingestion.manual_import import upsert_papers
from app.ingestion.pdf_downloader import DownloadRecord, download_pdfs
from app.ingestion.pdf_parser import extract_pdf_text
from app.ingestion.sync import execute_ttlab_sync
from app.intelligence.citation_verifier import verify_citations
from app.intelligence.extension_recommender import ExtensionFinderRequest, recommend_extensions
from app.intelligence.llm_provider import LLMAnswerDraft, OllamaProvider
from app.intelligence.paper_artifact_generator import serialize_public_artifact
from app.intelligence.rag_answerer import ask_question, assess_answerability
from app.models import Chunk, Paper, PaperArtifact, ReviewEvent, ThesisRecommendation
from app.models.paper import JSONEncodedValue
from app.publication import is_public_content
from app.runtime_provenance import retrieval_identity
from app.security import (
    AuthenticatedActor,
    operational_boundary_diagnostics,
    validate_security_configuration,
)


HUMAN_ADMIN = AuthenticatedActor(
    actor_id="human-admin",
    display_name="Human Admin",
    role="admin",
    reviewer_type="human",
    request_id="test-request",
)
EXTRACTION_GENERATION = "a" * 64
CHUNK_GENERATION = "b" * 64


def test_public_index_health_exposes_freshness_without_local_paths_or_technical_counts() -> None:
    projected = _project_health(
        {
            "status": "ready",
            "last_indexed_at": "2026-07-20T12:00:00Z",
            "index_path": "/private/index.json",
            "indexed_chunks": 719,
            "errors": [],
        },
        3,
    )

    assert projected == {
        "status": "ready",
        "projection_status": "public_projection_ready",
        "indexed_chunks": 3,
        "public_eligible_chunks": 3,
        "underlying_index_status": "ready",
        "underlying_representation_valid": True,
        "underlying_error_count": 0,
        "last_indexed_at": "2026-07-20T12:00:00Z",
    }


def memory_session() -> tuple[Session, object]:
    local_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(local_engine)
    return Session(local_engine), local_engine


def retrieval_row(paper_id: str, chunk_id: str, text: str) -> dict[str, object]:
    return {
        "paper_id": paper_id,
        "paper_title": f"Paper {paper_id}",
        "authors": ["Asha Singh"],
        "year": 2025,
        "venue": "TTLAB",
        "topics": ["retrieval"],
        "chunk_id": chunk_id,
        "chunk_index": 0,
        "section": "Methods",
        "page_start": 1,
        "page_end": 1,
        "snippet": text,
        "text": text,
        "score": 0.9,
        "source": {"pdf_url": "https://example.test/paper.pdf", "post_url": None},
    }


def test_technical_eligibility_is_not_public_access_and_scope_is_not_an_api_field(monkeypatch) -> None:
    session, _engine = memory_session()
    try:
        paper = Paper(
            paper_id="hidden",
            title="Hidden Technical Paper",
            corpus_eligibility_status="eligible",
            extraction_generation_id=EXTRACTION_GENERATION,
            chunk_extraction_generation_id=EXTRACTION_GENERATION,
            chunk_generation_id=CHUNK_GENERATION,
            public_index_generation_id=CHUNK_GENERATION,
            chunk_count=1,
        )
        session.add(paper)
        chunk = Chunk(
            chunk_id="hidden-c1",
            paper_id="hidden",
            text="retrieval augmented generation",
            extraction_generation_id=EXTRACTION_GENERATION,
        )
        session.add(chunk)
        session.flush()
        paper.chunk_generation_id = canonical_chunks_sha256(db_chunk_payload([chunk]))
        paper.public_index_generation_id = paper.chunk_generation_id
        session.add(paper)
        session.commit()
        raw = [retrieval_row("hidden", "hidden-c1", "retrieval augmented generation")]
        monkeypatch.setattr(retriever_module, "search_keyword", lambda *_args, **_kwargs: raw)
        monkeypatch.setattr(retriever_module, "enrich_keyword_results", lambda *_args, **_kwargs: raw)

        assert [chunk.chunk_id for chunk in eligible_chunks(session)] == ["hidden-c1"]
        assert eligible_chunks(session, public_only=True) == []
        assert retrieve(session, "retrieval", scope="technical")["result_count"] == 1
        assert retrieve(session, "retrieval")["result_count"] == 0
        assert not is_public_content(session, paper)

        paper.publication_status = "published"
        paper.rights_status = "cleared"
        paper.public_access_level = "searchable"
        session.add(paper)
        session.commit()
        assert retrieve(session, "retrieval")["result_count"] == 0
        paper.review_status = "approved"
        session.add(paper)
        session.commit()
        assert retrieve(session, "retrieval")["result_count"] == 0
        paper.extraction_review_status = "approved"
        session.add(paper)
        session.commit()
        assert retrieve(session, "retrieval")["result_count"] == 1
        assert is_public_content(session, paper)

        chunk.text = "retrieval bytes changed outside the rebuild workflow"
        session.add(chunk)
        session.commit()
        assert not is_public_content(session, paper)
        assert eligible_chunks(session, public_only=True) == []
        assert retrieve(session, "retrieval")["result_count"] == 0
    finally:
        session.close()

    assert "retrieval_scope" not in AskRequest.model_fields
    assert "retrieval_scope" not in ExtensionFinderRequest.model_fields


def test_public_retrieval_identity_redacts_hashes_when_metadata_omits_scope(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.runtime_provenance.index_diagnostics",
        lambda *_args, **_kwargs: {
            "embedding_provider": "feature_hashing",
            "status": "ready",
            "completeness_status": "complete",
            "index_sha256": "technical-index-secret",
            "corpus_snapshot_hash": "technical-corpus-secret",
        },
    )
    session, _engine = memory_session()
    try:
        identity = retrieval_identity(
            session,
            retrieval_mode="feature_hashing",
            retrieval_metadata={},
            corpus_scope="public",
        )
    finally:
        session.close()

    assert identity["scope"] == "public"
    assert identity["indexes"][0]["index_sha256"] is None
    assert identity["indexes"][0]["corpus_snapshot_hash"] is None


def test_review_and_correction_are_separate_and_public_uses_approved_effective_content() -> None:
    session, _engine = memory_session()
    try:
        session.add(Paper(paper_id="p1", title="Paper"))
        artifact = PaperArtifact(
            artifact_id="a1",
            paper_id="p1",
            artifact_type="public_summary",
            generated_json={"text": "generated"},
            generated_text="generated",
        )
        recommendation = ThesisRecommendation(
            recommendation_id="r1",
            request_json={"interests": "retrieval"},
            available_time="semester",
            project_type="software prototype",
            preferred_difficulty="medium",
            recommendations_json=[{"title": "generated"}],
        )
        session.add(artifact)
        session.add(recommendation)
        session.commit()

        with pytest.raises(ValidationError):
            ArtifactReviewRequest(review_status="approved", corrected_text="forbidden")
        with pytest.raises(ValidationError):
            RecommendationReviewRequest(
                review_status="approved",
                corrected_recommendations_json={"items": []},
            )

        save_artifact_correction(
            "a1",
            ArtifactCorrectionRequest(corrected_text="edited", corrected_json={"text": "edited"}),
            session,
            HUMAN_ADMIN,
        )
        save_recommendation_correction(
            "r1",
            RecommendationCorrectionRequest(
                corrected_recommendations_json=[
                    {
                        "paper_id": "p1",
                        "paper_title": "Paper",
                        "extension_title": "Edited extension",
                        "extension_summary": "Edited summary",
                        "mvp_scope": "Build a bounded prototype.",
                        "evaluation_plan": "Compare against a baseline.",
                        "difficulty": "medium",
                        "risk_level": "medium",
                        "citations": [],
                    }
                ]
            ),
            session,
            HUMAN_ADMIN,
        )
        assert artifact.review_status == "needs_review"
        assert artifact.generated_text == "generated"
        assert recommendation.recommendations_json == [{"title": "generated"}]

        review_artifact("a1", ArtifactReviewRequest(review_status="approved"), session, HUMAN_ADMIN)
        review_recommendation("r1", RecommendationReviewRequest(review_status="approved"), session, HUMAN_ADMIN)
        public = serialize_public_artifact(artifact)
        events = list(session.exec(select(ReviewEvent)).all())
    finally:
        session.close()

    assert public["effective_text"] == "edited"
    assert public["effective_json"] == {"text": "edited", "citations": []}
    assert public["provenance"]["approved_version"] == "corrected"
    assert [event.action for event in events].count("correction_saved") == 2


def test_answerability_claim_support_and_unused_citations(monkeypatch) -> None:
    mismatch = assess_answerability(
        "volcanic mineral policy",
        [retrieval_row("p1", "c1", "retrieval augmented generation for academic papers")],
        paper_id=None,
    )
    assert mismatch["answerable"] is False
    assert mismatch["reason"] == "hard_negative_source_mismatch"

    rows = [
        retrieval_row("p1", "c1", "retrieval augmented generation grounds cited answers"),
        retrieval_row("p2", "c2", "retrieval augmented methods provide a separate baseline"),
    ]

    class CitedProvider:
        def generate_answer(self, *_args, **_kwargs):
            return LLMAnswerDraft(
                answer_text="Retrieval augmented generation grounds cited answers [c1].",
                provider="test-provider",
                model="test-model@sha256:fixed",
                prompt_metadata={"prompt_sha256": "f" * 64},
            )

    monkeypatch.setattr(
        "app.intelligence.rag_answerer.retrieve",
        lambda *_args, **_kwargs: {
            "results": rows,
            "warnings": [],
            "expanded_query": "retrieval augmented generation",
            "query_expansions": [],
            "retrieval_strategy": "test",
        },
    )
    monkeypatch.setattr("app.intelligence.rag_answerer.get_provider", lambda *_args, **_kwargs: CitedProvider())
    session, _engine = memory_session()
    try:
        response = ask_question(session, "retrieval augmented generation", persist=False)
    finally:
        session.close()

    assert response["grounding_status"] == "partial"
    assert response["support_status"] == "support_unverified"
    assert response["claim_support"][0]["entailment_verified"] is False
    assert [citation["chunk_id"] for citation in response["citations"]] == ["c1"]
    assert response["retrieval_metadata"] == {
        "expanded_query": "retrieval augmented generation",
        "query_expansions": [],
        "retrieval_strategy": "test",
        "retrieval_scope": "public",
    }


def test_abstained_answer_retains_the_same_public_retrieval_metadata_contract(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.intelligence.rag_answerer.retrieve",
        lambda *_args, **_kwargs: {
            "results": [],
            "warnings": [],
            "expanded_query": "volcanic mineral policy",
            "query_expansions": [],
            "retrieval_strategy": "explicit_config_v1",
            "retriever_config": {},
            "vector_provider": None,
        },
    )
    session, _engine = memory_session()
    try:
        response = ask_question(session, "volcanic mineral policy", persist=False)
    finally:
        session.close()

    assert response["grounding_status"] == "unsupported"
    assert response["retrieval_metadata"] == {
        "expanded_query": "volcanic mineral policy",
        "query_expansions": [],
        "retrieval_strategy": "explicit_config_v1",
        "retrieval_scope": "public",
    }


def test_ollama_requires_digest_and_records_immutable_provenance(monkeypatch) -> None:
    digest = "a" * 64
    settings = Settings(ollama_allowed_model_digests={"pinned:1": digest})
    monkeypatch.setattr("app.intelligence.llm_provider.get_settings", lambda: settings)

    def fake_get(*_args, **_kwargs):
        return httpx.Response(
            200,
            request=httpx.Request("GET", "http://localhost:11434/api/tags"),
            json={"models": [{"name": "pinned:1", "digest": f"sha256:{digest}"}]},
        )

    def fake_post(*_args, **_kwargs):
        return httpx.Response(
            200,
            request=httpx.Request("POST", "http://localhost:11434/api/generate"),
            json={
                "model": "pinned:1",
                "digest": f"sha256:{digest}",
                "response": "A cited claim [c1].",
                "eval_count": 1,
                "eval_duration": 1,
            },
        )

    monkeypatch.setattr("app.intelligence.llm_provider.httpx.get", fake_get)
    monkeypatch.setattr("app.intelligence.llm_provider.httpx.post", fake_post)
    with pytest.raises(ValueError, match="not enabled with its current digest"):
        OllamaProvider("arbitrary:latest")

    draft = OllamaProvider("pinned:1").generate_answer(
        "What is retrieved?",
        [{"chunk_id": "c1", "title": "Paper", "text": "A cited claim."}],
    )
    assert draft.model == f"pinned:1@sha256:{digest}"
    assert draft.prompt_metadata["model_digest"] == f"sha256:{digest}"
    assert len(draft.prompt_metadata["prompt_sha256"]) == 64
    assert len(draft.prompt_metadata["generation_config_sha256"]) == 64
    assert draft.prompt_metadata["provider_resolution"]["fallback_used"] is False
    assert draft.prompt_metadata["generation_time_digest_verified"] is True


def test_explicit_local_demo_allows_any_installed_ollama_model(monkeypatch) -> None:
    digest = "f" * 64
    settings = Settings(
        allow_insecure_local_demo=True,
        ollama_allow_all_local_models=True,
    )

    monkeypatch.setattr(
        "app.intelligence.llm_provider.httpx.get",
        lambda *_args, **_kwargs: httpx.Response(
            200,
            request=httpx.Request("GET", "http://localhost:11434/api/tags"),
            json={"models": [{"name": "anything:local", "digest": digest}]},
        ),
    )
    monkeypatch.setattr(
        "app.intelligence.llm_provider.httpx.post",
        lambda *_args, **_kwargs: httpx.Response(
            200,
            request=httpx.Request("POST", "http://localhost:11434/api/generate"),
            json={
                "model": "anything:local",
                "digest": digest,
                "response": "A locally generated cited answer [c1].",
            },
        ),
    )

    draft = OllamaProvider("anything:local", settings=settings).generate_answer(
        "What is retrieved?",
        [{"chunk_id": "c1", "title": "Paper", "text": "A cited claim."}],
    )

    assert draft.provider == "ollama"
    assert draft.model == f"anything:local@sha256:{digest}"
    assert draft.prompt_metadata["provider_resolution"]["model_policy"] == "all_installed_local_models"
    assert any("without a configured digest pin" in warning for warning in draft.warnings)


def test_ollama_standard_response_uses_pre_post_checks_without_claiming_digest_attestation(monkeypatch) -> None:
    digest = "d" * 64
    settings = Settings(ollama_allowed_model_digests={"pinned:1": digest})
    monkeypatch.setattr("app.intelligence.llm_provider.get_settings", lambda: settings)

    monkeypatch.setattr(
        "app.intelligence.llm_provider.httpx.get",
        lambda *_args, **_kwargs: httpx.Response(
            200,
            request=httpx.Request("GET", "http://localhost:11434/api/tags"),
            json={"models": [{"name": "pinned:1", "digest": digest}]},
        ),
    )
    monkeypatch.setattr(
        "app.intelligence.llm_provider.httpx.post",
        lambda *_args, **_kwargs: httpx.Response(
            200,
            request=httpx.Request("POST", "http://localhost:11434/api/generate"),
            json={"model": "pinned:1", "response": "Unattested output [c1]."},
        ),
    )

    draft = OllamaProvider("pinned:1").generate_answer(
        "What is retrieved?",
        [{"chunk_id": "c1", "title": "Paper", "text": "A cited claim."}],
    )
    assert draft.provider == "ollama"
    assert draft.model == "pinned:1"
    assert draft.prompt_metadata["generation_time_digest_verified"] is False
    assert draft.prompt_metadata["tag_stable_across_generation"] is True
    assert draft.prompt_metadata["preflight_model_digest"] == f"sha256:{digest}"
    assert draft.prompt_metadata["postflight_model_digest"] == f"sha256:{digest}"
    assert "model_digest" not in draft.prompt_metadata
    assert draft.prompt_metadata["provider_resolution"]["effective_model"] == "pinned:1"
    assert any("do not eliminate the tag-mutation race" in warning for warning in draft.warnings)


def test_ollama_falls_back_if_tag_changes_between_preflight_and_postflight(monkeypatch) -> None:
    expected = "d" * 64
    changed = "e" * 64
    settings = Settings(ollama_allowed_model_digests={"pinned:1": expected})
    monkeypatch.setattr("app.intelligence.llm_provider.get_settings", lambda: settings)
    calls = 0

    def fake_get(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        digest = expected if calls == 1 else changed
        return httpx.Response(
            200,
            request=httpx.Request("GET", "http://localhost:11434/api/tags"),
            json={"models": [{"name": "pinned:1", "digest": digest}]},
        )

    monkeypatch.setattr("app.intelligence.llm_provider.httpx.get", fake_get)
    monkeypatch.setattr(
        "app.intelligence.llm_provider.httpx.post",
        lambda *_args, **_kwargs: httpx.Response(
            200,
            request=httpx.Request("POST", "http://localhost:11434/api/generate"),
            json={"model": "pinned:1", "response": "Output from a changed tag [c1]."},
        ),
    )

    draft = OllamaProvider("pinned:1").generate_answer(
        "What is retrieved?",
        [{"chunk_id": "c1", "title": "Paper", "text": "A cited claim."}],
    )
    assert draft.provider == "offline_extractive"
    assert draft.prompt_metadata["generation_time_digest_verified"] is False
    assert draft.prompt_metadata["provider_resolution"]["fallback_reason"] == "ollama_model_identity_verification_failed"


def test_strict_json_foreign_keys_wal_busy_timeout_and_index_writer_lock(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Malformed JSON"):
        JSONEncodedValue().process_result_value("{broken", None)

    database = tmp_path / "integrity.db"
    local_engine = create_engine(f"sqlite:///{database}", connect_args={"check_same_thread": False})
    install_sqlite_connection_pragmas(local_engine)
    assert initialize_sqlite_durability(local_engine) == "wal"
    SQLModel.metadata.create_all(local_engine)
    diagnostics = sqlite_integrity_diagnostics(local_engine)
    assert diagnostics["foreign_keys"] == 1
    assert diagnostics["journal_mode"] == "wal"
    assert diagnostics["busy_timeout_ms"] >= 5_000
    assert diagnostics["multi_writer_supported"] is False
    with Session(local_engine) as session:
        session.add(Chunk(chunk_id="orphan", paper_id="missing", text="orphan"))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

    index_path = tmp_path / "index.json"
    with index_writer_lock(index_path):
        with pytest.raises(IndexIntegrityError, match="Another index writer"):
            with index_writer_lock(index_path):
                pass


def test_sqlite_json_audit_reports_exact_location_and_blocks_startup(tmp_path: Path) -> None:
    database = tmp_path / "damaged-json.db"
    local_engine = create_engine(f"sqlite:///{database}", connect_args={"check_same_thread": False})
    install_sqlite_connection_pragmas(local_engine)
    initialize_sqlite_durability(local_engine)
    SQLModel.metadata.create_all(local_engine)
    with Session(local_engine) as session:
        session.add(Paper(paper_id="damaged", title="Damaged JSON"))
        session.commit()
    with local_engine.begin() as connection:
        connection.exec_driver_sql("UPDATE paper SET authors = '{broken' WHERE paper_id = 'damaged'")

    diagnostics = sqlite_integrity_diagnostics(local_engine)
    with local_engine.connect() as connection, pytest.raises(RuntimeError, match=r"paper.*damaged.*authors"):
        assert_sqlite_json_integrity(connection)

    assert diagnostics["status"] == "misconfigured"
    assert diagnostics["json_integrity_violation_count"] == 1
    assert diagnostics["json_integrity_violations"] == [
        {
            "table": "paper",
            "row": {"paper_id": "damaged"},
            "column": "authors",
            "error": "malformed_json",
        }
    ]


def test_sqlite_json_audit_uses_only_columns_present_in_legacy_schema(tmp_path: Path) -> None:
    database = tmp_path / "legacy-json.db"
    local_engine = create_engine(f"sqlite:///{database}")
    with local_engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE paper (paper_id VARCHAR PRIMARY KEY, title VARCHAR NOT NULL, authors VARCHAR)"
        )
        connection.exec_driver_sql(
            "INSERT INTO paper (paper_id, title, authors) VALUES ('legacy', 'Legacy', '[\"Asha\"]')"
        )
        assert sqlite_json_integrity_violations(connection) == []
        connection.exec_driver_sql(
            "UPDATE paper SET authors = '{broken' WHERE paper_id = 'legacy'"
        )
        violations = sqlite_json_integrity_violations(connection)

    assert violations == [
        {
            "table": "paper",
            "row": {"paper_id": "legacy"},
            "column": "authors",
            "error": "malformed_json",
        }
    ]


def test_extraction_manifest_hash_link_is_authoritative_and_mismatch_is_quarantined(tmp_path: Path) -> None:
    pdf_path = tmp_path / "paper.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "Manifest Test Paper Abstract retrieval evidence")
    document.save(pdf_path)
    document.close()
    output_dir = tmp_path / "extracted"
    result = extract_pdf_text(
        "manifest-paper",
        pdf_path,
        output_dir,
        expected_title="Manifest Test Paper",
    )
    assert validate_extraction_artifact_link(result) == (True, None)
    text_path = Path(result["full_text_path"])
    text_path.write_text("mixed generation", encoding="utf-8")
    assert validate_extraction_artifact_link(result) == (False, "text_artifact_hash_mismatch")

    session, _engine = memory_session()
    try:
        extraction_json = output_dir / "manifest-paper.json"
        paper = Paper(
            paper_id="manifest-paper",
            title="Manifest Test Paper",
            pdf_text_status="extracted",
            extracted_json_path=str(extraction_json),
            corpus_eligibility_status="eligible",
            extraction_generation_id=result["artifact_generation_id"],
        )
        session.add(paper)
        session.commit()
        summary = chunk_from_db(session, output_dir=tmp_path / "chunks")
        session.refresh(paper)
    finally:
        session.close()
    assert summary["quarantined"] == 1
    assert paper.pdf_text_status == "quarantined_extraction_artifact_mismatch"
    assert paper.chunk_count == 0


def test_extraction_manifest_hashes_and_compares_raw_crlf_bytes(tmp_path: Path) -> None:
    text_path = tmp_path / "crlf.txt"
    serialized_bytes = b"--- Page 1 ---\nline one\r\nline two\rline three\n"
    text_path.write_bytes(serialized_bytes)
    text_artifact_sha256 = hashlib.sha256(serialized_bytes).hexdigest()
    extraction_config = {"native_extractor": "test-fixture"}
    input_pdf_sha256 = "c" * 64
    generation_id = hashlib.sha256(
        json.dumps(
            {
                "paper_id": "crlf-paper",
                "input_pdf_sha256": input_pdf_sha256,
                "extraction_config": extraction_config,
                "text_artifact_sha256": text_artifact_sha256,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    extracted = {
        "artifact_contract": "json_authoritative_text_mirror_v1",
        "paper_id": "crlf-paper",
        "text_artifact_sha256": text_artifact_sha256,
        "full_text_path": str(text_path),
        "artifact_generation_id": generation_id,
        "input_pdf_sha256": input_pdf_sha256,
        "extraction_config": extraction_config,
        "pages": [{"page_number": 1, "text": "line one\r\nline two\rline three"}],
    }

    assert validate_extraction_artifact_link(extracted) == (True, None)


def test_chunk_artifact_manifest_detects_and_repairs_file_and_database_generation_drift(tmp_path: Path) -> None:
    pdf_path = tmp_path / "chunk-contract.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "Chunk Contract Paper Abstract retrieval evidence with deterministic citations.")
    document.save(pdf_path)
    document.close()
    extraction = extract_pdf_text(
        "chunk-contract",
        pdf_path,
        tmp_path / "extracted",
        expected_title="Chunk Contract Paper",
    )
    chunks_dir = tmp_path / "chunks"
    output_path = chunks_dir / "chunk-contract.json"
    session, _engine = memory_session()
    try:
        session.add(
            Paper(
                paper_id="chunk-contract",
                title="Chunk Contract Paper",
                pdf_text_status="extracted",
                extracted_json_path=str(tmp_path / "extracted" / "chunk-contract.json"),
                corpus_eligibility_status="eligible",
                extraction_generation_id=extraction["artifact_generation_id"],
            )
        )
        session.commit()
        first = chunk_from_db(session, output_dir=chunks_dir, min_chars=0)
        expected_file = json.loads(output_path.read_text(encoding="utf-8"))
        assert chunk_manifest_path(output_path).exists()

        tampered_file = [dict(item) for item in expected_file]
        tampered_file[0]["text"] = "stale file generation"
        output_path.write_text(json.dumps(tampered_file), encoding="utf-8")
        repaired_file = chunk_from_db(session, output_dir=chunks_dir, min_chars=0)
        assert json.loads(output_path.read_text(encoding="utf-8")) == expected_file

        db_chunk = session.exec(select(Chunk).where(Chunk.paper_id == "chunk-contract")).one()
        db_chunk.text = "stale database generation"
        session.add(db_chunk)
        session.commit()
        repaired_db = chunk_from_db(session, output_dir=chunks_dir, min_chars=0)
        refreshed = session.exec(select(Chunk).where(Chunk.paper_id == "chunk-contract")).one()
    finally:
        session.close()

    assert extraction["artifact_contract"] == "json_authoritative_text_mirror_v1"
    assert first["chunked"] == 1
    assert repaired_file["repaired_artifact"] == 1
    assert repaired_db["repaired_artifact"] == 1
    assert refreshed.text == expected_file[0]["text"]


def test_reviewed_import_conflicts_and_material_source_change_invalidate_descendants() -> None:
    session, _engine = memory_session()
    try:
        reviewed = Paper(
            paper_id="reviewed",
            title="Human Title",
            review_status="approved",
            metadata_field_reviews={"title": "approved"},
        )
        mutable = Paper(
            paper_id="mutable",
            title="Mutable",
            pdf_url="https://example.test/old.pdf",
            local_pdf_path="data/pdfs/old.pdf",
            pdf_text_status="extracted",
            corpus_eligibility_status="eligible",
            chunk_count=1,
        )
        session.add(reviewed)
        session.add(mutable)
        session.add(Chunk(chunk_id="mutable-c1", paper_id="mutable", text="derived text"))
        session.commit()
        summary = upsert_papers(
            session,
            [
                {"paper_id": "reviewed", "title": "Automated Replacement"},
                {
                    "paper_id": "mutable",
                    "title": "Mutable",
                    "pdf_url": "https://example.test/new.pdf",
                },
            ],
        )
        session.refresh(reviewed)
        session.refresh(mutable)
        mutable_chunks = list(session.exec(select(Chunk).where(Chunk.paper_id == "mutable")).all())
    finally:
        session.close()

    assert reviewed.title == "Human Title"
    assert reviewed.metadata_provenance["title"]["incoming_conflict"]["status"] == "conflict_needs_human_review"
    assert summary["reviewed_field_conflicts"] >= 1
    assert summary["descendants_invalidated"] == 1
    assert mutable_chunks == []
    assert mutable.local_pdf_path is None
    assert mutable.corpus_eligibility_status == "needs_review"


def test_sync_pdf_and_rate_boundaries_fail_closed_in_api_and_production(tmp_path: Path) -> None:
    session, _engine = memory_session()
    called = False

    def discoverer(*_args):
        nonlocal called
        called = True
        return []

    try:
        result = execute_ttlab_sync(session, settings=Settings(), discoverer=discoverer)
    finally:
        session.close()
    assert result["status"] == "disabled"
    assert called is False

    production = Settings(security_mode="production")
    with pytest.raises(RuntimeError, match="disabled in production/API mode"):
        download_pdfs(
            [DownloadRecord(paper_id="p1", pdf_url="https://lab.tt/p1.pdf")],
            tmp_path,
            download=True,
            settings_override=production,
        )
    boundaries = operational_boundary_diagnostics(production)
    assert boundaries["pdf_processing"]["external_controls_implemented_by_application"] is False
    assert boundaries["pdf_processing"]["dns_rebinding_toctou_fully_mitigated"] is False
    assert boundaries["rate_limiting"]["implementation"] == "process_local_memory"
    assert boundaries["rate_limiting"]["distributed_limiter_implemented"] is False

    actor_json = json.dumps(
        [
            {
                "token_sha256": "a" * 64,
                "actor_id": "admin",
                "display_name": "Admin",
                "role": "admin",
                "reviewer_type": "human",
            }
        ]
    )
    unsupported_topology = Settings(
        security_mode="production",
        auth_actors_json=actor_json,
        trusted_hosts=["advisor.example"],
        public_base_url="https://advisor.example",
        cors_origins=["https://advisor.example"],
        api_worker_count=2,
    )
    with pytest.raises(ValueError, match="process-local"):
        validate_security_configuration(unsupported_topology)


def test_v1_commit_is_not_misrepresented_as_a_code_identity(monkeypatch, tmp_path: Path) -> None:
    files = {}
    for key in ("retrieval", "qa", "extension", "artifact"):
        path = tmp_path / f"{key}.json"
        path.write_text(
            json.dumps(
                {
                    "git_commit_at_execution": "old-commit",
                    "corpus_snapshot_hash": "old-corpus",
                    "configuration_hash": "old-config",
                }
            ),
            encoding="utf-8",
        )
        files[key] = path
    monkeypatch.setattr(dashboard_module, "ROOT", tmp_path)
    monkeypatch.setattr(dashboard_module, "CURRENT_RESULT_FILES", files)
    monkeypatch.setattr(dashboard_module, "current_code_commit", lambda: "new-commit")
    monkeypatch.setattr(dashboard_module, "v2_package_freshness", lambda: {"status": "not_run"})
    session, _engine = memory_session()
    try:
        freshness = dashboard_module.evaluation_freshness(session)
    finally:
        session.close()
    assert freshness["status"] == "historical"
    assert all(item["status"] == "historical" for item in freshness["artifacts"].values())
    assert all(item["checks"]["code"] == "unverifiable" for item in freshness["artifacts"].values())
    assert all("commit" not in item["checks"] for item in freshness["artifacts"].values())
    assert freshness["notice"].endswith("A repository HEAD change alone is not a freshness signal.")


def test_v2_freshness_rejects_unattested_partial_package(monkeypatch, tmp_path: Path) -> None:
    code_path = tmp_path / "backend" / "app" / "example.py"
    database_path = tmp_path / "data" / "papers.db"
    config_path = tmp_path / "backend" / "requirements-lock.txt"
    output_path = tmp_path / "artifacts" / "peer_review_remediation" / "v2" / "qa_metrics_v2.json"
    receipt_path = tmp_path / "artifacts" / "peer_review_remediation" / "v2" / "freeze_receipt_v2.json"
    manifest_path = tmp_path / "artifacts" / "peer_review_remediation" / "v2" / "manifest_v2.json"
    for path, value in (
        (code_path, "print('frozen')\n"),
        (database_path, "frozen database bytes"),
        (config_path, "dependency==1\n"),
        (output_path, '{"status":"complete"}\n'),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")

    def digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    receipt = {
        "files": {
            "backend/app/example.py": {"sha256": digest(code_path)},
            "data/papers.db": {"sha256": digest(database_path)},
            "backend/requirements-lock.txt": {"sha256": digest(config_path)},
        }
    }
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    manifest = {
        "evaluation_id": "peer-review-remediation-v2",
        "status": "completed",
        "freeze_receipt": receipt_path.relative_to(tmp_path).as_posix(),
        "freeze_receipt_sha256": digest(receipt_path),
        "outputs": {
            output_path.relative_to(tmp_path).as_posix(): {"sha256": digest(output_path)},
        },
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(dashboard_module, "ROOT", tmp_path)

    result = dashboard_module.v2_package_freshness(manifest_path)

    assert result["status"] == "invalid"
    assert "package_filename_inventory_mismatch" in result["errors"]
    assert "validation_attestation_schema_invalid" in result["errors"]
    assert result["head_commit_compared"] is False


def test_v2_freshness_rejects_unsafe_recorded_paths(monkeypatch, tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest_v2.json"
    manifest_path.write_text(
        json.dumps(
            {
                "evaluation_id": "peer-review-remediation-v2",
                "status": "completed",
                "freeze_receipt": "../outside/freeze.json",
                "freeze_receipt_sha256": "a" * 64,
                "outputs": {"../outside/result.json": {"sha256": "b" * 64}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(dashboard_module, "ROOT", tmp_path)

    result = dashboard_module.v2_package_freshness(manifest_path)

    assert result["status"] == "invalid"
    assert "freeze_receipt_missing_unsafe_or_noncanonical" in result["errors"]
    assert "unsafe_output_path" in result["errors"]


def test_finder_outputs_candidate_specific_evidence_and_unknown_time() -> None:
    rows = [
        {
            **retrieval_row(
                "crop-public",
                "crop-c1",
                "Crop machine learning uses a publicly available crop dataset and reports accuracy.",
            ),
            "scores": {"combined": 0.9},
        },
        {
            **retrieval_row(
                "crop-private",
                "private-c1",
                "Crop machine learning optimization uses a private dataset and reports latency.",
            ),
            "scores": {"combined": 0.8},
        },
    ]
    retrieval_response = {
        "results": rows,
        "warnings": [],
        "expanded_query": "crop machine learning",
        "query_expansions": [],
    }
    request = ExtensionFinderRequest(
        interests="crop machine learning",
        skills=["Python"],
        available_time="2 weeks",
        project_type="ML experiment",
        top_k=2,
    )
    session, _engine = memory_session()
    try:
        response = recommend_extensions(
            session,
            request,
            retrieval_response=retrieval_response,
            retrieval_scope="technical",
        )
    finally:
        session.close()
    by_id = {item["paper_id"]: item for item in response["recommendations"]}
    assert response["grounding_status"] == "partial"
    assert by_id["crop-public"]["data_availability"] == "public"
    assert by_id["crop-private"]["data_availability"] == "private"
    assert by_id["crop-public"]["mvp_scope"] != by_id["crop-private"]["mvp_scope"]
    assert by_id["crop-public"]["evaluation_plan"] != by_id["crop-private"]["evaluation_plan"]
    assert all(item["implementation_time"] == "unknown" for item in by_id.values())
    assert all(item["mvp_scope_basis"]["classification"] == "system_suggestion" for item in by_id.values())
    assert all(item["profile_constraints"]["classification"] == "student_supplied_preferences_not_paper_facts" for item in by_id.values())


def test_citation_verifier_never_claims_entailment_from_lexical_overlap() -> None:
    source = {"chunk_id": "c1", "snippet": "The model reports precision and recall."}
    result = verify_citations(
        "The model reports precision and recall [c1].",
        [source],
        [{"chunk_id": "c1", "paper_id": "p1", "title": "Paper", "snippet": source["snippet"]}],
    )
    assert result["grounding_status"] == "partial"
    assert result["support_status"] == "support_unverified"
    assert result["claim_support"][0]["entailment_verified"] is False


def test_citation_verifier_prunes_unrelated_co_citation_per_marker() -> None:
    sources = [
        {"chunk_id": "supporting", "snippet": "The RAG model reports precision and recall."},
        {"chunk_id": "unrelated", "snippet": "Coastal rainfall affects agricultural drainage."},
    ]
    citations = [
        {"chunk_id": source["chunk_id"], "paper_id": f"paper-{index}", "title": f"Paper {index}", "snippet": source["snippet"]}
        for index, source in enumerate(sources, start=1)
    ]
    result = verify_citations(
        "The RAG model reports precision and recall [supporting] [unrelated].",
        sources,
        citations,
    )

    support = result["claim_support"][0]
    assert support["cited_chunk_ids"] == ["supporting", "unrelated"]
    assert support["supporting_chunk_ids"] == ["supporting"]
    assert result["used_chunk_ids"] == ["supporting"]
    assert support["citation_support"] == [
        {
            "chunk_id": "supporting",
            "lexical_overlap": 1.0,
            "classification": "support_unverified",
            "entailment_verified": False,
        },
        {
            "chunk_id": "unrelated",
            "lexical_overlap": 0.0,
            "classification": "unsupported",
            "entailment_verified": False,
        },
    ]
