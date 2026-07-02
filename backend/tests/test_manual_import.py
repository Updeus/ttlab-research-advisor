from sqlmodel import Session, SQLModel, create_engine, select

from app.ingestion.manual_import import upsert_papers
from app.models import Author, Paper


def test_manual_import_upserts_papers_and_authors() -> None:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    records = [
        {
            "paper_id": "paper-one",
            "title": "Paper One",
            "authors": ["Asha Singh", "Patrick Hosein"],
            "year": 2026,
            "publication_date_raw": "Jan, 2026",
            "venue": "Test Conference",
            "source_url": "https://doi.org/10.1000/example",
            "pdf_url": None,
            "topics": [],
            "all_urls": ["https://doi.org/10.1000/example"],
            "ingestion_status": "discovered",
            "pdf_text_status": "missing_pdf",
            "review_status": "needs_review",
        }
    ]

    with Session(engine) as session:
        summary = upsert_papers(session, records)
        paper = session.get(Paper, "paper-one")
        authors = list(session.exec(select(Author)).all())

    assert summary["created"] == 1
    assert summary["missing_pdf"] == 1
    assert paper is not None
    assert paper.review_status == "needs_review"
    assert paper.authors == ["Asha Singh", "Patrick Hosein"]
    assert {author.name for author in authors} == {"Asha Singh", "Patrick Hosein"}
