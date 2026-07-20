from __future__ import annotations

import hashlib
import json
from collections.abc import Generator
from pathlib import Path

import fitz
import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.config import Settings, get_settings
from app.db import get_session
from app.ingestion.pdf_downloader import DownloadRecord, download_pdfs, validate_remote_pdf_url
from app.ingestion.pdf_parser import extract_pdf_text, safe_output_path
from app.main import app, readiness_index_checks
from app.middleware import PublicRateLimitMiddleware
from app.models import Chunk, Paper, PaperArtifact, RAGAnswer, ReviewEvent, ThesisRecommendation
from app.security import parse_actor_records, validate_security_configuration

# Obvious deterministic fixtures, never deployment credentials.
ADMIN_TOKEN = "TEST_ONLY_ADMIN_" + ("a" * 32)
REVIEWER_TOKEN = "TEST_ONLY_REVIEWER_" + ("b" * 32)
AI_TOKEN = "TEST_ONLY_AI_REVIEWER_" + ("c" * 32)


def digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def security_settings() -> Settings:
    return Settings(
        auth_actors_json=json.dumps(
            [
                {
                    "token_sha256": digest(ADMIN_TOKEN),
                    "actor_id": "admin-jarod",
                    "display_name": "Administrator",
                    "role": "admin",
                    "reviewer_type": "human",
                },
                {
                    "token_sha256": digest(REVIEWER_TOKEN),
                    "actor_id": "reviewer-one",
                    "display_name": "Reviewer One",
                    "role": "reviewer",
                    "reviewer_type": "human",
                },
                {
                    "token_sha256": digest(AI_TOKEN),
                    "actor_id": "codex-ai-review",
                    "display_name": "Codex AI Review",
                    "role": "reviewer",
                    "reviewer_type": "ai",
                },
            ]
        )
    )


def build_security_engine():
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(test_engine)
    with Session(test_engine) as session:
        session.add(
            Paper(
                paper_id="secure-paper",
                title="Secure Paper",
                authors=["A. Researcher"],
                source_url="https://lab.tt/paper",
                pdf_url="https://lab.tt/paper.pdf",
                local_pdf_path="/private/workspace/data/pdfs/paper.pdf",
                extracted_json_path="/private/workspace/data/extracted/paper.json",
                extracted_text_path="/private/workspace/data/extracted/paper.txt",
                corpus_eligibility_status="eligible",
                review_status="needs_review",
            )
        )
        session.commit()
    return test_engine


def session_override(test_engine):
    def override() -> Generator[Session, None, None]:
        with Session(test_engine) as session:
            yield session

    return override


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_actor_configuration_accepts_only_hashed_unique_records() -> None:
    records = parse_actor_records(security_settings())
    assert {record.actor_id for record in records} == {"admin-jarod", "reviewer-one", "codex-ai-review"}
    assert ADMIN_TOKEN not in security_settings().auth_actors_json

    duplicate = Settings(
        auth_actors_json=json.dumps(
            [
                {
                    "token_sha256": digest(ADMIN_TOKEN),
                    "actor_id": "one",
                    "display_name": "One",
                    "role": "admin",
                    "reviewer_type": "human",
                },
                {
                    "token_sha256": digest(ADMIN_TOKEN),
                    "actor_id": "two",
                    "display_name": "Two",
                    "role": "reviewer",
                    "reviewer_type": "human",
                },
            ]
        )
    )
    with pytest.raises(ValueError, match="duplicate token digests"):
        parse_actor_records(duplicate)


def test_production_configuration_fails_closed_without_admin_or_https() -> None:
    with pytest.raises(ValueError, match="active environment-configured admin"):
        validate_security_configuration(
            Settings(
                security_mode="production",
                cors_origins=["https://advisor.example"],
                trusted_hosts=["advisor.example"],
                public_base_url="https://advisor.example",
            )
        )
    with pytest.raises(ValueError, match="https TTLAB_PUBLIC_BASE_URL"):
        validate_security_configuration(
            Settings(
                security_mode="production",
                auth_actors_json=security_settings().auth_actors_json,
                cors_origins=["https://advisor.example"],
                trusted_hosts=["advisor.example"],
                public_base_url="http://advisor.example",
            )
        )


def test_admin_routes_require_token_enforce_roles_and_attribute_events() -> None:
    test_engine = build_security_engine()
    app.dependency_overrides[get_session] = session_override(test_engine)
    app.dependency_overrides[get_settings] = security_settings
    try:
        client = TestClient(app)
        assert client.get("/api/admin/overview").status_code == 401
        assert client.get("/api/admin/overview", headers=auth(REVIEWER_TOKEN)).status_code == 200
        reviewer_sync = client.get("/api/admin/ingestion-sync", headers=auth(REVIEWER_TOKEN))
        assert reviewer_sync.status_code == 200
        assert reviewer_sync.json()["manual_trigger_allowed"] is False
        assert client.post("/api/admin/ingestion-sync/request", headers=auth(REVIEWER_TOKEN)).status_code == 403
        queued_sync = client.post("/api/admin/ingestion-sync/request", headers=auth(ADMIN_TOKEN))
        assert queued_sync.status_code == 202
        assert queued_sync.json()["accepted"] is True
        assert client.get("/api/admin/ingestion-sync", headers=auth(ADMIN_TOKEN)).json()[
            "manual_trigger_allowed"
        ] is True
        duplicate_sync = client.post("/api/admin/ingestion-sync/request", headers=auth(ADMIN_TOKEN))
        assert duplicate_sync.status_code == 202
        assert duplicate_sync.json()["accepted"] is False

        forbidden = client.patch(
            "/api/admin/papers/secure-paper",
            headers=auth(REVIEWER_TOKEN),
            json={"review_status": "approved"},
        )
        assert forbidden.status_code == 403

        ai_wrong_state = client.patch(
            "/api/admin/papers/secure-paper",
            headers=auth(AI_TOKEN),
            json={"review_status": "reviewed"},
        )
        assert ai_wrong_state.status_code == 403
        ai_review = client.patch(
            "/api/admin/papers/secure-paper",
            headers=auth(AI_TOKEN),
            json={"review_status": "ai_reviewed", "reviewer_notes": "Source checked."},
        )
        assert ai_review.status_code == 200
        event = ai_review.json()["review_event"]
        assert event["reviewer_id"] == "codex-ai-review"
        assert event["reviewer_type"] == "ai"
        assert event["reviewer_role"] == "reviewer"
        assert event["request_id"] != "unavailable"
        assert len(event["event_hash"]) == 64

        approved = client.patch(
            "/api/admin/papers/secure-paper",
            headers=auth(ADMIN_TOKEN),
            json={"review_status": "approved"},
        )
        assert approved.status_code == 200
        assert approved.json()["paper"]["reviewed_by"] == "admin-jarod"
        integrity = client.get("/api/admin/overview", headers=auth(ADMIN_TOKEN)).json()["review_event_integrity"]
        assert integrity["status"] == "verified"
        assert integrity["verified_events"] == 2
    finally:
        app.dependency_overrides.clear()


def test_correction_reopens_review_and_same_approved_status_cannot_bypass_role() -> None:
    test_engine = build_security_engine()
    with Session(test_engine) as session:
        session.add(
            PaperArtifact(
                artifact_id="artifact-one",
                paper_id="secure-paper",
                artifact_type="public_summary",
                generated_text="Original generated text",
                generated_json={"text": "Original generated text"},
                review_status="approved",
                reviewer_notes="Internal approval note",
                reviewed_by="admin-jarod",
                corrected_text="Previously approved correction",
                corrected_json={"text": "Previously approved correction"},
            )
        )
        session.add(
            ThesisRecommendation(
                recommendation_id="recommendation-one",
                available_time="semester",
                project_type="software prototype",
                preferred_difficulty="medium",
                review_status="approved",
                corrected_recommendations_json={"items": [{"title": "Old"}]},
            )
        )
        paper = session.get(Paper, "secure-paper")
        assert paper is not None
        paper.review_status = "approved"
        session.add(paper)
        session.commit()

    app.dependency_overrides[get_session] = session_override(test_engine)
    app.dependency_overrides[get_settings] = security_settings
    try:
        client = TestClient(app)
        same_status = client.patch(
            "/api/admin/papers/secure-paper",
            headers=auth(REVIEWER_TOKEN),
            json={"review_status": "approved", "reviewer_notes": "Cannot preserve approval."},
        )
        assert same_status.status_code == 403

        metadata_correction = client.patch(
            "/api/admin/papers/secure-paper",
            headers=auth(REVIEWER_TOKEN),
            json={"title": "Corrected secure paper", "review_status": "approved"},
        )
        assert metadata_correction.status_code == 200
        assert metadata_correction.json()["paper"]["review_status"] == "needs_review"
        assert metadata_correction.json()["review_event"]["previous_status"] == "approved"
        assert metadata_correction.json()["review_event"]["new_status"] == "needs_review"
        assert metadata_correction.json()["review_event"]["action"] == "corrected"

        artifact_correction = client.patch(
            "/api/admin/artifacts/artifact-one/review",
            headers=auth(ADMIN_TOKEN),
            json={
                "review_status": "approved",
                "reviewer_notes": "Draft correction must be reviewed again.",
                "corrected_text": "New correction",
            },
        )
        assert artifact_correction.status_code == 200
        assert artifact_correction.json()["artifact"]["review_status"] == "needs_review"
        assert artifact_correction.json()["review_event"]["new_status"] == "needs_review"

        recommendation_correction = client.patch(
            "/api/admin/recommendations/recommendation-one/review",
            headers=auth(ADMIN_TOKEN),
            json={
                "review_status": "approved",
                "corrected_recommendations_json": [{"title": "New"}],
            },
        )
        assert recommendation_correction.status_code == 200
        assert recommendation_correction.json()["recommendation"]["review_status"] == "needs_review"
    finally:
        app.dependency_overrides.clear()


def test_resource_mutations_provider_allowlist_and_input_bounds_are_enforced() -> None:
    test_engine = build_security_engine()
    app.dependency_overrides[get_session] = session_override(test_engine)
    app.dependency_overrides[get_settings] = security_settings
    try:
        client = TestClient(app)
        anonymous_generation = client.post(
            "/api/papers/secure-paper/artifacts/generate",
            json={"artifact_types": ["public_summary"]},
        )
        reviewer_generation = client.post(
            "/api/papers/missing/artifacts/generate",
            headers=auth(REVIEWER_TOKEN),
            json={"artifact_types": ["public_summary"]},
        )
        reviewer_batch = client.post(
            "/api/papers/artifacts/generate-batch",
            headers=auth(REVIEWER_TOKEN),
            json={"limit": 1, "artifact_types": ["public_summary"]},
        )
        disabled_provider = client.post(
            "/api/ask",
            json={"question": "A bounded question", "provider": "openai"},
        )
        excessive_question = client.post("/api/ask", json={"question": "x" * 2_001})
        invalid_url = client.patch(
            "/api/admin/papers/secure-paper",
            headers=auth(ADMIN_TOKEN),
            json={"source_url": "file:///etc/passwd"},
        )
    finally:
        app.dependency_overrides.clear()

    assert anonymous_generation.status_code == 401
    assert reviewer_generation.status_code == 404
    assert reviewer_batch.status_code == 403
    assert disabled_provider.status_code == 400
    assert excessive_question.status_code == 422
    assert invalid_url.status_code == 422


def test_review_event_table_rejects_update_and_delete() -> None:
    test_engine = build_security_engine()
    with test_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO reviewevent "
                "(review_event_id,item_type,item_id,action,reviewer_name,reviewer_id,reviewer_type,reviewer_role,request_id,diff_json,created_at) "
                "VALUES ('event-1','paper','secure-paper','reviewed','Reviewer','reviewer-one','human','reviewer','request-1','{}','2026-07-12')"
            )
        )
    with pytest.raises(DatabaseError, match="append-only"):
        with test_engine.begin() as connection:
            connection.execute(text("UPDATE reviewevent SET action='tampered' WHERE review_event_id='event-1'"))
    with pytest.raises(DatabaseError, match="append-only"):
        with test_engine.begin() as connection:
            connection.execute(text("DELETE FROM reviewevent WHERE review_event_id='event-1'"))


def test_public_ask_and_finder_do_not_persist_profile_or_question(monkeypatch) -> None:
    test_engine = build_security_engine()
    app.dependency_overrides[get_session] = session_override(test_engine)
    app.dependency_overrides[get_settings] = security_settings
    monkeypatch.setattr(
        "app.api.ask.ask_question",
        lambda _session, question, **kwargs: {
            "answer_id": "transient-answer",
            "question": question,
            "persist": kwargs["persist"],
        },
    )
    monkeypatch.setattr(
        "app.api.recommendations.recommend_extensions",
        lambda _session, request, **kwargs: {
            "recommendation_id": "transient-recommendation",
            "request": request.model_dump(),
            "persist": kwargs["persist"],
        },
    )
    try:
        client = TestClient(app)
        answer = client.post("/api/ask", json={"question": "private interest question"})
        finder = client.post(
            "/api/recommendations/extensions",
            json={"interests": "private student interests", "skills": ["Python"]},
        )
        assert answer.json()["persist"] is False
        assert finder.json()["persist"] is False
        assert answer.headers["cache-control"] == "no-store"
        assert finder.headers["cache-control"] == "no-store"
        assert client.get("/api/ask/history").status_code == 401
        assert client.get("/api/recommendations/extensions/history").status_code == 401
        with Session(test_engine) as session:
            assert session.exec(select(RAGAnswer)).all() == []
            assert session.exec(select(ThesisRecommendation)).all() == []
    finally:
        app.dependency_overrides.clear()


def test_public_paper_payloads_redact_local_paths_and_full_text_requires_auth() -> None:
    test_engine = build_security_engine()
    app.dependency_overrides[get_session] = session_override(test_engine)
    app.dependency_overrides[get_settings] = security_settings
    try:
        client = TestClient(app)
        paper = client.get("/api/papers/secure-paper")
        extraction = client.get("/api/papers/secure-paper/extraction")
        assert paper.status_code == 200
        assert "local_pdf_path" not in paper.json()
        assert "raw_record" not in paper.json()
        assert "extracted_json_path" not in extraction.json()
        assert "local_pdf_path" not in extraction.json()
        assert client.get("/api/papers/secure-paper/chunks", params={"full": True}).status_code == 403
        for endpoint in (
            "/api/search/diagnostics",
            "/api/ask/diagnostics",
            "/api/evaluation/dashboard",
            "/api/llms/benchmark/latest",
        ):
            response = client.get(endpoint)
            assert response.status_code == 200
            assert not collect_keys(response.json()).intersection(
                {"path", "index_path", "manifest_path", "local_pdf_path", "extracted_json_path"}
            )
    finally:
        app.dependency_overrides.clear()


def test_public_artifacts_hide_review_workspace_and_noneligible_evidence() -> None:
    test_engine = build_security_engine()
    with Session(test_engine) as session:
        session.add(
            PaperArtifact(
                artifact_id="draft-artifact",
                paper_id="secure-paper",
                artifact_type="public_summary",
                generated_text="Generated public summary",
                generated_json={"text": "Generated public summary"},
                review_status="needs_review",
                reviewer_notes="Private reviewer note",
                reviewed_by="reviewer-one",
                corrected_text="Unapproved correction",
                corrected_json={"text": "Unapproved correction"},
            )
        )
        session.add(
            Paper(
                paper_id="needs-review-paper",
                title="Needs Review Paper",
                authors=["A. Researcher"],
                corpus_eligibility_status="needs_review",
            )
        )
        session.add(
            Chunk(
                chunk_id="needs-review-chunk",
                paper_id="needs-review-paper",
                text="This source text is not cleared for public snippet display.",
            )
        )
        session.add(
            PaperArtifact(
                artifact_id="needs-review-artifact",
                paper_id="needs-review-paper",
                artifact_type="public_summary",
                generated_text="Not public",
                citations_json=[{"chunk_id": "needs-review-chunk", "snippet": "Not public"}],
            )
        )
        session.commit()

    app.dependency_overrides[get_session] = session_override(test_engine)
    app.dependency_overrides[get_settings] = security_settings
    try:
        client = TestClient(app)
        public_draft = client.get("/api/papers/secure-paper/artifacts/public_summary")
        assert public_draft.status_code == 200
        assert not {
            "reviewer_notes",
            "reviewed_by",
            "corrected_text",
            "corrected_json",
        }.intersection(public_draft.json())

        protected_draft = client.get(
            "/api/papers/secure-paper/artifacts/public_summary",
            headers=auth(REVIEWER_TOKEN),
        )
        assert protected_draft.status_code == 200
        assert protected_draft.json()["reviewer_notes"] == "Private reviewer note"
        assert protected_draft.json()["corrected_text"] == "Unapproved correction"

        approved = client.patch(
            "/api/admin/artifacts/draft-artifact/review",
            headers=auth(ADMIN_TOKEN),
            json={"review_status": "approved", "reviewer_notes": "Private approval note"},
        )
        assert approved.status_code == 200
        public_approved = client.get("/api/papers/secure-paper/artifacts/public_summary")
        assert public_approved.status_code == 200
        assert public_approved.json()["corrected_text"] == "Unapproved correction"
        assert public_approved.json()["corrected_json"] == {"text": "Unapproved correction"}
        assert "reviewer_notes" not in public_approved.json()
        assert "reviewed_by" not in public_approved.json()

        assert client.get("/api/papers/needs-review-paper/chunks").status_code == 404
        assert client.get("/api/papers/needs-review-paper/artifacts").status_code == 404
        assert (
            client.get(
                "/api/papers/needs-review-paper/chunks",
                headers=auth(REVIEWER_TOKEN),
            ).status_code
            == 200
        )
        assert (
            client.get(
                "/api/papers/needs-review-paper/artifacts",
                headers=auth(REVIEWER_TOKEN),
            ).status_code
            == 200
        )
    finally:
        app.dependency_overrides.clear()


def test_public_llm_status_omits_internal_endpoint_and_raw_error(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.api.llms.local_llm_status",
        lambda: {
            "available": False,
            "base_url": "http://10.0.0.5:11434",
            "models": [],
            "warnings": ["ConnectError http://10.0.0.5:11434 [Errno 111]"],
        },
    )
    response = TestClient(app).get("/api/llms/local")
    assert response.status_code == 200
    assert "base_url" not in response.json()
    serialized = json.dumps(response.json())
    assert "10.0.0.5" not in serialized
    assert "Errno" not in serialized


def test_readiness_requires_keyword_and_feature_hashing_but_dense_may_be_missing(monkeypatch) -> None:
    keyword_ready = {
        "status": "ready",
        "completeness_status": "complete",
        "keyword_indexed_chunks": 12,
        "eligible_chunks": 12,
    }
    feature_ready = {
        "status": "ready",
        "completeness_status": "complete",
        "indexed_chunks": 12,
        "eligible_chunks": 12,
    }
    dense_missing = {
        "status": "missing",
        "completeness_status": "missing",
        "indexed_chunks": 0,
        "eligible_chunks": 0,
    }
    monkeypatch.setattr("app.main.keyword_diagnostics", lambda _session: keyword_ready)
    monkeypatch.setattr(
        "app.main.index_diagnostics",
        lambda _session, _path, provider: feature_ready if provider == "feature_hashing" else dense_missing,
    )
    monkeypatch.setattr("app.main.validate_present_authoritative_indexes", lambda _session: {})

    checks, ready = readiness_index_checks(object())  # type: ignore[arg-type]
    assert ready is True
    assert checks["keyword_index"]["required"] is True
    assert checks["feature_hashing_index"]["required"] is True
    assert checks["dense_index"] == {
        "required": False,
        "ready": False,
        "status": "missing",
        "completeness_status": "missing",
        "indexed_chunks": 0,
        "eligible_chunks": 0,
    }

    monkeypatch.setattr(
        "app.main.keyword_diagnostics",
        lambda _session: {**keyword_ready, "status": "not_built", "completeness_status": "missing"},
    )
    _checks, ready = readiness_index_checks(object())  # type: ignore[arg-type]
    assert ready is False

    monkeypatch.setattr("app.main.keyword_diagnostics", lambda _session: keyword_ready)
    monkeypatch.setattr(
        "app.main.index_diagnostics",
        lambda _session, _path, provider: (
            {**feature_ready, "status": "missing", "completeness_status": "missing"}
            if provider == "feature_hashing"
            else dense_missing
        ),
    )
    _checks, ready = readiness_index_checks(object())  # type: ignore[arg-type]
    assert ready is False


def collect_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(*(collect_keys(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(collect_keys(item) for item in value))
    return set()


def test_security_headers_exact_cors_and_body_limit() -> None:
    client = TestClient(app)
    allowed = client.get("/health", headers={"Origin": "http://localhost:5173"})
    disallowed = client.get("/health", headers={"Origin": "https://evil.example"})
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "access-control-allow-origin" not in disallowed.headers
    assert allowed.headers["x-content-type-options"] == "nosniff"
    assert allowed.headers["x-frame-options"] == "DENY"
    assert allowed.headers["x-ttlab-security-mode"] == "local_demo"
    assert "x-request-id" in allowed.headers

    oversized = client.post(
        "/api/ask",
        content=b"x" * 1_048_577,
        headers={"Content-Type": "application/json"},
    )
    assert oversized.status_code == 413

    openapi = client.get("/openapi.json").json()
    assert "ReviewerAdminBearer" in openapi["components"]["securitySchemes"]
    assert openapi["paths"]["/api/admin/overview"]["get"]["security"]


def test_public_generation_rate_limiter_is_bounded_per_path() -> None:
    small_app = FastAPI()

    @small_app.post("/api/ask")
    def generated() -> dict[str, bool]:
        return {"ok": True}

    small_app.add_middleware(PublicRateLimitMiddleware, requests_per_minute=2)
    client = TestClient(small_app)
    assert client.post("/api/ask").status_code == 200
    assert client.post("/api/ask").status_code == 200
    limited = client.post("/api/ask")
    assert limited.status_code == 429
    assert limited.headers["Retry-After"] == "60"


def test_ssrf_validation_blocks_private_resolution_and_redirect_before_following(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="non-public"):
        validate_remote_pdf_url(
            "https://lab.tt/paper.pdf",
            allowed_hosts=["lab.tt"],
            resolver=lambda *_args, **_kwargs: ["127.0.0.1"],
        )

    requests: list[str] = []

    def redirect_transport(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(302, headers={"Location": "http://127.0.0.1/private.pdf"}, request=request)

    client = httpx.Client(transport=httpx.MockTransport(redirect_transport))
    try:
        result = download_pdfs(
            [DownloadRecord(paper_id="redirect", pdf_url="https://lab.tt/redirect.pdf")],
            tmp_path,
            download=True,
            client=client,
            allowed_hosts=["lab.tt"],
            resolver=lambda *_args, **_kwargs: ["93.184.216.34"],
        )
    finally:
        client.close()
    assert result["blocked_url"] == 1
    assert requests == ["https://lab.tt/redirect.pdf"]
    assert not list(tmp_path.glob("*.part"))
    assert not (tmp_path / "redirect.pdf").exists()


def test_pdf_download_byte_limit_is_streamed_and_atomic(tmp_path: Path) -> None:
    content = b"%PDF-1.7\n" + b"x" * 1_200_000
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                headers={"Content-Type": "application/pdf"},
                content=content,
                request=request,
            )
        )
    )
    try:
        result = download_pdfs(
            [DownloadRecord(paper_id="large", pdf_url="https://lab.tt/large.pdf")],
            tmp_path,
            download=True,
            client=client,
            allowed_hosts=["lab.tt"],
            max_bytes=1_048_576,
            resolver=lambda *_args, **_kwargs: ["93.184.216.34"],
        )
    finally:
        client.close()
    assert result["oversize"] == 1
    assert not (tmp_path / "large.pdf").exists()
    assert not list(tmp_path.glob("*.part"))


def test_output_paths_are_sanitized_and_parser_rejects_page_limit(tmp_path: Path) -> None:
    safe = safe_output_path(tmp_path, "../../outside", ".json")
    assert safe.parent == tmp_path
    assert safe.name != "outside.json"

    source = tmp_path / "two-pages.pdf"
    document = fitz.open()
    document.new_page().insert_text((72, 72), "Page one")
    document.new_page().insert_text((72, 72), "Page two")
    document.save(source)
    document.close()

    result = extract_pdf_text(
        "two-pages",
        source,
        tmp_path / "out",
        overwrite=True,
        max_pdf_pages=1,
    )
    assert result["extraction_status"] == "failed"
    assert "page parser limit" in result["diagnostics"]["extraction_error"]
