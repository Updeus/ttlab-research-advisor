from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.api.admin import (
    AuthorCorrectionRequest,
    GraphReviewRequest,
    PaperPatchRequest,
    author_queue_items,
    patch_paper,
    review_author,
    review_author_alias,
    review_author_topic,
    review_paper_topic,
    review_topic,
    save_author_correction,
)
from app.indexing.chunker import canonical_chunks_sha256, db_chunk_payload
from app.intelligence.topic_explorer import author_detail, list_topics
from app.models import (
    Author,
    AuthorAlias,
    AuthorTopic,
    Chunk,
    Paper,
    PaperArtifact,
    PaperTopic,
    RAGAnswer,
    ThesisRecommendation,
    Topic,
)
from app.security import AuthenticatedActor


HUMAN_ADMIN = AuthenticatedActor(
    actor_id="human-admin",
    display_name="Human Administrator",
    role="admin",
    reviewer_type="human",
    request_id="graph-review-test",
)

AI_ADMIN = AuthenticatedActor(
    actor_id="ai-reviewer",
    display_name="AI Reviewer",
    role="admin",
    reviewer_type="ai",
    request_id="graph-review-test-ai",
)
EXTRACTION_GENERATION = "a" * 64
CHUNK_GENERATION = "b" * 64


def build_graph_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        author = Author(
            name="A. Researcher",
            canonical_name="A. Researcher",
            normalized_name="a researcher",
            review_status="needs_review",
            identity_status="unresolved",
            identity_review_status="needs_review",
            paper_count=1,
        )
        session.add(author)
        session.flush()
        assert author.id is not None
        session.add(
            AuthorAlias(
                alias_id="alias-a",
                canonical_author_id=author.id,
                alias="A. Researcher",
                normalized_alias="a researcher",
                review_status="needs_review",
            )
        )
        session.add(
            Paper(
                paper_id="paper-a",
                title="Grounded RAG Systems",
                authors=["A. Researcher"],
                topics=["RAG"],
                review_status="approved",
                extraction_review_status="approved",
                publication_status="published",
                rights_status="cleared",
                public_access_level="searchable",
                corpus_eligibility_status="eligible",
                pdf_text_status="extracted",
                extraction_generation_id=EXTRACTION_GENERATION,
                chunk_extraction_generation_id=EXTRACTION_GENERATION,
                chunk_generation_id=CHUNK_GENERATION,
                public_index_generation_id=CHUNK_GENERATION,
                chunk_count=1,
            )
        )
        session.add(
            Chunk(
                chunk_id="paper-a-chunk",
                paper_id="paper-a",
                chunk_index=0,
                section="Abstract",
                text="Grounded retrieval augmented generation systems use cited source evidence.",
                extraction_generation_id=EXTRACTION_GENERATION,
            )
        )
        session.add(
            Topic(
                topic_id="rag",
                name="RAG",
                normalized_name="rag",
                review_status="needs_review",
            )
        )
        session.add(
            PaperTopic(
                link_id="paper-a:rag",
                paper_id="paper-a",
                topic_id="rag",
                score=2.0,
                evidence_json=[{"paper_id": "paper-a", "source": "paper_topics"}],
                review_status="needs_review",
            )
        )
        session.add(
            AuthorTopic(
                link_id=f"{author.id}:rag",
                author_id=author.id,
                topic_id="rag",
                paper_count=1,
                score=2.0,
                evidence_json=[{"paper_id": "paper-a", "source": "paper_topic_link"}],
                review_status="approved",
            )
        )
        session.flush()
        paper = session.get(Paper, "paper-a")
        assert paper is not None
        chunks = list(session.exec(select(Chunk).where(Chunk.paper_id == "paper-a")).all())
        generation_id = canonical_chunks_sha256(db_chunk_payload(chunks))
        paper.chunk_generation_id = generation_id
        paper.public_index_generation_id = generation_id
        session.add(paper)
        session.commit()
    return engine


def test_author_queue_reports_machine_readable_approval_blockers() -> None:
    engine = build_graph_engine()
    with Session(engine) as session:
        item = author_queue_items(session, "needs_review")[0]

    assert item["approval_blockers"] == ["identity_unresolved_or_ambiguous"]
    assert item["details"]["approval_blockers"] == ["identity_unresolved_or_ambiguous"]
    assert item["details"]["dependencies"] == {}


def test_only_human_admin_can_approve_and_unresolved_author_fails_closed() -> None:
    engine = build_graph_engine()
    with Session(engine) as session:
        author = session.exec(select(Author)).one()
        assert author.id is not None
        with pytest.raises(HTTPException) as ai_error:
            review_author(author.id, GraphReviewRequest(review_status="approved"), session, AI_ADMIN)
        with pytest.raises(HTTPException) as unresolved_error:
            review_author(author.id, GraphReviewRequest(review_status="approved"), session, HUMAN_ADMIN)

    assert ai_error.value.status_code == 403
    assert unresolved_error.value.status_code == 409
    assert unresolved_error.value.detail["approval_blockers"] == ["identity_unresolved_or_ambiguous"]


def test_human_review_workflow_populates_public_explorer_only_after_all_approvals() -> None:
    engine = build_graph_engine()
    with Session(engine) as session:
        author = session.exec(select(Author)).one()
        assert author.id is not None
        correction = save_author_correction(
            author.id,
            AuthorCorrectionRequest(canonical_name="Asha Researcher", identity_status="resolved"),
            session,
            HUMAN_ADMIN,
        )
        assert correction["author"]["identity_review_status"] == "needs_review"
        assert session.get(AuthorTopic, f"{author.id}:rag").review_status == "needs_review"

        review_author(author.id, GraphReviewRequest(review_status="approved"), session, HUMAN_ADMIN)
        review_author_alias("alias-a", GraphReviewRequest(review_status="approved"), session, HUMAN_ADMIN)
        review_topic("rag", GraphReviewRequest(review_status="approved"), session, HUMAN_ADMIN)
        review_paper_topic("paper-a:rag", GraphReviewRequest(review_status="approved"), session, HUMAN_ADMIN)
        review_author_topic(f"{author.id}:rag", GraphReviewRequest(review_status="approved"), session, HUMAN_ADMIN)

        topics = list_topics(session)
        detail = author_detail(session, author.id)

    assert topics["total"] == 1
    assert topics["items"][0]["author_count"] == 1
    assert detail is not None
    assert detail["topics"][0]["topic_id"] == "rag"


def test_material_author_and_paper_corrections_reset_dependent_link_approvals() -> None:
    engine = build_graph_engine()
    with Session(engine) as session:
        author = session.exec(select(Author)).one()
        assert author.id is not None
        author.identity_status = "resolved"
        author.review_status = "approved"
        author.identity_review_status = "approved"
        topic = session.get(Topic, "rag")
        paper_link = session.get(PaperTopic, "paper-a:rag")
        author_link = session.get(AuthorTopic, f"{author.id}:rag")
        assert topic is not None and paper_link is not None and author_link is not None
        topic.review_status = "approved"
        paper_link.review_status = "approved"
        author_link.review_status = "approved"
        session.add(author)
        session.add(topic)
        session.add(paper_link)
        session.add(author_link)
        session.commit()

        save_author_correction(
            author.id,
            AuthorCorrectionRequest(canonical_name="Asha R. Researcher"),
            session,
            HUMAN_ADMIN,
        )
        assert session.get(AuthorTopic, author_link.link_id).review_status == "needs_review"

        author_link = session.get(AuthorTopic, author_link.link_id)
        author_link.review_status = "approved"
        session.add(author_link)
        session.add(
            PaperArtifact(
                artifact_id="artifact-a",
                paper_id="paper-a",
                artifact_type="public_summary",
                review_status="approved",
            )
        )
        session.add(
            RAGAnswer(
                answer_id="answer-a",
                question="What is RAG?",
                answer="Grounded answer.",
                cited_paper_ids=["paper-a"],
                citations_json=[{"paper_id": "paper-a", "chunk_id": "chunk-a"}],
                review_status="approved",
            )
        )
        session.add(
            ThesisRecommendation(
                recommendation_id="recommendation-a",
                request_json={"interests": "RAG"},
                available_time="semester",
                project_type="prototype",
                preferred_difficulty="medium",
                recommendations_json=[{"paper_id": "paper-a", "title": "Extension"}],
                review_status="approved",
            )
        )
        session.commit()
        patch_paper(
            "paper-a",
            PaperPatchRequest(title="Corrected Grounded RAG Systems"),
            session,
            HUMAN_ADMIN,
        )

        reset_paper_link = session.get(PaperTopic, paper_link.link_id)
        reset_author_link = session.get(AuthorTopic, author_link.link_id)
        reset_paper = session.get(Paper, "paper-a")
        reset_artifact = session.get(PaperArtifact, "artifact-a")
        reset_answer = session.get(RAGAnswer, "answer-a")
        reset_recommendation = session.get(ThesisRecommendation, "recommendation-a")

    assert reset_paper_link is not None and reset_paper_link.review_status == "needs_review"
    assert reset_author_link is not None and reset_author_link.review_status == "needs_review"
    assert reset_paper is not None and reset_paper.rights_status == "unknown"
    assert reset_artifact is not None and reset_artifact.review_status == "needs_reprocess"
    assert reset_answer is not None and reset_answer.review_status == "needs_reprocess"
    assert reset_recommendation is not None and reset_recommendation.review_status == "needs_reprocess"


def test_unapproved_topic_links_stay_hidden_on_public_bibliographic_authors() -> None:
    engine = build_graph_engine()
    with Session(engine) as session:
        author = session.exec(select(Author)).one()
        assert author.id is not None
        author.identity_status = "resolved"
        author.review_status = "reviewed"
        author.identity_review_status = "reviewed"
        topic = session.get(Topic, "rag")
        paper_link = session.get(PaperTopic, "paper-a:rag")
        author_link = session.get(AuthorTopic, f"{author.id}:rag")
        alias = session.get(AuthorAlias, "alias-a")
        assert topic is not None and paper_link is not None and author_link is not None and alias is not None
        for record in (topic, paper_link, author_link, alias):
            record.review_status = "reviewed"
            session.add(record)
        session.add(author)
        session.commit()

        topics = list_topics(session)
        detail = author_detail(session, author.id)

    assert topics["total"] == 0
    # Bibliographic identity cards are derived from already-public papers.
    # Their unapproved topic/alias links must remain private.
    assert detail is not None
    assert detail["topics"] == []
    assert detail["aliases"] == []
    assert detail["identity_review_status"] == "reviewed"


def test_non_source_metadata_correction_invalidates_generated_outputs_without_resetting_rights() -> None:
    engine = build_graph_engine()
    with Session(engine) as session:
        session.add(
            PaperArtifact(
                artifact_id="abstract-artifact",
                paper_id="paper-a",
                artifact_type="technical_summary",
                review_status="approved",
            )
        )
        session.commit()

        patch_paper(
            "paper-a",
            PaperPatchRequest(abstract="Corrected human-reviewed abstract."),
            session,
            HUMAN_ADMIN,
        )
        paper = session.get(Paper, "paper-a")
        artifact = session.get(PaperArtifact, "abstract-artifact")

    assert paper is not None and paper.rights_status == "cleared"
    assert paper.publication_status == "pending_review"
    assert paper.public_access_level == "hidden"
    assert artifact is not None and artifact.review_status == "needs_reprocess"
