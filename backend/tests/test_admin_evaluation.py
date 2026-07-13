from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.api import evaluation as evaluation_api
from app.db import get_session
from app.evaluation.dashboard import build_evaluation_dashboard
from app.main import app
from app.models import Chunk, Paper, PaperArtifact, PaperTopic, RAGAnswer, ReviewEvent, ThesisRecommendation, Topic
from app.security import AuthenticatedActor, require_reviewer


TEST_ADMIN = AuthenticatedActor(
    actor_id="test-admin",
    display_name="Test Administrator",
    role="admin",
    reviewer_type="human",
    request_id="test-request",
)


def build_admin_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            Paper(
                paper_id="admin-paper",
                title="Admin Review Paper",
                authors=["Asha Singh"],
                year=2025,
                venue="Demo Venue",
                pdf_url="https://example.test/admin.pdf",
                pdf_text_status="extracted",
                pages_with_text=2,
                page_count=2,
                chunk_count=1,
                topics=["RAG"],
                review_status="needs_review",
            )
        )
        session.add(
            Chunk(
                chunk_id="admin-chunk",
                paper_id="admin-paper",
                chunk_index=0,
                page_start=1,
                page_end=2,
                section="Abstract",
                text="The paper presents a source grounded research advisor with evaluation.",
                word_count=10,
                source_hash="admin-hash",
            )
        )
        session.add(
            Topic(
                topic_id="retrieval",
                name="Retrieval",
                normalized_name="retrieval",
                review_status="ai_reviewed",
            )
        )
        session.add(
            PaperTopic(
                link_id="admin-paper-retrieval",
                paper_id="admin-paper",
                topic_id="retrieval",
                score=1.0,
                evidence_json=[{"paper_id": "admin-paper", "field": "title"}],
            )
        )
        session.add(
            RAGAnswer(
                answer_id="answer-1",
                question="What does the paper discuss?",
                answer="It discusses a research advisor.",
                citations_json=[{"paper_id": "admin-paper", "title": "Admin Review Paper", "chunk_id": "admin-chunk"}],
                grounding_status="grounded",
                review_status="needs_review",
            )
        )
        session.add(
            ThesisRecommendation(
                recommendation_id="recommendation-1",
                request_json={"interests": "RAG"},
                available_time="semester",
                project_type="software prototype",
                preferred_difficulty="medium",
                recommendations_json=[
                    {
                        "paper_id": "admin-paper",
                        "extension_title": "Advisor prototype",
                        "citations": [{"paper_id": "admin-paper", "title": "Admin Review Paper", "chunk_id": "admin-chunk"}],
                    }
                ],
                grounding_status="partial",
                review_status="needs_review",
            )
        )
        session.add(
            PaperArtifact(
                artifact_id="artifact-1",
                paper_id="admin-paper",
                artifact_type="public_summary",
                generated_json={
                    "text": "AI-assisted public summary.",
                    "citations": [{"paper_id": "admin-paper", "title": "Admin Review Paper", "chunk_id": "admin-chunk"}],
                },
                generated_text="AI-assisted public summary.",
                citations_json=[{"paper_id": "admin-paper", "title": "Admin Review Paper", "chunk_id": "admin-chunk"}],
                source_chunk_ids_json=["admin-chunk"],
                grounding_status="grounded",
                review_status="needs_review",
            )
        )
        session.commit()
    return engine


def make_override(engine):
    def override_session() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session

    return override_session


def test_review_event_model_can_be_created() -> None:
    event = ReviewEvent(
        review_event_id="event-1",
        item_type="paper",
        item_id="paper-1",
        action="approved",
        previous_status="needs_review",
        new_status="approved",
        reviewer_notes="Looks good.",
    )

    assert event.reviewer_name == "Legacy unattributed actor"
    assert event.reviewer_id == "legacy-unattributed"
    assert event.diff_json == {}


def test_paper_metadata_patch_updates_only_provided_fields_and_creates_event() -> None:
    engine = build_admin_engine()
    app.dependency_overrides[get_session] = make_override(engine)
    app.dependency_overrides[require_reviewer] = lambda: TEST_ADMIN
    try:
        client = TestClient(app)
        response = client.patch(
            "/api/admin/papers/admin-paper",
            json={"title": "Corrected Title", "review_status": "approved", "reviewer_notes": "Metadata checked."},
        )
        events = client.get("/api/admin/review-events", params={"item_type": "paper", "item_id": "admin-paper"})
        paper = client.get("/api/papers/admin-paper")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["paper"]["review_status"] == "needs_review"
    assert paper.json()["title"] == "Corrected Title"
    assert paper.json()["venue"] == "Demo Venue"
    assert events.status_code == 200
    assert events.json()[0]["action"] == "corrected"


def test_artifact_recommendation_and_answer_review_endpoints_create_events() -> None:
    engine = build_admin_engine()
    app.dependency_overrides[get_session] = make_override(engine)
    app.dependency_overrides[require_reviewer] = lambda: TEST_ADMIN
    try:
        client = TestClient(app)
        artifact = client.patch(
            "/api/admin/artifacts/artifact-1/review",
            json={"review_status": "approved", "reviewer_notes": "Summary is faithful.", "corrected_text": "Reviewed text."},
        )
        recommendation = client.patch(
            "/api/admin/recommendations/recommendation-1/review",
            json={"review_status": "rejected", "reviewer_notes": "Needs narrower scope."},
        )
        answer = client.patch(
            "/api/admin/answers/answer-1/review",
            json={
                "review_status": "approved",
                "reviewer_notes": "Citations match.",
                "citation_correct": True,
                "answer_faithfulness_score": 4,
                "usefulness_score": 5,
            },
        )
        events = client.get("/api/admin/review-events")
    finally:
        app.dependency_overrides.clear()

    assert artifact.status_code == 200
    assert artifact.json()["artifact"]["review_status"] == "needs_review"
    assert recommendation.status_code == 200
    assert recommendation.json()["recommendation"]["review_status"] == "rejected"
    assert answer.status_code == 200
    assert answer.json()["answer"]["citation_correct"] is True
    assert len(events.json()) == 3


def test_review_queue_overview_events_and_stats_work() -> None:
    engine = build_admin_engine()
    app.dependency_overrides[get_session] = make_override(engine)
    app.dependency_overrides[require_reviewer] = lambda: TEST_ADMIN
    try:
        client = TestClient(app)
        queue = client.get("/api/admin/review-queue")
        overview = client.get("/api/admin/overview")
        events = client.get("/api/admin/review-events", params={"item_type": "paper"})
        stats = client.get("/api/stats")
    finally:
        app.dependency_overrides.clear()

    assert queue.status_code == 200
    assert queue.json()["total"] == 4
    assert overview.status_code == 200
    assert overview.json()["papers_needing_metadata_review"] == 1
    assert events.status_code == 200
    assert events.json() == []
    assert stats.status_code == 200
    assert stats.json()["admin_review_queue_count"] == 4
    assert stats.json()["evaluation_files_present"] == {
        "retrieval": True,
        "qa": True,
        "extension": True,
        "artifact": True,
    }
    assert stats.json()["top_topics"] == [["Retrieval", 1]]


def test_evaluation_dashboard_returns_not_run_when_files_are_absent(tmp_path: Path) -> None:
    engine = build_admin_engine()
    with Session(engine) as session:
        dashboard = build_evaluation_dashboard(session, tmp_path)

    assert dashboard["retrieval"]["status"] == "not_run"
    assert dashboard["qa"]["status"] == "not_run"
    assert dashboard["extension"]["status"] == "not_run"
    assert dashboard["artifact"]["status"] == "not_run"


def test_evaluation_dashboard_parses_existing_sample_results(tmp_path: Path) -> None:
    (tmp_path / "retrieval_eval_results.json").write_text(
        json.dumps({"metrics": {"question_count": 2, "recall_at_3": 0.5, "recall_at_5": 1.0, "mrr": 0.75}, "questions": []}),
        encoding="utf-8",
    )
    (tmp_path / "qa_eval_results.json").write_text(
        json.dumps({"question_count": 1, "results": [{"any_gold_paper_cited": True, "citation_count": 2, "grounding_status": "grounded"}]}),
        encoding="utf-8",
    )
    (tmp_path / "extension_eval_results.json").write_text(
        json.dumps(
            {
                "case_count": 1,
                "cases": [{"recommendation_count": 2, "warnings_count": 1}],
                "metrics": {"average_citation_coverage": 1.0, "grounded_cases": 1, "partial_cases": 0, "unsupported_cases": 0},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "artifact_eval_results.json").write_text(
        json.dumps(
            {
                "case_count": 1,
                "cases": [
                    {
                        "artifact_count": 2,
                        "warnings_count": 1,
                        "sections_with_explicit_support": 1,
                        "sections_inferred": 2,
                        "sections_not_found": 0,
                    }
                ],
                "metrics": {"average_citation_coverage": 0.5, "grounded_cases": 0, "partial_cases": 1, "unsupported_cases": 0},
            }
        ),
        encoding="utf-8",
    )
    engine = build_admin_engine()
    with Session(engine) as session:
        dashboard = build_evaluation_dashboard(session, tmp_path)

    assert dashboard["retrieval"]["recall_at_3"] == 0.5
    assert dashboard["qa"]["cited_gold_paper_count"] == 1
    assert dashboard["extension"]["recommendation_count"] == 2
    assert dashboard["artifact"]["sections_inferred"] == 2


def test_evaluation_dashboard_endpoint_can_return_not_run_with_temp_dir(monkeypatch, tmp_path: Path) -> None:
    engine = build_admin_engine()

    def temp_dashboard(session: Session):
        return build_evaluation_dashboard(session, tmp_path)

    monkeypatch.setattr(evaluation_api, "build_evaluation_dashboard", temp_dashboard)
    app.dependency_overrides[get_session] = make_override(engine)
    try:
        client = TestClient(app)
        response = client.get("/api/evaluation/dashboard")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["retrieval"]["status"] == "not_run"


def test_default_evaluation_dashboard_exposes_executed_silver_experiments() -> None:
    engine = build_admin_engine()
    with Session(engine) as session:
        dashboard = build_evaluation_dashboard(session)

    assert dashboard["evaluation_label"].startswith("AI-reviewed silver")
    assert dashboard["human_validation"] is False
    assert dashboard["retrieval"]["status"] == "available"
    assert dashboard["retrieval"]["question_count"] == 50
    assert dashboard["retrieval"]["recall_at_10"] == 1.0
    assert dashboard["qa"]["claim_count"] == 400
    assert dashboard["qa"]["citation_correctness"] == 0.625
    assert dashboard["extension"]["case_count"] == 28
    assert dashboard["extension"]["relevance_difference_ci"][0] < 0
    assert dashboard["artifact"]["review_event_count"] == 48
    assert dashboard["artifact"]["needs_reprocess_count"] == 27
