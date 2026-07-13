from __future__ import annotations

from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, func, select

from app.db import get_session
from app.demo import prepare_demo as prepare_demo_module
from app.demo.smoke_check import run_smoke_check
from app.intelligence.topic_explorer import author_detail, get_related_papers, normalize_topic, rebuild_topic_index
from app.main import app
from app.models import Author, AuthorTopic, Chunk, Paper, PaperArtifact, PaperTopic, Topic


def build_explorer_engine(*, reviewed: bool = False):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Author(name="Asha Singh", review_status="needs_review"))
        session.add(Author(name="Ben Lee", review_status="needs_review"))
        session.add(Author(name="Cara Jones", review_status="needs_review"))
        session.add(
            Paper(
                paper_id="rag-paper",
                title="Retrieval Augmented Generation for Research Discovery",
                authors=["Asha Singh", "Ben Lee"],
                year=2025,
                venue="TTLAB Demo",
                topics=["RAG"],
                review_status="approved" if reviewed else "needs_review",
                pdf_text_status="extracted",
                corpus_eligibility_status="eligible",
            )
        )
        session.add(
            Paper(
                paper_id="related-paper",
                title="RAG Web Application for Academic Discovery",
                authors=["Asha Singh", "Cara Jones"],
                year=2024,
                venue="TTLAB Demo",
                topics=["retrieval augmented generation", "web applications"],
                pdf_text_status="extracted",
                corpus_eligibility_status="eligible",
            )
        )
        session.add(
            Paper(
                paper_id="mobile-paper",
                title="Optimisation of Mobile Network Pricing",
                authors=["Dev Patel"],
                year=2023,
                topics=["optimisation"],
                pdf_text_status="extracted",
                corpus_eligibility_status="eligible",
            )
        )
        session.add(
            Chunk(
                chunk_id="rag-chunk",
                paper_id="rag-paper",
                chunk_index=0,
                section="Abstract",
                text="Retrieval augmented generation and information retrieval help students inspect cited research evidence.",
            )
        )
        session.add(
            Chunk(
                chunk_id="related-chunk",
                paper_id="related-paper",
                chunk_index=0,
                section="Methodology",
                text="The web application uses RAG, search, and a dashboard for academic discovery.",
            )
        )
        session.add(
            PaperArtifact(
                artifact_id="artifact-rag",
                paper_id="rag-paper",
                artifact_type="required_skills",
                generated_json={"skills": ["Python", "information retrieval", "web application development"]},
                generated_text="Required skills include Python and information retrieval.",
                generation_status="generated",
            )
        )
        session.commit()
    return engine


def make_override(engine):
    def override_session() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session

    return override_session


def test_topic_normalization_merges_synonyms() -> None:
    assert normalize_topic("Retrieval Augmented Generation") == ("rag", "RAG")
    assert normalize_topic("rag") == ("rag", "RAG")
    assert normalize_topic("optimisation") == ("optimization", "Optimization")
    assert normalize_topic("Artificial Intelligence") == ("ai", "AI")


def test_topic_rebuild_creates_topics_from_publication_metadata_and_chunks_only() -> None:
    engine = build_explorer_engine()
    with Session(engine) as session:
        summary = rebuild_topic_index(session)
        rag = session.get(Topic, "rag")
        paper_links = session.exec(select(PaperTopic).where(PaperTopic.paper_id == "rag-paper")).all()

    assert summary["topics_created"] >= 3
    assert rag is not None
    assert any(link.topic_id == "rag" for link in paper_links)
    assert any(any(evidence["source"] == "chunk_text" for evidence in link.evidence_json) for link in paper_links)
    assert not any(
        evidence["source"].startswith("artifact:")
        for link in paper_links
        for evidence in link.evidence_json
    )


def test_topic_rebuild_excludes_ineligible_papers_and_generated_artifact_topics() -> None:
    engine = build_explorer_engine()
    with Session(engine) as session:
        session.add(
            Paper(
                paper_id="excluded-paper",
                title="Cybersecurity and Fraud Detection",
                authors=["Asha Singh"],
                corpus_eligibility_status="excluded_pdf_metadata_mismatch",
                pdf_text_status="extracted",
            )
        )
        session.add(
            Chunk(
                chunk_id="excluded-chunk",
                paper_id="excluded-paper",
                chunk_index=0,
                section="Introduction",
                text="Cybersecurity fraud detection is the subject of this mismatched PDF.",
            )
        )
        session.add(
            PaperArtifact(
                artifact_id="artifact-only-topic",
                paper_id="mobile-paper",
                artifact_type="summary",
                generated_text="This generated text claims cybersecurity and climate expertise.",
                generated_json={"summary": "Cybersecurity and climate"},
                generation_status="generated",
            )
        )
        session.commit()

        rebuild_topic_index(session)
        excluded_links = session.exec(
            select(PaperTopic).where(PaperTopic.paper_id == "excluded-paper")
        ).all()
        artifact_only_links = {
            link.topic_id
            for link in session.exec(select(PaperTopic).where(PaperTopic.paper_id == "mobile-paper")).all()
        }
        author = session.exec(select(Author).where(Author.name == "Asha Singh")).one()
        author_output = author_detail(session, author.id or -1)
        assert author.paper_count == 2

    assert excluded_links == []
    assert "cybersecurity" not in artifact_only_links
    assert "climate" not in artifact_only_links
    assert author_output is not None
    assert len(author_output["papers"]) == 2
    assert "bibliographic evidence only" in author_output["potential_expertise_summary"]
    assert "availability" in author_output["potential_expertise_summary"]
    assert get_related_papers_from_engine(engine, "excluded-paper") == []


def get_related_papers_from_engine(engine, paper_id: str) -> list[dict[str, object]]:
    with Session(engine) as session:
        return get_related_papers(session, paper_id)


def test_reviewed_manual_topics_are_not_overwritten_by_inferred_topics() -> None:
    engine = build_explorer_engine(reviewed=True)
    with Session(engine) as session:
        paper = session.get(Paper, "rag-paper")
        assert paper is not None
        paper.topics = ["Manual Topic"]
        session.add(paper)
        session.commit()
        rebuild_topic_index(session)
        linked_topic_ids = {
            link.topic_id
            for link in session.exec(select(PaperTopic).where(PaperTopic.paper_id == "rag-paper")).all()
        }

    assert linked_topic_ids == {"manual-topic"}


def test_author_topic_aggregation_and_related_paper_reasons_work() -> None:
    engine = build_explorer_engine()
    with Session(engine) as session:
        rebuild_topic_index(session)
        author_links = session.exec(select(AuthorTopic)).all()
        related = get_related_papers(session, "rag-paper", limit=5)

    assert author_links
    assert related
    assert related[0]["paper_id"] == "related-paper"
    assert "shared author" in related[0]["reason"]
    assert "shared topic" in related[0]["reason"]


def test_explorer_api_endpoints_and_stats_work() -> None:
    engine = build_explorer_engine()
    with Session(engine) as session:
        rebuild_topic_index(session)

    app.dependency_overrides[get_session] = make_override(engine)
    try:
        client = TestClient(app)
        overview = client.get("/api/explorer/overview")
        topics = client.get("/api/topics")
        topic_detail = client.get("/api/topics/rag")
        authors = client.get("/api/authors")
        author_id = authors.json()["items"][0]["author_id"]
        author_detail = client.get(f"/api/authors/{author_id}")
        related = client.get("/api/papers/rag-paper/related")
        stats = client.get("/api/stats")
    finally:
        app.dependency_overrides.clear()

    assert overview.status_code == 200
    assert overview.json()["explorer_index_status"] == "ready"
    assert topics.status_code == 200
    assert topics.json()["items"]
    assert topic_detail.status_code == 200
    assert topic_detail.json()["papers"]
    assert authors.status_code == 200
    assert author_detail.status_code == 200
    assert author_detail.json()["papers"]
    assert related.status_code == 200
    assert stats.status_code == 200
    assert stats.json()["topic_count"] >= 1
    assert stats.json()["paper_topic_links"] >= 1


def test_demo_prepare_helper_is_idempotent_in_skip_mode(monkeypatch) -> None:
    engine = build_explorer_engine()
    monkeypatch.setattr(prepare_demo_module, "index_chunks", lambda *args, **kwargs: {"indexed_chunks": 0})
    with Session(engine) as session:
        first = prepare_demo_module.prepare_demo(session=session, limit=1, skip_downloads=True, skip_artifacts=True)
        second = prepare_demo_module.prepare_demo(session=session, limit=1, skip_downloads=True, skip_artifacts=True)
        topic_count = session.exec(select(func.count()).select_from(Topic)).one()

    assert first["download"]["skipped"] == "skip_downloads requested"
    assert second["download"]["skipped"] == "skip_downloads requested"
    assert first["demo_summary"]["papers_imported"] == 3
    assert second["demo_summary"]["topics"] >= 1
    assert "frontend" in first["routes"]
    assert topic_count >= 1


def test_smoke_check_returns_structured_status_without_network() -> None:
    engine = build_explorer_engine()
    with Session(engine) as session:
        rebuild_topic_index(session)

    app.dependency_overrides[get_session] = make_override(engine)
    try:
        client = TestClient(app)
        result = run_smoke_check(client)
    finally:
        app.dependency_overrides.clear()

    # This isolated test database deliberately has no matching authoritative
    # retrieval indexes. The smoke checker must expose that state instead of
    # treating any unrelated on-disk index as ready.
    assert result["overall_status"] == "FAIL"
    assert result["counts"]["fail"] >= 1
    assert any(check["name"] == "stats" and check["level"] == "PASS" for check in result["checks"])
    assert any(
        check["name"] == "feature_hashing_index" and check["level"] == "FAIL"
        for check in result["checks"]
    )
    assert result["summary"]["papers"] == 3
    assert result["summary"]["topics"] >= 1
