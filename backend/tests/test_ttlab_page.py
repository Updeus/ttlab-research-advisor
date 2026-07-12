from pathlib import Path

from app.ingestion.ttlab_page import looks_like_author_line, parse_publications_from_html, parse_year, split_authors


FIXTURE = Path(__file__).parent / "fixtures" / "ttlab_archive.html"


def test_parser_extracts_publication_fields_and_links() -> None:
    html = FIXTURE.read_text(encoding="utf-8")
    records, next_url = parse_publications_from_html(html, "https://lab.tt/index.php/category/pub/")

    assert next_url == "https://lab.tt/index.php/category/pub/page/2/"
    assert len(records) == 3

    direct_pdf = records[0]
    assert direct_pdf["title"] == "Direct PDF Research Paper"
    assert direct_pdf["authors"] == ["Asha Singh", "Ben Lee", "Patrick Hosein"]
    assert direct_pdf["venue"] == "International Conference on Useful Systems"
    assert direct_pdf["year"] == 2026
    assert direct_pdf["pdf_url"] == "https://lab.tt/wp-content/uploads/2026/01/direct-paper.pdf"
    assert direct_pdf["source_url"] is None
    assert direct_pdf["pdf_text_status"] == "not_extracted"


def test_parser_handles_external_source_without_pdf_and_deduplicates_title() -> None:
    html = FIXTURE.read_text(encoding="utf-8")
    records, _next_url = parse_publications_from_html(html, "https://lab.tt/index.php/category/pub/")
    doi_only = records[1]

    assert doi_only["title"] == "DOI Only Paper"
    assert doi_only["source_url"] == "https://doi.org/10.1000/example"
    assert doi_only["pdf_url"] is None
    assert doi_only["pdf_text_status"] == "missing_pdf"
    assert [record["title"] for record in records].count("DOI Only Paper") == 1


def test_parser_handles_malformed_split_year() -> None:
    assert parse_year("March, 202 6") == 2026
    assert parse_year("March, 202") is None


def test_parser_preserves_audit_urls() -> None:
    html = FIXTURE.read_text(encoding="utf-8")
    records, _next_url = parse_publications_from_html(html, "https://lab.tt/index.php/category/pub/")

    malformed = records[2]
    assert malformed["publication_date_raw"] == "March, 202 6"
    assert "https://publisher.example/paper" in malformed["all_urls"]
    assert malformed["review_status"] == "needs_review"


def test_action_link_text_is_never_treated_as_an_author() -> None:
    assert looks_like_author_line("Click to View") is False
    assert split_authors("Click to View") == []
