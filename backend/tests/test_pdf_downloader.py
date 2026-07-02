from pathlib import Path

import httpx

from app.ingestion.pdf_downloader import DownloadRecord, download_pdfs, verify_pdf_response


def test_pdf_downloader_dry_run_does_not_save_files(tmp_path: Path) -> None:
    records = [DownloadRecord(paper_id="paper-one", pdf_url="https://lab.tt/example.pdf")]

    summary = download_pdfs(records, tmp_path, download=False)

    assert summary["attempted"] == 1
    assert summary["downloaded"] == 0
    assert not (tmp_path / "paper-one.pdf").exists()


def test_pdf_downloader_verifies_pdf_signature() -> None:
    valid = httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF-1.7\nbody")
    invalid = httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"<html>not pdf</html>")

    assert verify_pdf_response(valid) is True
    assert verify_pdf_response(invalid) is False
