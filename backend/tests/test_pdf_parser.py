from pathlib import Path

import fitz

from app.ingestion.pdf_parser import extract_pdf_text


def create_text_pdf(path: Path, text: str) -> None:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    document.save(path)
    document.close()


def create_blank_pdf(path: Path) -> None:
    document = fitz.open()
    document.new_page()
    document.save(path)
    document.close()


def test_pdf_parser_extracts_text_from_fixture_pdf(tmp_path: Path) -> None:
    pdf_path = tmp_path / "text.pdf"
    create_text_pdf(pdf_path, "Abstract This paper studies TTLAB publication discovery.")

    result = extract_pdf_text("paper-text", pdf_path, tmp_path / "extracted")

    assert result["extraction_status"] == "extracted"
    assert result["page_count"] == 1
    assert result["pages"][0]["word_count"] >= 6
    assert Path(result["full_text_path"]).exists()


def test_pdf_parser_handles_blank_no_text_pdf(tmp_path: Path) -> None:
    pdf_path = tmp_path / "blank.pdf"
    create_blank_pdf(pdf_path)

    result = extract_pdf_text("paper-blank", pdf_path, tmp_path / "extracted")

    assert result["extraction_status"] == "no_text"
    assert result["diagnostics"]["pages_without_text"] == 1
    assert result["diagnostics"]["possible_scanned_pdf"] is True
