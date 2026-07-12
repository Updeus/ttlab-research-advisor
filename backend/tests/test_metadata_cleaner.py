import json
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine, select

from app.ingestion.metadata_cleaner import audit_pdf_title_identities, repair_author_identities
from app.models import Author, AuthorAlias, Paper


def test_author_repair_recovers_click_to_view_from_source_paragraphs_idempotently() -> None:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Author(name="Click to View"))
        session.add(
            Paper(
                paper_id="trust-paper",
                title="A Trust Framework",
                authors=["Click to View"],
                venue="Shiva Ramoudith, Patrick Hosein",
                raw_record={
                    "raw_scraped": {
                        "paragraphs": [
                            "A Trust Framework",
                            "Click to View",
                            "Shiva Ramoudith, Patrick Hosein",
                            "Future of Information and Communication Conference",
                            "March, 2020",
                        ]
                    }
                },
            )
        )
        session.commit()

        first = repair_author_identities(session)
        paper = session.get(Paper, "trust-paper")
        second = repair_author_identities(session)
        click = session.exec(select(Author).where(Author.name == "Click to View")).one()
        aliases = list(session.exec(select(AuthorAlias)).all())
        paper_authors = list(paper.authors) if paper is not None else []
        paper_venue = paper.venue if paper is not None else None
        paper_author_source = paper.metadata_provenance["authors"]["source"] if paper is not None else None
        click_status = click.identity_status
        alias_names = {alias.alias for alias in aliases}

    assert paper is not None
    assert paper_authors == ["Shiva Ramoudith", "Patrick Hosein"]
    assert paper_venue == "Future of Information and Communication Conference"
    assert paper_author_source == "raw_record.raw_scraped.paragraphs"
    assert click_status == "invalid"
    assert first["source_backed_authors_recovered"] == 1
    assert second["source_backed_authors_recovered"] == 0
    assert alias_names >= {"Shiva Ramoudith", "Patrick Hosein"}


def test_author_repair_merges_only_exact_normalized_variants() -> None:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Author(name="P. Hosein"))
        session.add(Author(name="P Hosein"))
        session.add(Author(name="Patrick Hosein"))
        session.commit()

        summary = repair_author_identities(session)
        authors = list(session.exec(select(Author).order_by(Author.id)).all())

    abbreviated = [author for author in authors if author.normalized_name == "p hosein"]
    full = next(author for author in authors if author.normalized_name == "patrick hosein")
    assert summary["authors_merged"] == 1
    assert sorted(author.identity_status for author in abbreviated) == ["merged", "unresolved"]
    assert full.identity_status == "unresolved"


def test_pdf_title_audit_excludes_mismatch_idempotently(tmp_path: Path) -> None:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    mismatch_path = tmp_path / "mismatch.json"
    mismatch_path.write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "page_number": 1,
                        "text": "Soft-Churn Optimal Switching between Prepaid Data Subscriptions on smartphones " * 3,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    with Session(engine) as session:
        session.add(
            Paper(
                paper_id="vector-paper",
                title="Vector Search Performance Enhancements on Limited Memory Edge Devices",
                authors=["Asha Singh"],
                pdf_text_status="extracted",
                extracted_json_path=str(mismatch_path),
            )
        )
        session.commit()

        first = audit_pdf_title_identities(session)
        second = audit_pdf_title_identities(session)
        paper = session.get(Paper, "vector-paper")
        status = paper.corpus_eligibility_status if paper else None
        match_status = paper.pdf_title_match_status if paper else None

    assert first["possible_mismatch"] == 1
    assert second["possible_mismatch"] == 1
    assert first["excluded_paper_ids"] == ["vector-paper"]
    assert status == "excluded_pdf_metadata_mismatch"
    assert match_status == "possible_mismatch"
