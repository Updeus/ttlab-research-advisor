from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.api.admin_control import (
    BulkExecuteRequest,
    BulkPreviewRequest,
    execute_bulk,
    preview_bulk,
)
from app.models import Paper, RAGAnswer
from app.security import AuthenticatedActor


def test_catch_all_approves_everything_except_missing_pdf_papers() -> None:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    actor = AuthenticatedActor(
        actor_id="admin-test",
        display_name="Admin Test",
        role="admin",
        reviewer_type="human",
        request_id="catch-all-test",
    )

    with Session(engine) as session:
        session.add(
            Paper(
                paper_id="has-pdf",
                title="",
                authors=[],
                pdf_text_status="not_extracted",
            )
        )
        session.add(
            Paper(
                paper_id="missing-pdf",
                title="Missing PDF Paper",
                authors=["A. Author"],
                pdf_text_status="missing_pdf",
            )
        )
        session.add(
            RAGAnswer(
                answer_id="unsupported-answer",
                question="Question",
                answer="Uncited answer",
                grounding_status="unsupported",
                citations_json=[],
            )
        )
        session.commit()

        preview = preview_bulk(
            BulkPreviewRequest(
                approval_mode="catch_all",
                item_types=["papers", "extractions", "answers"],
            ),
            session,
            actor,
        )

        assert preview["approval_mode"] == "catch_all"
        assert {
            (item["item_type"], item["item_id"])
            for item in preview["blocked"]
        } == {("paper", "missing-pdf"), ("extraction", "missing-pdf")}
        assert all(item["blockers"] == ["missing_pdf"] for item in preview["blocked"])

        result = execute_bulk(
            BulkExecuteRequest(
                operation_id=str(preview["operation_id"]),
                preview_hash=str(preview["preview_hash"]),
            ),
            session,
            actor,
        )

        has_pdf = session.get(Paper, "has-pdf")
        missing_pdf = session.get(Paper, "missing-pdf")
        answer = session.get(RAGAnswer, "unsupported-answer")
        assert has_pdf is not None and has_pdf.review_status == "approved"
        assert has_pdf.extraction_review_status == "approved"
        assert missing_pdf is not None and missing_pdf.review_status == "needs_review"
        assert missing_pdf.extraction_review_status == "needs_review"
        assert answer is not None and answer.review_status == "approved"
        assert result["approved_count"] == 3
