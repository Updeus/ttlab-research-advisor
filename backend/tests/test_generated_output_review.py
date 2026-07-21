from __future__ import annotations

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.evaluation import generated_output_review as review_module
from app.evaluation.generated_output_review import (
    REVIEWER_ID,
    REVIEW_REQUEST_ID,
    apply_reviews,
    compatibility_report,
    disposable_idempotence,
    plan_reviews,
    review_recommendation,
)
from app.models import Chunk, Paper, PaperArtifact, RAGAnswer, ReviewEvent, ThesisRecommendation


def build_review_engine(database_url: str = "sqlite:///:memory:"):
    engine_kwargs = {"connect_args": {"check_same_thread": False}}
    if database_url == "sqlite:///:memory:":
        engine_kwargs["poolclass"] = StaticPool
    engine = create_engine(database_url, **engine_kwargs)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            Paper(
                paper_id="review-paper",
                title="Reviewed Source Paper",
                authors=["Asha Singh"],
                corpus_eligibility_status="eligible",
                pdf_text_status="extracted",
                pages_with_text=1,
                page_count=1,
            )
        )
        session.add(
            Chunk(
                chunk_id="current-chunk",
                paper_id="review-paper",
                chunk_index=0,
                page_start=1,
                page_end=1,
                section="Introduction",
                text="The paper presents a source-grounded method and evaluation for a research system.",
                source_hash="a" * 64,
            )
        )
        stale_citation = {
            "paper_id": "review-paper",
            "title": "Reviewed Source Paper",
            "chunk_id": "stale-chunk",
            "page_start": 1,
            "page_end": 1,
            "snippet": "Old source text",
        }
        session.add(
            RAGAnswer(
                answer_id="answer-one",
                question="What does the paper present?",
                answer="The paper presents a research system.",
                retrieved_chunk_ids=["stale-chunk"],
                cited_paper_ids=["review-paper"],
                citations_json=[stale_citation],
                retrieved_chunks_json=[{"chunk_id": "stale-chunk", "paper_id": "review-paper", "snippet": "Old source text"}],
                grounding_status="grounded",
            )
        )
        session.add(
            PaperArtifact(
                artifact_id="artifact-one",
                paper_id="review-paper",
                artifact_type="public_summary",
                generated_json={"text": "Old summary", "citations": [stale_citation]},
                generated_text="Old summary",
                source_chunk_ids_json=["stale-chunk"],
                citations_json=[stale_citation],
                grounding_status="grounded",
            )
        )
        session.commit()
    return engine


def fresh_recommendation_response() -> dict[str, object]:
    citation = {
        "paper_id": "review-paper",
        "title": "Reviewed Source Paper",
        "chunk_id": "current-chunk",
        "section": "Introduction",
        "page_start": 1,
        "page_end": 1,
        "snippet": "The paper presents a source-grounded method and evaluation for a research system.",
    }
    item = {
        "paper_id": "review-paper",
        "paper_focus": "A source-grounded research system.",
        "source_supported_facts": [{"claim": "The paper presents a method.", "chunk_id": "current-chunk"}],
        "identified_gap": {"text": "No explicit gap found.", "support_status": "not_found", "source_chunk_ids": ["current-chunk"]},
        "extension_summary": "Suggested extension; this is a student-project suggestion, not a verified claim from the paper.",
        "mvp_scope": "Build one small workflow.",
        "stretch_goals": ["Add evaluation."],
        "required_skills": ["Python"],
        "skills_gap": [],
        "data_required": "Synthetic data.",
        "data_availability": "synthetic",
        "evaluation_plan": "Compare a baseline.",
        "difficulty": "medium",
        "risk_level": "medium",
        "implementation_time": "semester",
        "citations": [citation],
        "potential_researcher_fit": [{"name": "Asha Singh", "reason": "Author of the source paper; not verified as a supervisor."}],
    }
    return {
        "recommendations": [item],
        "provider": "offline_deterministic",
        "model": "template-recommender-v1",
        "retrieval_mode": "hybrid",
        "top_k": 1,
        "grounding_status": "partial",
        "warnings": ["No explicit future-work statement found."],
    }


def test_compatibility_and_artifact_regeneration_are_source_current() -> None:
    engine = build_review_engine()
    assert compatibility_report(engine)["migration_required"] is False

    with Session(engine) as session:
        decisions = plan_reviews(session)

    by_type = {decision.item_type: decision for decision in decisions}
    assert by_type["rag_answer"].target_status == "needs_reprocess"
    assert "missing_chunk:stale-chunk" in by_type["rag_answer"].rationale
    assert by_type["paper_artifact"].target_status == "ai_reviewed"
    assert by_type["paper_artifact"].checks["regenerated_with_current_deterministic_pipeline"] is True
    assert {item["chunk_id"] for item in by_type["paper_artifact"].evidence} == {"current-chunk"}


def test_apply_is_idempotent_and_events_are_ai_attributed_and_evidence_linked() -> None:
    engine = build_review_engine()
    with Session(engine) as session:
        decisions = plan_reviews(session)
        first = apply_reviews(session, decisions)
        second = apply_reviews(session, decisions)
        events = session.exec(select(ReviewEvent).order_by(ReviewEvent.created_at)).all()
        answer = session.get(RAGAnswer, "answer-one")
        artifact = session.get(PaperArtifact, "artifact-one")

    assert first["created_events"] == 2
    assert first["review_event_integrity"]["status"] == "verified"
    assert second["created_events"] == 0
    assert second["changed_records"] == 0
    assert len(events) == 2
    assert all(event.reviewer_id == REVIEWER_ID for event in events)
    assert all(event.reviewer_type == "ai" for event in events)
    assert all(event.request_id == REVIEW_REQUEST_ID for event in events)
    assert all(event.diff_json["review"]["evidence"] for event in events)
    assert answer is not None and answer.review_status == "needs_reprocess"
    assert answer.grounding_status == "unsupported"
    assert artifact is not None and artifact.review_status == "ai_reviewed"
    assert artifact.source_chunk_ids_json == ["current-chunk"]


def test_disposable_proof_reuses_preexisting_version_events(tmp_path) -> None:
    database = tmp_path / "already-reviewed.db"
    engine = build_review_engine(f"sqlite:///{database}")
    with Session(engine) as session:
        decisions = plan_reviews(session)
        initial = apply_reviews(session, decisions)

    proof = disposable_idempotence(database)

    assert initial["created_events"] == 2
    assert proof["status"] == "PASS"
    assert proof["preexisting_version_events"] == 2
    assert proof["first_pass"]["created_events"] == 0
    assert proof["first_pass"]["changed_records"] == 0
    assert proof["first_pass"]["skipped_existing"] == 2
    assert proof["second_pass"]["skipped_existing"] == 2


def test_changed_payload_creates_a_fresh_append_only_review_event() -> None:
    engine = build_review_engine()
    with Session(engine) as session:
        initial = apply_reviews(session, plan_reviews(session))
        answer = session.get(RAGAnswer, "answer-one")
        assert answer is not None
        answer.answer = "The generated payload changed after the earlier AI review."
        answer.review_status = "needs_review"
        answer.reviewed_by = None
        answer.reviewed_at = None
        session.add(answer)
        session.commit()

        refreshed = apply_reviews(session, plan_reviews(session))
        events = session.exec(
            select(ReviewEvent)
            .where(ReviewEvent.item_type == "rag_answer")
            .where(ReviewEvent.item_id == "answer-one")
            .order_by(ReviewEvent.created_at)
        ).all()

    assert initial["created_events"] == 2
    assert refreshed["created_events"] == 1
    assert refreshed["skipped_existing"] == 1
    assert len(events) == 2
    assert events[0].event_hash != events[1].event_hash
    assert events[1].previous_event_hash == events[0].event_hash or events[1].previous_event_hash is not None


def test_recommendation_is_regenerated_and_ai_reviewed_when_boundaries_hold(monkeypatch) -> None:
    engine = build_review_engine()
    with Session(engine) as session:
        session.add(
            ThesisRecommendation(
                recommendation_id="recommendation-one",
                request_json={
                    "interests": "research systems",
                    "skills": ["Python"],
                    "available_time": "semester",
                    "project_type": "software prototype",
                    "data_constraints": "synthetic",
                    "preferred_difficulty": "medium",
                    "top_k": 1,
                    "retrieval_mode": "hybrid",
                    "provider": "offline_deterministic",
                },
                available_time="semester",
                project_type="software prototype",
                preferred_difficulty="medium",
                recommendations_json=[],
            )
        )
        session.commit()
        monkeypatch.setattr(
            review_module,
            "recommend_extensions",
            lambda *args, **kwargs: fresh_recommendation_response(),
        )
        record = session.get(ThesisRecommendation, "recommendation-one")
        assert record is not None
        decision = review_recommendation(session, record)

    assert decision.target_status == "ai_reviewed"
    assert decision.checks["regenerated_with_current_deterministic_pipeline"] is True
    assert decision.checks["schema_errors"] == []
    assert {item["chunk_id"] for item in decision.evidence} == {"current-chunk"}


def test_sanitized_review_corrections_do_not_redistribute_generated_payload() -> None:
    engine = build_review_engine()
    with Session(engine) as session:
        artifact_decision = next(item for item in plan_reviews(session) if item.item_type == "paper_artifact")
    sanitized = artifact_decision.sanitized()

    assert sanitized["corrections"]
    assert all("after" not in correction and "before" not in correction for correction in sanitized["corrections"])
    assert all(len(correction["after_sha256"]) == 64 for correction in sanitized["corrections"])
    assert sanitized["human_validation"] is False
