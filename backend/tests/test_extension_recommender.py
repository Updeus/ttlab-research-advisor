from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.db import get_session
from app.evaluation.extension_eval import citation_coverage_percentage, evaluate_case
from app.indexing.keyword_search import rebuild_keyword_index
from app.indexing.chunker import canonical_chunks_sha256, db_chunk_payload
from app.intelligence import extension_recommender as extension_recommender_module
from app.intelligence.extension_recommender import (
    SCORE_WEIGHTS,
    ExtensionFinderRequest,
    build_retrieval_query,
    evidence_only_baseline,
    group_results_by_paper,
    identify_gap,
    matches_avoid_topic,
    recommendation_diagnostics,
    recommend_extensions,
    validated_score_weights,
)
from app.intelligence.recommendation_verifier import verify_recommendations
from app.main import app
from app.models import Chunk, Paper, ThesisRecommendation

EXTRACTION_GENERATION = "a" * 64
CHUNK_GENERATION = "b" * 64


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
            corpus_eligibility_status="eligible",
            review_status="approved",
            extraction_review_status="approved",
            publication_status="published",
            rights_status="cleared",
            public_access_level="searchable",
            extraction_generation_id=EXTRACTION_GENERATION,
            chunk_extraction_generation_id=EXTRACTION_GENERATION,
            chunk_generation_id=CHUNK_GENERATION,
            public_index_generation_id=CHUNK_GENERATION,
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
            corpus_eligibility_status="eligible",
            review_status="approved",
            extraction_review_status="approved",
            publication_status="published",
            rights_status="cleared",
            public_access_level="searchable",
            extraction_generation_id=EXTRACTION_GENERATION,
            chunk_extraction_generation_id=EXTRACTION_GENERATION,
            chunk_generation_id=CHUNK_GENERATION,
            public_index_generation_id=CHUNK_GENERATION,
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
            extraction_generation_id=EXTRACTION_GENERATION,
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
            extraction_generation_id=EXTRACTION_GENERATION,
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
            extraction_generation_id=EXTRACTION_GENERATION,
        )
    )
    session.flush()
    for paper_id in ("rag-platform", "traffic-dashboard"):
        chunks = list(session.exec(select(Chunk).where(Chunk.paper_id == paper_id)).all())
        generation_id = canonical_chunks_sha256(db_chunk_payload(chunks))
        paper = session.get(Paper, paper_id)
        assert paper is not None
        paper.chunk_generation_id = generation_id
        paper.public_index_generation_id = generation_id
        session.add(paper)
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


def test_evidence_only_baseline_returns_ranked_papers_and_passages() -> None:
    session, _engine = build_extension_session()
    try:
        baseline = evidence_only_baseline(session, extension_request())
    finally:
        session.close()

    assert baseline["output_mode"] == "evidence_only"
    assert baseline["papers"][0]["paper_id"] == "rag-platform"
    assert baseline["papers"][0]["passages"][0]["chunk_id"].startswith("rag-platform")
    assert "does not propose" in baseline["disclaimer"]


def test_retrieval_query_is_topic_focused_not_padded_with_generic_constraints() -> None:
    request = extension_request()
    query = build_retrieval_query(request)

    assert "RAG" in query
    assert "research discovery" in query
    assert request.project_type not in query
    assert request.data_constraints not in query
    assert "future work limitations" not in query


def test_recommendation_weights_are_validated_normalized_and_changeable() -> None:
    assert validated_score_weights() == SCORE_WEIGHTS
    normalized = validated_score_weights({**SCORE_WEIGHTS, "retrieval_relevance": 0.6})
    assert sum(normalized.values()) == pytest.approx(1.0)
    assert normalized["retrieval_relevance"] > SCORE_WEIGHTS["retrieval_relevance"]
    with pytest.raises(ValueError):
        validated_score_weights({"retrieval_relevance": 1.0})


def test_gap_detection_uses_conservative_source_phrase_and_inference_labels() -> None:
    source_phrase = identify_gap(
        [
            {
                "chunk_id": "c1",
                "section": "Conclusion",
                "snippet": "A dataset is described first. We identify as future work evaluation on a broader sample.",
            }
        ]
    )
    inferred = identify_gap(
        [
            {
                "chunk_id": "c2",
                "section": "Discussion",
                "snippet": "We believe performance can improve with a larger dataset.",
            }
        ]
    )
    generic = identify_gap(
        [
            {
                "chunk_id": "c3",
                "section": "Methodology",
                "snippet": "The dataset supports evaluation of the proposed model.",
            }
        ]
    )
    unattributed_phrase = identify_gap(
        [
            {
                "chunk_id": "c4",
                "section": "Conclusion",
                "snippet": "A dataset is described first. Future work should evaluate a broader sample.",
            }
        ]
    )

    assert source_phrase["support_status"] == "source_phrase_unverified"
    assert source_phrase["text"].endswith("We identify as future work evaluation on a broader sample.")
    assert inferred["support_status"] == "inferred_from_paper"
    assert inferred["text"].startswith("Inferred extension opening")
    assert unattributed_phrase["support_status"] == "inferred_from_paper"
    assert "explicit_in_paper" not in {
        source_phrase["support_status"],
        inferred["support_status"],
        unattributed_phrase["support_status"],
    }
    assert generic["support_status"] == "not_found"


def test_gap_detection_ignores_related_work_and_negated_future_work_phrases() -> None:
    related_work = identify_gap(
        [
            {
                "chunk_id": "related",
                "section": "Related Work",
                "snippet": "Prior authors state that future work should use a larger dataset.",
            }
        ]
    )
    negated = identify_gap(
        [
            {
                "chunk_id": "negated",
                "section": "Conclusion",
                "snippet": "We do not identify future work as a limitation of this completed benchmark.",
            }
        ]
    )

    assert related_work["support_status"] == "not_found"
    assert related_work["source_chunk_ids"] == []
    assert negated["support_status"] == "not_found"
    assert negated["source_chunk_ids"] == []


def test_multiword_avoid_topic_does_not_penalize_one_generic_token() -> None:
    assert not matches_avoid_topic("A public synthetic time-series dataset", ["private datasets"])
    assert matches_avoid_topic("A private collection of datasets", ["private datasets"])
    assert matches_avoid_topic("Deep neural learning architecture", ["deep learning"])


def test_recommendation_diagnostics_exclude_ineligible_paper_chunks() -> None:
    session, _engine = build_extension_session()
    try:
        session.add(
            Paper(
                paper_id="excluded-pdf",
                title="Mismatched PDF",
                corpus_eligibility_status="excluded_pdf_metadata_mismatch",
            )
        )
        session.add(Chunk(chunk_id="excluded-0001", paper_id="excluded-pdf", text="not searchable"))
        session.commit()
        diagnostics = recommendation_diagnostics(session)
    finally:
        session.close()

    assert diagnostics["searchable_chunks"] == 3
    assert diagnostics["searchable_papers"] == 2
    # Public diagnostics intentionally do not disclose the hidden technical
    # corpus size; only the publishable projection is countable anonymously.
    assert diagnostics["raw_chunks"] is None
    assert diagnostics["raw_papers_with_chunks"] is None


def test_demo_recommendation_diagnostics_use_technical_corpus() -> None:
    session, _engine = build_extension_session()
    try:
        hidden = session.get(Paper, "rag-platform")
        assert hidden is not None
        hidden.review_status = "needs_review"
        hidden.publication_status = "hidden"
        session.add(hidden)
        session.commit()

        public_diagnostics = recommendation_diagnostics(session)
        demo_diagnostics = recommendation_diagnostics(session, demo_preview=True)
    finally:
        session.close()

    assert public_diagnostics["searchable_papers"] == 1
    assert demo_diagnostics["searchable_papers"] == 2
    assert demo_diagnostics["searchable_chunks"] == 3
    assert demo_diagnostics["demo_preview"] is True
    assert demo_diagnostics["scope"] == "technical_demo"


def test_recommender_returns_ranked_recommendations_with_citations() -> None:
    session, _engine = build_extension_session()
    try:
        response = recommend_extensions(session, extension_request(), persist=True)
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


def test_finder_cli_requires_explicit_persistence_even_for_technical_scope(monkeypatch, capsys) -> None:
    defaults = extension_recommender_module.build_parser().parse_args(
        ["recommend", "--interests", "retrieval augmented generation"]
    )
    explicit = extension_recommender_module.build_parser().parse_args(
        [
            "recommend",
            "--interests",
            "retrieval augmented generation",
            "--scope",
            "technical",
            "--persist",
        ]
    )
    assert defaults.scope == "public"
    assert defaults.persist is False
    assert explicit.scope == "technical"
    assert explicit.persist is True

    session, local_engine = build_extension_session()
    session.close()
    monkeypatch.setattr(extension_recommender_module, "engine", local_engine)
    monkeypatch.setattr(extension_recommender_module, "create_db_and_tables", lambda: None)
    monkeypatch.setattr(
        "sys.argv",
        [
            "extension_recommender",
            "recommend",
            "--interests",
            "retrieval augmented generation",
            "--scope",
            "technical",
        ],
    )

    extension_recommender_module.main()
    capsys.readouterr()
    with Session(local_engine) as verification_session:
        stored = list(verification_session.exec(select(ThesisRecommendation)).all())

    assert stored == []


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

    assert grounded["grounding_status"] == "partial"
    assert grounded["support_status"] == "support_unverified"
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
    assert fetched.status_code == 401
    assert history.status_code == 401
    assert diagnostics.status_code == 200
    assert diagnostics.json()["total_recommendation_runs"] is None
    assert diagnostics.json()["history_counts_visibility"] == "protected_reviewer_only"
    assert stats.status_code == 200
    assert "total_extension_recommendation_runs" not in stats.json()
    assert "total_extension_ideas" not in stats.json()


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
