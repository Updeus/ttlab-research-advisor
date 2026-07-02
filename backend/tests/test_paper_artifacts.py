from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.db import get_session
from app.evaluation.artifact_eval import citation_coverage_percentage, evaluate_case
from app.intelligence.artifact_verifier import verify_artifact_payload
from app.intelligence.paper_artifact_generator import generate_paper_artifacts
from app.main import app
from app.models import Chunk, Paper, PaperArtifact


def build_artifact_session() -> tuple[Session, object]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    session = Session(engine)
    session.add(
        Paper(
            paper_id="artifact-paper",
            title="Machine Learning Research Advisor",
            authors=["Asha Singh"],
            year=2025,
            pdf_text_status="extracted",
            pages_with_text=8,
            page_count=8,
            chunk_count=3,
        )
    )
    session.add(
        Chunk(
            chunk_id="artifact-paper-0001",
            paper_id="artifact-paper",
            chunk_index=0,
            page_start=1,
            page_end=2,
            section="Abstract",
            text=(
                "This paper presents a research advisor system for academic discovery. "
                "The system uses retrieval and a web application to help students inspect papers."
            ),
            word_count=20,
            source_hash="artifact-1",
        )
    )
    session.add(
        Chunk(
            chunk_id="artifact-paper-0002",
            paper_id="artifact-paper",
            chunk_index=1,
            page_start=3,
            page_end=4,
            section="Methodology",
            text=(
                "The method uses a Python pipeline, machine learning classification, retrieval, "
                "and a dashboard interface to organize paper evidence."
            ),
            word_count=18,
            source_hash="artifact-2",
        )
    )
    session.add(
        Chunk(
            chunk_id="artifact-paper-0003",
            paper_id="artifact-paper",
            chunk_index=2,
            page_start=5,
            page_end=6,
            section="Results",
            text=(
                "Evaluation results compare retrieval accuracy and task success. "
                "The approach reports precision and recall for the research discovery workflow."
            ),
            word_count=18,
            source_hash="artifact-3",
        )
    )
    session.commit()
    return session, engine


def test_paper_artifact_generator_handles_paper_with_chunks() -> None:
    session, _engine = build_artifact_session()
    try:
        response = generate_paper_artifacts(
            session,
            "artifact-paper",
            ["paper_intelligence_bundle", "podcast_script"],
            overwrite=True,
        )
        stored = session.exec(PaperArtifact.__table__.select()).all()
    finally:
        session.close()

    assert response["paper_id"] == "artifact-paper"
    assert len(response["artifacts"]) == 2
    assert stored


def test_generator_returns_summaries_with_citations_and_statuses() -> None:
    session, _engine = build_artifact_session()
    try:
        response = generate_paper_artifacts(session, "artifact-paper", ["paper_intelligence_bundle"], overwrite=True)
    finally:
        session.close()

    bundle = response["artifacts"][0]["generated_json"]
    assert bundle["public_summary"]["citations"]
    assert bundle["technical_summary"]["citations"]
    assert bundle["limitations"]["support_status"] == "not_found"
    assert bundle["future_work"]["support_status"] in {"not_found", "inferred"}


def test_possible_extensions_are_marked_as_system_suggestions() -> None:
    session, _engine = build_artifact_session()
    try:
        response = generate_paper_artifacts(session, "artifact-paper", ["paper_intelligence_bundle"], overwrite=True)
    finally:
        session.close()

    extensions = response["artifacts"][0]["generated_json"]["possible_extensions"]
    assert extensions
    assert all(extension["support_status"] == "suggested_by_system" for extension in extensions)


def test_required_skills_are_generated_deterministically_from_methods() -> None:
    session, _engine = build_artifact_session()
    try:
        response = generate_paper_artifacts(session, "artifact-paper", ["required_skills"], overwrite=True)
    finally:
        session.close()

    skills = response["artifacts"][0]["generated_json"]["skills"]
    assert "Python" in skills
    assert "machine learning" in skills


def test_podcast_script_generator_returns_dialogue_and_citations() -> None:
    session, _engine = build_artifact_session()
    try:
        response = generate_paper_artifacts(session, "artifact-paper", ["podcast_script"], overwrite=True)
    finally:
        session.close()

    podcast = response["artifacts"][0]["generated_json"]
    assert podcast["duration_target"] == "3-5 minutes"
    assert podcast["script"][0]["speaker"] == "Host"
    assert podcast["citations"]


def test_artifact_verifier_statuses() -> None:
    paper = Paper(paper_id="verify-paper", title="Verify", pdf_text_status="extracted", pages_with_text=2, page_count=2)
    citation = {"paper_id": "verify-paper", "title": "Verify", "chunk_id": "c1", "snippet": "Evidence"}
    grounded = verify_artifact_payload("public_summary", {"text": "Summary", "citations": [citation]}, {"c1"}, paper, source_chunk_count=3)
    partial = verify_artifact_payload(
        "possible_extensions",
        {"items": [{"support_status": "suggested_by_system", "citations": [citation]}], "citations": [citation]},
        {"c1"},
        paper,
        source_chunk_count=3,
    )
    unsupported = verify_artifact_payload("public_summary", {"text": "Summary", "citations": []}, {"c1"}, paper, source_chunk_count=3)

    assert grounded["grounding_status"] == "grounded"
    assert partial["grounding_status"] == "partial"
    assert unsupported["grounding_status"] == "unsupported"


def test_artifact_api_endpoints_and_batch_limit_work() -> None:
    session, engine = build_artifact_session()
    session.close()

    def override_session() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    try:
        client = TestClient(app)
        generated = client.post(
            "/api/papers/artifact-paper/artifacts/generate",
            json={"artifact_types": ["paper_intelligence_bundle", "podcast_script"], "overwrite": True},
        )
        listed = client.get("/api/papers/artifact-paper/artifacts")
        diagnostics = client.get("/api/artifacts/diagnostics")
        batch = client.post(
            "/api/papers/artifacts/generate-batch",
            json={"limit": 1, "artifact_types": ["paper_intelligence_bundle"], "overwrite": True},
        )
    finally:
        app.dependency_overrides.clear()

    assert generated.status_code == 200
    assert generated.json()["artifacts"][0]["citations"]
    assert listed.status_code == 200
    assert len(listed.json()) >= 2
    assert diagnostics.status_code == 200
    assert diagnostics.json()["total_artifacts"] >= 2
    assert batch.status_code == 200
    assert batch.json()["processed"] == 1


def test_artifact_eval_calculates_citation_coverage() -> None:
    assert citation_coverage_percentage(1, 2) == 0.5

    session, _engine = build_artifact_session()
    try:
        evaluated = evaluate_case(
            session,
            {
                "case_id": "artifact-case",
                "paper_id": "artifact-paper",
                "artifact_types": ["public_summary", "technical_summary"],
            },
        )
    finally:
        session.close()

    assert evaluated["artifact_count"] == 2
    assert evaluated["percentage_artifacts_with_citations"] == 1.0
