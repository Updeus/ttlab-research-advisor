from pathlib import Path

import httpx

from app.config import Settings
from app.ingestion.pdf_downloader import (
    DownloadRecord,
    classify_http_unavailability,
    download_pdfs,
    verify_pdf_response,
)


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


def test_pdf_unavailability_http_taxonomy_is_deterministic() -> None:
    assert classify_http_unavailability(403) == "forbidden"
    assert classify_http_unavailability(404) == "not_found"
    assert classify_http_unavailability(410) == "not_found"
    assert classify_http_unavailability(401) == "permission_restricted"
    assert classify_http_unavailability(451) == "permission_restricted"
    assert classify_http_unavailability(503) == "network_error"


def test_pdf_downloader_counts_forbidden_and_invalid_pdf(tmp_path: Path) -> None:
    worker_settings = Settings(
        service_role="offline_worker",
        sync_execution_mode="offline_single_writer",
    )
    forbidden_client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(403, request=request)),
    )
    invalid_client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                headers={"content-type": "application/pdf"},
                content=b"not-pdf",
                request=request,
            )
        )
    )
    try:
        forbidden = download_pdfs(
            [DownloadRecord(paper_id="forbidden", pdf_url="https://example.test/forbidden.pdf")],
            tmp_path,
            download=True,
            client=forbidden_client,
            allowed_hosts=["example.test"],
            resolver=lambda *_args, **_kwargs: ["93.184.216.34"],
            settings_override=worker_settings,
        )
        invalid = download_pdfs(
            [DownloadRecord(paper_id="invalid", pdf_url="https://example.test/invalid.pdf")],
            tmp_path,
            download=True,
            client=invalid_client,
            allowed_hosts=["example.test"],
            resolver=lambda *_args, **_kwargs: ["93.184.216.34"],
            settings_override=worker_settings,
        )
    finally:
        forbidden_client.close()
        invalid_client.close()

    assert forbidden["forbidden"] == 1
    assert forbidden["failed"] == 1
    assert invalid["invalid_pdf"] == 1
