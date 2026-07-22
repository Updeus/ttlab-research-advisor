from pathlib import Path

import fitz

from app.ingestion import pdf_parser as pdf_parser_module
from app.ingestion.ocr import OCRPageResult, tesseract_language_data_identity
from app.ingestion.pdf_parser import extract_pdf_text, title_match_diagnostic, title_match_diagnostic_pages


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


def create_image_pdf(path: Path, *, with_text: bool = False, substantial_text: bool = False) -> None:
    document = fitz.open()
    page = document.new_page()
    pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 120, 120), False)
    pixmap.clear_with(240)
    page.insert_image(fitz.Rect(72, 100, 300, 328), stream=pixmap.tobytes("png"))
    if with_text:
        text = "Methods Native text accompanies a page image for review."
        if substantial_text:
            text = " ".join(["Methods and results provide substantial native scientific text alongside a normal figure."] * 4)
        page.insert_textbox(fitz.Rect(72, 50, 540, 98), text, fontsize=8)
    document.save(path)
    document.close()


class FakeOCRProvider:
    name = "fake-ocr"

    def __init__(self, status: str = "completed") -> None:
        self.status = status

    def availability(self) -> tuple[bool, str | None]:
        return self.status != "dependency_unavailable", "missing fake dependency" if self.status == "dependency_unavailable" else None

    def version(self) -> str:
        return "fake-ocr-v1"

    def extract_page(self, _page, page_number: int) -> OCRPageResult:
        return OCRPageResult(
            page_number=page_number,
            text="OCR recovered title and body text." if self.status == "completed" else "",
            confidence=0.91 if self.status == "completed" else None,
            status=self.status,
            provider=self.name,
            provider_version=self.version(),
            error="missing fake dependency" if self.status == "dependency_unavailable" else None,
        )


class VersionedTesseractProvider(FakeOCRProvider):
    name = "tesseract"

    def __init__(self) -> None:
        super().__init__()
        self.version_value = "tesseract-test-v1"
        self.extract_calls = 0

    def version(self) -> str:
        return self.version_value

    def extract_page(self, page, page_number: int) -> OCRPageResult:
        self.extract_calls += 1
        result = super().extract_page(page, page_number)
        return OCRPageResult(
            **{
                **result.__dict__,
                "provider": self.name,
                "provider_version": self.version(),
                "configuration": {"test": "deterministic"},
            }
        )


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

    assert result["extraction_status"] == "blank"
    assert result["diagnostics"]["pages_without_text"] == 1
    assert result["diagnostics"]["possible_scanned_pdf"] is False
    assert result["diagnostics"]["content_type"] == "blank"
    assert result["pages"][0]["review_required"] is True


def test_pdf_parser_handles_malformed_pdf_without_crashing(tmp_path: Path) -> None:
    pdf_path = tmp_path / "malformed.pdf"
    pdf_path.write_bytes(b"not a pdf")

    result = extract_pdf_text("paper-malformed", pdf_path, tmp_path / "extracted")

    assert result["extraction_status"] == "failed"
    assert result["diagnostics"]["extraction_error"]
    assert result["diagnostics"]["ocr_review_required"] is True


def test_pdf_parser_distinguishes_scanned_and_mixed_pages(tmp_path: Path) -> None:
    scanned_path = tmp_path / "scanned.pdf"
    mixed_path = tmp_path / "mixed.pdf"
    create_image_pdf(scanned_path)
    create_image_pdf(mixed_path, with_text=True)

    scanned = extract_pdf_text("paper-scanned", scanned_path, tmp_path / "scanned-out")
    mixed = extract_pdf_text("paper-mixed", mixed_path, tmp_path / "mixed-out")

    assert scanned["extraction_status"] == "scanned_pdf"
    assert scanned["diagnostics"]["content_type"] == "scanned"
    assert scanned["pages"][0]["content_class"] == "scanned"
    assert mixed["extraction_status"] == "extracted"
    assert mixed["diagnostics"]["content_type"] == "mixed"
    assert mixed["pages"][0]["extraction_method"] == "native"


def test_optional_ocr_records_page_provenance_and_dependency_absence(tmp_path: Path) -> None:
    pdf_path = tmp_path / "scanned.pdf"
    create_image_pdf(pdf_path)

    recovered = extract_pdf_text(
        "paper-ocr",
        pdf_path,
        tmp_path / "ocr-out",
        run_ocr=True,
        ocr_provider=FakeOCRProvider(),
    )
    unavailable = extract_pdf_text(
        "paper-no-ocr",
        pdf_path,
        tmp_path / "no-ocr-out",
        run_ocr=True,
        ocr_provider=FakeOCRProvider("dependency_unavailable"),
    )

    assert recovered["extraction_status"] == "extracted"
    assert recovered["diagnostics"]["ocr_status"] == "completed"
    assert recovered["pages"][0]["extraction_method"] == "ocr"
    assert recovered["pages"][0]["ocr_confidence"] == 0.91
    assert recovered["pages"][0]["provenance"]["page_number"] == 1
    assert unavailable["extraction_status"] == "scanned_pdf"
    assert unavailable["diagnostics"]["ocr_status"] == "dependency_unavailable"
    assert unavailable["pages"][0]["review_required"] is True


def test_ocr_version_and_language_pack_identity_participate_in_cache_generation(monkeypatch, tmp_path: Path) -> None:
    pdf_path = tmp_path / "versioned-scanned.pdf"
    create_image_pdf(pdf_path)
    provider = VersionedTesseractProvider()
    configuration = {
        "language": "eng",
        "config": "--oem 3 --psm 6",
        "render_dpi": 144,
        "language_data": {
            "status": "available",
            "resolved_path": "/test/eng.traineddata",
            "sha256": "a" * 64,
        },
    }
    monkeypatch.setattr(pdf_parser_module, "deterministic_ocr_configuration", lambda: configuration)

    first = extract_pdf_text(
        "versioned-ocr",
        pdf_path,
        tmp_path / "versioned-output",
        run_ocr=True,
        ocr_provider=provider,
    )
    cached = extract_pdf_text(
        "versioned-ocr",
        pdf_path,
        tmp_path / "versioned-output",
        run_ocr=True,
        ocr_provider=provider,
    )
    provider.version_value = "tesseract-test-v2"
    version_changed = extract_pdf_text(
        "versioned-ocr",
        pdf_path,
        tmp_path / "versioned-output",
        run_ocr=True,
        ocr_provider=provider,
    )
    configuration = {
        **configuration,
        "language_data": {**configuration["language_data"], "sha256": "b" * 64},
    }
    language_pack_changed = extract_pdf_text(
        "versioned-ocr",
        pdf_path,
        tmp_path / "versioned-output",
        run_ocr=True,
        ocr_provider=provider,
    )

    assert provider.extract_calls == 3
    assert cached["artifact_generation_id"] == first["artifact_generation_id"]
    assert version_changed["artifact_generation_id"] != first["artifact_generation_id"]
    assert language_pack_changed["artifact_generation_id"] != version_changed["artifact_generation_id"]
    assert language_pack_changed["extraction_config"]["ocr_provider_version"] == "tesseract-test-v2"
    assert language_pack_changed["extraction_config"]["ocr_configuration"]["language_data"]["sha256"] == "b" * 64
    assert language_pack_changed["diagnostics"]["ocr_configuration"]["language_data"]["resolved_path"] == "/test/eng.traineddata"


def test_tesseract_language_data_identity_is_hashed_or_explicitly_unavailable() -> None:
    identity = tesseract_language_data_identity("eng")

    assert identity["language"] == "eng"
    assert identity["status"] in {"available", "unavailable"}
    if identity["status"] == "available":
        assert Path(identity["resolved_path"]).is_file()
        assert len(identity["sha256"]) == 64
        assert identity["reason"] is None
    else:
        assert identity["sha256"] is None
        assert identity["reason"]


def test_normal_text_and_figure_page_does_not_trigger_ocr_or_review(tmp_path: Path) -> None:
    pdf_path = tmp_path / "normal-figure.pdf"
    create_image_pdf(pdf_path, with_text=True, substantial_text=True)

    result = extract_pdf_text(
        "paper-normal-figure",
        pdf_path,
        tmp_path / "normal-out",
        run_ocr=True,
        ocr_provider=FakeOCRProvider(),
    )

    assert result["diagnostics"]["content_type"] == "mixed"
    assert result["pages"][0]["native_word_count"] >= 25
    assert result["pages"][0]["ocr_status"] == "not_needed"
    assert result["pages"][0]["extraction_method"] == "native"
    assert result["pages"][0]["review_required"] is False


def test_title_match_diagnostic_flags_unrelated_first_page() -> None:
    mismatch = title_match_diagnostic(
        "Vector Search Performance Enhancements on Limited Memory Edge Devices",
        "Soft-Churn: Optimal Switching between Prepaid Data Subscriptions on E-SIM support Smartphones " * 3,
    )
    match = title_match_diagnostic(
        "A Consumer Focused Open Data Platform",
        "A Consumer Focused Open Data Platform Cherlton Millette Patrick Hosein " * 3,
    )

    assert mismatch["status"] == "possible_mismatch"
    assert mismatch["token_coverage"] == 0.0
    assert match["status"] == "matched"


def test_title_match_searches_bounded_proceedings_pages_without_admitting_weak_overlap() -> None:
    title = "Playlist Shuffling given User-Defined Constraints on Song Sequencing"
    proceedings = title_match_diagnostic_pages(
        title,
        [
            (1, "1"),
            (2, "International Conference on New Music Concepts Proceeding Book " * 3),
            (5, "Contents Playlist Shuffling given User-Defined Constraints on Song Sequencing 7"),
            (7, f"{title} Sterling Ramroach and Patrick Hosein Abstract " * 2),
        ],
    )
    weak_later_overlap = title_match_diagnostic_pages(
        "Vector Search Performance Enhancements on Limited Memory Edge Devices",
        [
            (1, "Soft-Churn Optimal Switching between Prepaid Data Subscriptions on smartphones " * 3),
            (2, "The performance of this mobile device system was evaluated with limited data " * 3),
        ],
    )
    weak_first_overlap = title_match_diagnostic_pages(
        "Vector Search Performance Enhancements on Limited Memory Edge Devices",
        [(1, "Vector performance on a mobile device was measured with limited data " * 4)],
    )

    assert proceedings["status"] == "matched"
    assert proceedings["matched_page"] in {5, 7}
    assert proceedings["match_basis"] in {"bounded_page_exact_phrase", "bounded_page_strong_token_coverage"}
    assert proceedings["scope"]["max_pages"] == 8
    assert weak_later_overlap["status"] == "possible_mismatch"
    assert weak_first_overlap["status"] == "possible_mismatch"
