from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.db import get_session
from app.evaluation.extension_eval import citation_coverage_percentage, evaluate_case
from app.indexing.keyword_search import rebuild_keyword_index
from app.intelligence.extension_recommender import (
    ExtensionFinderRequest,
    group_results_by_paper,
    recommend_extensions,
)
from app.intelligence.recommendation_verifier import verify_recommendations
from app.main import app
from app.models import Chunk, Paper, ThesisRecommendation


def build_extension_session() -> tuple[Session, object]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    session = Session(engine)
    session.add(
        Paper(
            paper_id="rag-platform",
            title="RAG Platform for Research Discovery",
            authors=["Asha Singh", "Ben Lee"],
            year=2025,
            post_url="https://lab.tt/rag-platform",
            pdf_url="https://lab.tt/rag-platform.pdf",
            pdf_text_status="extracted",
            chunk_count=2,
        )
    )
    session.add(
        Paper(
            paper_id="traffic-dashboard",
            title="Traffic Data Dashboard",
            authors=["Cara Mills"],
            year=2024,
            post_url="https://lab.tt/traffic-dashboard",
            pdf_text_status="extracted",
            chunk_count=1,
        )
    )
    session.add(
        Chunk(
            chunk_id="rag-platform-0001",
            paper_id="rag-platform",
            chunk_index=0,
            page_start=1,
            page_end=2,
            section="Introduction",
            text=(
                "This paper presents retrieval augmented generation for academic research discovery "
                "using a web application and cited source chunks."
            ),
            word_count=16,
            source_hash="rag-1",
        )
    )
    session.add(
        Chunk(
            chunk_id="rag-platform-0002",
            paper_id="rag-platform",
            chunk_index=1,
            page_start=7,
            page_end=8,
            section="Future Work",
            text=(
                "Future work includes improving evaluation datasets, extending the prototype for students, "
                "and testing usability in education settings."
            ),
            word_count=16,
            source_hash="rag-2",
        )
    )
    session.add(
        Chunk(
            chunk_id="traffic-dashboard-0001",
            paper_id="traffic-dashboard",
            chunk_index=0,
            page_start=3,
            page_end=4,
            section="Methods",
            text="The traffic dashboard uses public data visualization to analyze congestion patterns.",
            word_count=10,
            source_hash="traffic-1",
        )
    )
    session.commit()
    rebuild_keyword_index(session)
    return session, engine


def extension_request() -> ExtensionFinderRequest:
    return ExtensionFinderRequest(
        interests="RAG, web apps, education",
        skills=["Python", "React", "FastAPI"],
        available_time="semester",
        project_type="software prototype",
        data_constraints="prefer public or synthetic data",
        preferred_difficulty="medium",
        preferred_topics=["AI", "research discovery"],
        top_k=2,
        retrieval_mode="keyword",
    )


def test_extension_request_schema_validates_valid_input() -> None:
    request = extension_request()

    assert request.interests == "RAG, web apps, education"
    assert request.top_k == 2


def test_extension_request_rejects_empty_interests() -> None:
    with pytest.raises(ValidationError):
        ExtensionFinderRequest(interests="   ")


def test_recommender_retrieves_and_groups_chunks_by_paper() -> None:
    session, _engine = build_extension_session()
    try:
        response = recommend_extensions(session, extension_request(), persist=False)
        grouped = group_results_by_paper(
            [
                {
                    "paper_id": recommendation["paper_id"],
                    "paper_title": recommendation["paper_title"],
                    "authors": recommendation["authors"],
                    "year": recommendation["year"],
                    "chunk_id": recommendation["citations"][0]["chunk_id"],
                    "scores": {"combined": recommendation["fit_score"]},
                    "source": {},
                }
                for recommendation in response["recommendations"]
            ]
        )
    finally:
        session.close()

    assert "rag-platform" in grouped
    assert grouped["rag-platform"]["chunks"]


def test_recommender_returns_ranked_recommendations_with_citations() -> None:
    session, _engine = build_extension_session()
    try:
        response = recommend_extensions(session, extension_request())
        stored = session.get(ThesisRecommendation, response["recommendation_id"])
    finally:
        session.close()

    assert response["recommendations"]
    assert response["recommendations"][0]["rank"] == 1
    assert response["recommendations"][0]["citations"]
    assert response["recommendations"][0]["identified_gap"]["support_status"] in {
        "explicit_in_paper",
        "inferred_from_paper",
        "not_found",
    }
    assert stored is not None


def test_offline_recommendation_provider_works_without_external_api() -> None:
    session, _engine = build_extension_session()
    try:
        request = extension_request()
        request.provider = "openai"
        response = recommend_extensions(session, request, persist=False)
    finally:
        session.close()

    assert response["provider"] == "offline_deterministic"
    assert any("not implemented" in warning for warning in response["warnings"])


def test_recommendation_verifier_marks_grounded_partial_and_unsupported() -> None:
    retrieved = {"c1": {"chunk_id": "c1"}}
    base_recommendation = {
        "rank": 1,
        "citations": [{"chunk_id": "c1", "paper_id": "p1", "score": 0.5}],
        "source_supported_facts": [{"chunk_id": "c1", "claim": "Fact"}],
        "identified_gap": {"support_status": "explicit_in_paper"},
        "data_availability": "public",
        "skills_gap": [],
        "difficulty": "medium",
        "implementation_time": "semester",
    }
    grounded = verify_recommendations([base_recommendation], retrieved, available_time="semester")
    partial = verify_recommendations(
        [{**base_recommendation, "identified_gap": {"support_status": "inferred_from_paper"}}],
        retrieved,
        available_time="semester",
    )
    unsupported = verify_recommendations([{**base_recommendation, "citations": []}], retrieved, available_time="semester")

    assert grounded["grounding_status"] == "grounded"
    assert partial["grounding_status"] == "partial"
    assert unsupported["grounding_status"] == "unsupported"


def test_extension_recommendation_api_endpoints_and_stats_work() -> None:
    session, engine = build_extension_session()
    session.close()

    def override_session() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    try:
        client = TestClient(app)
        posted = client.post("/api/recommendations/extensions", json=extension_request().model_dump())
        recommendation_id = posted.json()["recommendation_id"]
        fetched = client.get(f"/api/recommendations/extensions/{recommendation_id}")
        history = client.get("/api/recommendations/extensions/history")
        diagnostics = client.get("/api/recommendations/extensions/diagnostics")
        stats = client.get("/api/stats")
    finally:
        app.dependency_overrides.clear()

    assert posted.status_code == 200
    assert posted.json()["recommendations"][0]["citations"]
    assert fetched.status_code == 200
    assert fetched.json()["recommendation_id"] == recommendation_id
    assert history.status_code == 200
    assert history.json()[0]["recommendation_id"] == recommendation_id
    assert diagnostics.status_code == 200
    assert diagnostics.json()["total_recommendation_runs"] == 1
    assert stats.status_code == 200
    assert stats.json()["total_extension_recommendation_runs"] == 1
    assert stats.json()["total_extension_ideas"] >= 1


def test_extension_eval_calculates_citation_coverage_correctly() -> None:
    response = {
        "recommendation_id": "run-1",
        "grounding_status": "grounded",
        "warnings": [],
        "recommendations": [
            {
                "paper_id": "p1",
                "extension_title": "One",
                "citations": [{"paper_id": "p1"}],
                "warnings": [],
                "difficulty": "medium",
                "risk_level": "low",
            },
            {
                "paper_id": "p2",
                "extension_title": "Two",
                "citations": [],
                "warnings": ["Needs data check"],
                "difficulty": "hard",
                "risk_level": "medium",
            },
        ],
    }
    evaluated = evaluate_case({"case_id": "case-1"}, response)

    assert citation_coverage_percentage(1, 2) == 0.5
    assert evaluated["percentage_recommendations_with_citations"] == 0.5
    assert evaluated["citation_count"] == 1
