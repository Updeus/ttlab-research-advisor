from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import fitz
from sqlalchemy import delete
from sqlmodel import Session, select

from app.config import Settings, get_settings
from app.db import create_db_and_tables, engine
from app.io_utils import atomic_write_json, atomic_write_text
from app.ingestion.ocr import OCRProvider, deterministic_ocr_configuration, get_ocr_provider
from app.models import Chunk, Paper
from app.security import require_offline_pdf_worker


def utc_now() -> datetime:
    return datetime.now(UTC)


def count_words(text: str) -> int:
    return len([word for word in text.split() if word.strip()])


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_json_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def extraction_configuration(
    *,
    run_ocr: bool,
    ocr_provider: OCRProvider | None,
    expected_title: str | None,
    max_pdf_bytes: int,
    max_pdf_pages: int,
) -> dict[str, Any]:
    provider_name = getattr(ocr_provider, "name", "tesseract") if run_ocr else None
    provider_version: str | None = None
    if run_ocr and ocr_provider is not None and hasattr(ocr_provider, "version"):
        try:
            provider_version = ocr_provider.version()
        except Exception:
            provider_version = None
    return {
        "run_ocr": run_ocr,
        "ocr_provider": provider_name,
        "ocr_provider_version": provider_version,
        "ocr_configuration": (
            deterministic_ocr_configuration()
            if run_ocr and provider_name == "tesseract"
            else {"status": "provider_specific_configuration_unavailable"} if run_ocr else None
        ),
        "expected_title": expected_title,
        "max_pdf_bytes": max_pdf_bytes,
        "max_pdf_pages": max_pdf_pages,
    }


def load_valid_cached_extraction(
    json_path: Path,
    txt_path: Path,
    *,
    input_pdf_sha256: str,
    extraction_config: dict[str, Any],
) -> dict[str, Any] | None:
    """Load a cache generation only when both authoritative links validate."""

    if not json_path.exists() or not txt_path.exists():
        return None
    try:
        cached = json.loads(json_path.read_text(encoding="utf-8"))
        if not isinstance(cached, dict):
            return None
        expected_text_hash = str(cached.get("text_artifact_sha256") or "")
        if not re.fullmatch(r"[0-9a-f]{64}", expected_text_hash):
            return None
        if cached.get("artifact_contract") != "json_authoritative_text_mirror_v1":
            return None
        if cached.get("input_pdf_sha256") != input_pdf_sha256:
            return None
        if cached.get("extraction_config") != extraction_config:
            return None
        if str(cached.get("full_text_path") or "") != str(txt_path):
            return None
        if file_hash(txt_path) != expected_text_hash:
            return None
        generation_payload = {
            "paper_id": cached.get("paper_id"),
            "input_pdf_sha256": input_pdf_sha256,
            "extraction_config": extraction_config,
            "text_artifact_sha256": expected_text_hash,
        }
        expected_generation_id = hashlib.sha256(
            json.dumps(generation_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        if cached.get("artifact_generation_id") != expected_generation_id:
            return None
        return cached
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return None


def inspect_page_content(page: fitz.Page, native_text: str) -> dict[str, Any]:
    """Classify a page conservatively using native text and visible-object signals."""

    try:
        image_count = len(page.get_images(full=True))
    except Exception:
        image_count = 0
    try:
        drawing_count = len(page.get_drawings())
    except Exception:
        drawing_count = 0
    word_count = count_words(native_text)
    char_count = len(native_text)
    if char_count == 0 and image_count == 0 and drawing_count == 0:
        content_class = "blank"
    elif image_count > 0 and (word_count < 5 or char_count < 30):
        content_class = "scanned"
    elif image_count > 0 and char_count > 0:
        content_class = "mixed"
    elif char_count > 0:
        content_class = "textual"
    else:
        content_class = "unknown"
    return {
        "content_class": content_class,
        "image_count": image_count,
        "drawing_count": drawing_count,
        "native_char_count": char_count,
        "native_word_count": word_count,
    }


def classify_document_content(page_records: list[dict[str, Any]]) -> str:
    classes = {str(page.get("content_class") or "unknown") for page in page_records}
    if classes == {"blank"}:
        return "blank"
    if "mixed" in classes or ("scanned" in classes and ("textual" in classes or "blank" in classes)):
        return "mixed"
    if "scanned" in classes:
        return "scanned"
    if "textual" in classes:
        return "textual"
    return "unknown"


def summarize_ocr_status(page_records: list[dict[str, Any]], requested: bool) -> str:
    if not requested:
        return "not_requested"
    statuses = [str(page.get("ocr_status")) for page in page_records if page.get("ocr_status") not in {None, "not_needed"}]
    if not statuses:
        return "not_needed"
    if all(status == "completed" for status in statuses):
        return "completed"
    if "completed" in statuses:
        return "partial"
    if "dependency_unavailable" in statuses:
        return "dependency_unavailable"
    if "failed" in statuses:
        return "failed"
    return "no_text"


TITLE_STOPWORDS = {
    "a",
    "an",
    "and",
    "for",
    "from",
    "in",
    "of",
    "on",
    "the",
    "to",
    "using",
    "with",
}


def title_match_diagnostic_pages(
    expected_title: str | None,
    pages: list[tuple[int, str]],
    *,
    max_pages: int = 8,
) -> dict[str, Any]:
    expected_tokens = {
        token
        for token in re.findall(r"[a-z0-9]+", (expected_title or "").casefold())
        if token not in TITLE_STOPWORDS and len(token) > 1
    }
    expected_phrase = " ".join(re.findall(r"[a-z0-9]+", (expected_title or "").casefold()))
    examined = [(number, text) for number, text in pages[:max_pages]]
    if len(expected_tokens) < 3 or sum(len(text.strip()) for _, text in examined) < 80:
        return {
            "status": "not_assessed",
            "token_coverage": None,
            "expected_title": expected_title,
            "matched_page": None,
            "match_basis": None,
            "scope": {"max_pages": max_pages, "pages_examined": [number for number, _ in examined]},
            "reason": "Insufficient title tokens or bounded-page text for a conservative comparison.",
        }
    page_scores: list[tuple[int, float, set[str], bool]] = []
    for page_number, page_text in examined:
        normalized_page = " ".join(re.findall(r"[a-z0-9]+", page_text[:12000].casefold()))
        page_tokens = set(normalized_page.split())
        overlap = expected_tokens.intersection(page_tokens)
        coverage = len(overlap) / len(expected_tokens)
        exact_phrase = bool(expected_phrase and expected_phrase in normalized_page)
        page_scores.append((page_number, coverage, overlap, exact_phrase))
    best_page, coverage, overlap, exact_phrase = max(page_scores, key=lambda item: (item[1], item[3]))
    first_page = page_scores[0]
    if first_page[3] or first_page[1] >= 0.6:
        status = "matched"
        best_page, coverage, overlap, exact_phrase = first_page
        match_basis = "first_page_exact_phrase" if first_page[3] else "first_page_strong_token_coverage"
    elif exact_phrase or coverage >= 0.6:
        status = "matched"
        match_basis = "bounded_page_exact_phrase" if exact_phrase else "bounded_page_strong_token_coverage"
    else:
        status = "possible_mismatch"
        match_basis = None
    return {
        "status": status,
        "token_coverage": round(coverage, 4),
        "expected_title": expected_title,
        "matched_page": best_page if status == "matched" else None,
        "best_candidate_page": best_page,
        "match_basis": match_basis,
        "scope": {"max_pages": max_pages, "pages_examined": [number for number, _ in examined]},
        "matched_tokens": sorted(overlap),
        "missing_tokens": sorted(expected_tokens - overlap),
        "reason": "No first-page match or strong bounded-page title evidence; manual PDF identity review is required."
        if status == "possible_mismatch"
        else "Publication title was found by the conservative bounded-page identity check.",
    }


def title_match_diagnostic(expected_title: str | None, first_page_text: str) -> dict[str, Any]:
    """Backward-compatible single-page wrapper used by focused callers/tests."""

    return title_match_diagnostic_pages(expected_title, [(1, first_page_text)], max_pages=1)


def extract_pdf_text(
    paper_id: str,
    local_pdf_path: Path,
    output_dir: Path = Path("data/extracted_text"),
    overwrite: bool = False,
    run_ocr: bool = False,
    ocr_provider: OCRProvider | None = None,
    expected_title: str | None = None,
    max_pdf_bytes: int | None = None,
    max_pdf_pages: int | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    max_pdf_bytes = max_pdf_bytes or settings.max_pdf_download_bytes
    max_pdf_pages = max_pdf_pages or settings.max_pdf_pages
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = safe_output_path(output_dir, paper_id, ".json")
    txt_path = safe_output_path(output_dir, paper_id, ".txt")
    if not local_pdf_path.exists() or not local_pdf_path.is_file():
        return build_failed_result(paper_id, local_pdf_path, json_path, txt_path, "Configured PDF path is not a file.")
    if local_pdf_path.suffix.lower() != ".pdf":
        return build_failed_result(paper_id, local_pdf_path, json_path, txt_path, "Configured input is not a .pdf file.")
    if local_pdf_path.stat().st_size > max_pdf_bytes:
        return build_failed_result(
            paper_id,
            local_pdf_path,
            json_path,
            txt_path,
            f"PDF exceeds the configured {max_pdf_bytes}-byte parser limit.",
        )
    with local_pdf_path.open("rb") as source_handle:
        if not source_handle.read(1_024).startswith(b"%PDF"):
            return build_failed_result(
                paper_id,
                local_pdf_path,
                json_path,
                txt_path,
                "Configured input does not contain a PDF signature.",
            )

    input_pdf_sha256 = file_hash(local_pdf_path)
    provider = ocr_provider or (get_ocr_provider("tesseract") if run_ocr else None)
    extraction_config = extraction_configuration(
        run_ocr=run_ocr,
        ocr_provider=provider,
        expected_title=expected_title,
        max_pdf_bytes=max_pdf_bytes,
        max_pdf_pages=max_pdf_pages,
    )
    if not overwrite:
        cached = load_valid_cached_extraction(
            json_path,
            txt_path,
            input_pdf_sha256=input_pdf_sha256,
            extraction_config=extraction_config,
        )
        if cached is not None:
            return cached

    warnings: list[str] = []
    try:
        document = fitz.open(local_pdf_path)
    except Exception as exc:
        return build_failed_result(paper_id, local_pdf_path, json_path, txt_path, str(exc))

    if document.page_count > max_pdf_pages:
        document.close()
        return build_failed_result(
            paper_id,
            local_pdf_path,
            json_path,
            txt_path,
            f"PDF exceeds the configured {max_pdf_pages}-page parser limit.",
        )

    pages: list[dict[str, Any]] = []
    full_text_parts: list[str] = []
    extraction_error: str | None = None
    try:
        for index, page in enumerate(document, start=1):
            native_text = (page.get_text("text") or "").strip()
            content = inspect_page_content(page, native_text)
            normalized_text = native_text
            low_native_text = content["native_word_count"] < 25 or content["native_char_count"] < 180
            ocr_status = (
                "not_needed"
                if content["content_class"] == "textual"
                or (content["content_class"] == "mixed" and not low_native_text)
                else "not_requested"
            )
            ocr_provider_name: str | None = None
            ocr_provider_version: str | None = None
            ocr_confidence: float | None = None
            ocr_error: str | None = None
            ocr_configuration: dict[str, Any] | None = None
            text_source = "native" if native_text else "none"
            should_ocr = run_ocr and (
                content["content_class"] in {"scanned", "unknown"}
                or (content["content_class"] == "mixed" and low_native_text)
            )
            if should_ocr and provider is not None:
                ocr_result = provider.extract_page(page, index)
                ocr_status = ocr_result.status
                ocr_provider_name = ocr_result.provider
                ocr_provider_version = ocr_result.provider_version
                ocr_confidence = ocr_result.confidence
                ocr_error = ocr_result.error
                ocr_configuration = ocr_result.configuration
                ocr_text = ocr_result.text.strip()
                if ocr_text:
                    if native_text and ocr_text not in native_text:
                        normalized_text = f"{native_text}\n\n[OCR supplement]\n{ocr_text}"
                        text_source = "native+ocr"
                    elif not native_text:
                        normalized_text = ocr_text
                        text_source = "ocr"
                if ocr_error:
                    warnings.append(f"Page {index} OCR {ocr_status}: {ocr_error}")
            review_required = (
                content["content_class"] in {"scanned", "blank", "unknown"}
                or (content["content_class"] == "mixed" and low_native_text)
                or ocr_status in {"dependency_unavailable", "failed", "no_text"}
                or (ocr_confidence is not None and ocr_confidence < 0.6)
            )
            page_record = {
                "page_number": index,
                "text": normalized_text,
                "char_count": len(normalized_text),
                "word_count": count_words(normalized_text),
                **content,
                "extraction_method": text_source,
                "ocr_status": ocr_status,
                "ocr_provider": ocr_provider_name,
                "ocr_provider_version": ocr_provider_version,
                "ocr_confidence": ocr_confidence,
                "ocr_error": ocr_error,
                "ocr_configuration": ocr_configuration,
                "review_required": review_required,
                "provenance": {
                    "local_pdf_path": str(local_pdf_path),
                    "page_number": index,
                    "native_extractor": f"PyMuPDF {fitz.VersionBind}",
                    "ocr_provider": ocr_provider_name,
                    "ocr_provider_version": ocr_provider_version,
                    "ocr_configuration": ocr_configuration,
                },
            }
            pages.append(page_record)
            full_text_parts.append(f"\n\n--- Page {index} ---\n{normalized_text}".strip())
    except Exception as exc:
        extraction_error = str(exc)
    finally:
        document.close()

    full_text = "\n\n".join(part for part in full_text_parts if part)
    total_char_count = sum(page["char_count"] for page in pages)
    total_word_count = sum(page["word_count"] for page in pages)
    pages_with_text = sum(1 for page in pages if page["char_count"] > 0)
    pages_without_text = len(pages) - pages_with_text
    content_type = classify_document_content(pages)
    possible_scanned_pdf = content_type in {"scanned", "mixed"} and any(
        page.get("content_class") == "scanned" for page in pages
    )
    if possible_scanned_pdf:
        warnings.append("PDF may be scanned or image-heavy; little extractable text was found.")

    extraction_status = "failed" if extraction_error else "extracted"
    if not extraction_error and total_char_count == 0:
        extraction_status = "blank" if content_type == "blank" else "scanned_pdf" if content_type == "scanned" else "no_text"
    ocr_status = summarize_ocr_status(pages, run_ocr)
    ocr_pages_count = sum(1 for page in pages if page.get("ocr_status") == "completed")
    ocr_review_required = any(bool(page.get("review_required")) for page in pages)
    title_match = title_match_diagnostic_pages(
        expected_title,
        [(int(page.get("page_number") or 0), str(page.get("text") or "")) for page in pages],
    )
    if title_match["status"] == "possible_mismatch":
        warnings.append("The bounded-page title check may not match the publication record; exclude until reviewed.")

    serialized_text = full_text + ("\n" if full_text else "")
    text_artifact_sha256 = text_hash(serialized_text)
    artifact_generation_id = hashlib.sha256(
        json.dumps(
            {
                "paper_id": paper_id,
                "input_pdf_sha256": input_pdf_sha256,
                "extraction_config": extraction_config,
                "text_artifact_sha256": text_artifact_sha256,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    result = {
        "paper_id": paper_id,
        "local_pdf_path": str(local_pdf_path),
        "page_count": len(pages),
        "pages": pages,
        "full_text_path": str(txt_path),
        "text_hash": text_hash(full_text),
        "text_artifact_sha256": text_artifact_sha256,
        "artifact_generation_id": artifact_generation_id,
        "artifact_contract": "json_authoritative_text_mirror_v1",
        "input_pdf_sha256": input_pdf_sha256,
        "extraction_config": extraction_config,
        "extraction_status": extraction_status,
        "warnings": warnings,
        "diagnostics": {
            "page_count": len(pages),
            "total_char_count": total_char_count,
            "total_word_count": total_word_count,
            "pages_with_text": pages_with_text,
            "pages_without_text": pages_without_text,
            "possible_scanned_pdf": possible_scanned_pdf,
            "content_type": content_type,
            "page_content_counts": {
                label: sum(1 for page in pages if page.get("content_class") == label)
                for label in ("textual", "mixed", "scanned", "blank", "unknown")
            },
            "ocr_requested": run_ocr,
            "ocr_status": ocr_status,
            "ocr_provider": provider.name if provider is not None else None,
            "ocr_provider_version": provider.version() if provider is not None and hasattr(provider, "version") else None,
            "ocr_configuration": extraction_config.get("ocr_configuration"),
            "ocr_pages_count": ocr_pages_count,
            "ocr_review_required": ocr_review_required,
            "pdf_title_match": title_match,
            "extraction_error": extraction_error,
        },
    }
    # The JSON manifest is the authoritative commit record and is replaced
    # last. A crash after replacing TXT leaves the old JSON/hash pair invalid,
    # which consumers quarantine instead of accepting a mixed generation.
    atomic_write_text(txt_path, serialized_text)
    atomic_write_json(json_path, result)
    return result


def safe_output_path(output_dir: Path, paper_id: str, suffix: str) -> Path:
    if not paper_id or len(paper_id) > 200:
        raise ValueError("paper_id must contain between 1 and 200 characters")
    safe_name = "".join(char if char.isalnum() or char in "-_" else "-" for char in paper_id).strip("-")
    if not safe_name:
        raise ValueError("paper_id does not contain any safe filename characters")
    if safe_name != paper_id:
        safe_name = f"{safe_name[:160]}-{hashlib.sha256(paper_id.encode('utf-8')).hexdigest()[:12]}"
    target = output_dir / f"{safe_name}{suffix}"
    if target.resolve().parent != output_dir.resolve():
        raise ValueError("Resolved extraction target escaped the configured output directory")
    return target


def build_failed_result(
    paper_id: str,
    local_pdf_path: Path,
    json_path: Path,
    txt_path: Path,
    error: str,
) -> dict[str, Any]:
    serialized_text = ""
    text_artifact_sha256 = text_hash(serialized_text)
    result = {
        "paper_id": paper_id,
        "local_pdf_path": str(local_pdf_path),
        "page_count": 0,
        "pages": [],
        "full_text_path": str(txt_path),
        "text_hash": text_hash(""),
        "text_artifact_sha256": text_artifact_sha256,
        "artifact_generation_id": hashlib.sha256(
            f"{paper_id}|failed|{text_artifact_sha256}|{error}".encode("utf-8")
        ).hexdigest(),
        "artifact_contract": "json_authoritative_text_mirror_v1",
        "extraction_status": "failed",
        "warnings": [],
        "diagnostics": {
            "page_count": 0,
            "total_char_count": 0,
            "total_word_count": 0,
            "pages_with_text": 0,
            "pages_without_text": 0,
            "possible_scanned_pdf": False,
            "content_type": "unknown",
            "page_content_counts": {"textual": 0, "mixed": 0, "scanned": 0, "blank": 0, "unknown": 0},
            "ocr_requested": False,
            "ocr_status": "not_requested",
            "ocr_provider": None,
            "ocr_provider_version": None,
            "ocr_pages_count": 0,
            "ocr_review_required": True,
            "pdf_title_match": {
                "status": "not_assessed",
                "token_coverage": None,
                "expected_title": None,
                "reason": "PDF could not be opened.",
            },
            "extraction_error": error,
        },
    }
    atomic_write_text(txt_path, serialized_text)
    atomic_write_json(json_path, result)
    return result


def update_paper_from_extraction(session: Session, paper: Paper, result: dict[str, Any], json_path: Path) -> None:
    # Local import avoids the metadata-cleaner -> parser cycle while keeping
    # one invalidation contract shared with manual corrections.
    from app.ingestion.manual_import import (
        invalidate_generated_outputs_for_paper,
        reset_dependent_graph_reviews_for_paper,
    )

    new_generation_id = str(result.get("artifact_generation_id") or "") or None
    new_input_sha256 = str(result.get("input_pdf_sha256") or "") or None
    extraction_config = result.get("extraction_config")
    new_config_sha256 = canonical_json_sha256(extraction_config) if isinstance(extraction_config, dict) else None
    generation_changed = paper.extraction_generation_id != new_generation_id
    source_bytes_changed = paper.extraction_input_pdf_sha256 != new_input_sha256
    if generation_changed:
        session.exec(delete(Chunk).where(Chunk.paper_id == paper.paper_id))
        paper.chunk_count = 0
        paper.chunk_extraction_generation_id = None
        paper.chunk_generation_id = None
        paper.public_index_generation_id = None
        paper.publication_status = "pending_review"
        paper.public_access_level = "hidden"
        if source_bytes_changed:
            paper.rights_status = "unknown"
        reset_dependent_graph_reviews_for_paper(
            session,
            paper.paper_id,
            reason="Extraction generation changed; source-derived topic relationships require re-review.",
        )
        invalidate_generated_outputs_for_paper(
            session,
            paper.paper_id,
            reason="Extraction generation changed; regenerate and reapprove this source-grounded output.",
        )
        paper.extraction_review_status = "needs_review"
        paper.extraction_reviewer_notes = None
        paper.extraction_reviewed_at = None
        paper.extraction_reviewed_by = None
    paper.extraction_generation_id = new_generation_id
    paper.extraction_input_pdf_sha256 = new_input_sha256
    paper.extraction_config_sha256 = new_config_sha256
    diagnostics = dict(result.get("diagnostics", {}))
    diagnostics["warnings"] = result.get("warnings", [])
    status = result.get("extraction_status")
    paper.pdf_text_status = {
        "extracted": "extracted",
        "no_text": "no_text",
        "blank": "blank_pdf",
        "scanned_pdf": "scanned_pdf",
        "failed": "extraction_failed",
    }.get(str(status), "extraction_failed")
    paper.ingestion_status = "text_extracted" if paper.pdf_text_status == "extracted" else paper.pdf_text_status
    paper.extracted_json_path = str(json_path)
    paper.extracted_text_path = str(result.get("full_text_path") or "")
    paper.extraction_diagnostics = diagnostics
    paper.page_count = int(diagnostics.get("page_count") or 0)
    paper.total_char_count = int(diagnostics.get("total_char_count") or 0)
    paper.total_word_count = int(diagnostics.get("total_word_count") or 0)
    paper.pages_with_text = int(diagnostics.get("pages_with_text") or 0)
    paper.pages_without_text = int(diagnostics.get("pages_without_text") or 0)
    paper.possible_scanned_pdf = bool(diagnostics.get("possible_scanned_pdf") or False)
    paper.extraction_content_type = str(diagnostics.get("content_type") or "unknown")
    paper.ocr_status = str(diagnostics.get("ocr_status") or "not_requested")
    paper.ocr_provider = diagnostics.get("ocr_provider")
    paper.ocr_provider_version = diagnostics.get("ocr_provider_version")
    paper.ocr_pages_count = int(diagnostics.get("ocr_pages_count") or 0)
    paper.ocr_review_required = bool(diagnostics.get("ocr_review_required") or False)
    title_match = diagnostics.get("pdf_title_match") if isinstance(diagnostics.get("pdf_title_match"), dict) else {}
    paper.pdf_title_match_status = str(title_match.get("status") or "not_assessed")
    paper.pdf_title_match_score = title_match.get("token_coverage")
    if paper.pdf_text_status == "scanned_pdf":
        paper.pdf_unavailability_reason = "scanned_pdf"
        paper.pdf_unavailability_detail = "Native extraction found image-based pages without usable text; OCR review is required."
    elif paper.pdf_text_status in {"extraction_failed", "no_text", "blank_pdf"}:
        paper.pdf_unavailability_reason = "extraction_failure"
        paper.pdf_unavailability_detail = str(diagnostics.get("extraction_error") or paper.pdf_text_status)
    elif paper.pdf_text_status == "extracted":
        paper.pdf_unavailability_reason = None
        paper.pdf_unavailability_detail = None
    if paper.pdf_title_match_status == "possible_mismatch":
        paper.corpus_eligibility_status = "excluded_pdf_metadata_mismatch"
        paper.corpus_exclusion_reason = "The bounded-page title check lacks strong evidence for this publication title; manual correction is required."
        paper.ocr_review_required = True
    elif paper.pdf_text_status != "extracted":
        paper.corpus_eligibility_status = "ineligible_extraction"
        paper.corpus_exclusion_reason = f"PDF text status is {paper.pdf_text_status}."
    elif paper.pdf_title_match_status == "matched":
        paper.corpus_eligibility_status = "eligible"
        paper.corpus_exclusion_reason = None
    else:
        paper.corpus_eligibility_status = "needs_review"
        paper.corpus_exclusion_reason = "PDF title identity could not be assessed conservatively."
    paper.updated_at = utc_now()
    session.add(paper)


def candidate_papers(session: Session, paper_ids: list[str] | None = None) -> list[Paper]:
    statement = select(Paper).where(Paper.local_pdf_path.is_not(None)).order_by(Paper.year.desc(), Paper.title)
    papers = list(session.exec(statement).all())
    if paper_ids:
        allowed = set(paper_ids)
        papers = [paper for paper in papers if paper.paper_id in allowed]
    return papers


def extract_from_db(
    session: Session,
    *,
    limit: int | None = None,
    paper_ids: list[str] | None = None,
    overwrite: bool = False,
    output_dir: Path = Path("data/extracted_text"),
    run_ocr: bool = False,
    ocr_provider: OCRProvider | None = None,
    settings_override: Settings | None = None,
) -> dict[str, int]:
    worker_settings = settings_override or get_settings()
    require_offline_pdf_worker(worker_settings, "Batch PDF parsing")
    summary = {
        "attempted": 0,
        "extracted": 0,
        "no_text": 0,
        "scanned_pdf": 0,
        "blank_pdf": 0,
        "ocr_completed": 0,
        "ocr_dependency_unavailable": 0,
        "failed": 0,
        "missing_pdf": 0,
        "skipped_existing": 0,
    }
    for paper in candidate_papers(session, paper_ids):
        if limit is not None and summary["attempted"] >= limit:
            break
        if not paper.local_pdf_path:
            summary["missing_pdf"] += 1
            continue
        local_pdf_path = Path(paper.local_pdf_path)
        if not local_pdf_path.exists():
            summary["missing_pdf"] += 1
            paper.pdf_text_status = "missing_pdf"
            paper.pdf_unavailability_reason = "not_found"
            paper.pdf_unavailability_detail = f"Configured local PDF path does not exist: {local_pdf_path}"
            session.add(paper)
            continue
        json_path = safe_output_path(output_dir, paper.paper_id, ".json")
        txt_path = safe_output_path(output_dir, paper.paper_id, ".txt")
        extraction_config = extraction_configuration(
            run_ocr=run_ocr,
            ocr_provider=ocr_provider,
            expected_title=paper.title,
            max_pdf_bytes=worker_settings.max_pdf_download_bytes,
            max_pdf_pages=worker_settings.max_pdf_pages,
        )
        if not overwrite:
            cached = load_valid_cached_extraction(
                json_path,
                txt_path,
                input_pdf_sha256=file_hash(local_pdf_path),
                extraction_config=extraction_config,
            )
            if cached is not None:
                # The manifest is authoritative. Reconcile database state even
                # after a prior process promoted the files but crashed before
                # committing the corresponding Paper generation.
                update_paper_from_extraction(session, paper, cached, json_path)
                summary["skipped_existing"] += 1
                continue
        summary["attempted"] += 1
        result = extract_pdf_text(
            paper.paper_id,
            local_pdf_path,
            output_dir,
            overwrite=overwrite,
            run_ocr=run_ocr,
            ocr_provider=ocr_provider,
            expected_title=paper.title,
            max_pdf_bytes=worker_settings.max_pdf_download_bytes,
            max_pdf_pages=worker_settings.max_pdf_pages,
        )
        update_paper_from_extraction(session, paper, result, json_path)
        status = result["extraction_status"]
        if status == "extracted":
            summary["extracted"] += 1
        elif status == "no_text":
            summary["no_text"] += 1
        elif status == "scanned_pdf":
            summary["scanned_pdf"] += 1
        elif status == "blank":
            summary["blank_pdf"] += 1
        else:
            summary["failed"] += 1
        ocr_status = result.get("diagnostics", {}).get("ocr_status")
        if ocr_status == "completed":
            summary["ocr_completed"] += 1
        elif ocr_status == "dependency_unavailable":
            summary["ocr_dependency_unavailable"] += 1
    session.commit()
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract page-aware text from downloaded PDFs.")
    subparsers = parser.add_subparsers(dest="command")
    extract = subparsers.add_parser("extract")
    extract.add_argument("--limit", type=int, default=None)
    extract.add_argument("--paper-id", action="append", default=None)
    extract.add_argument("--overwrite", action="store_true")
    extract.add_argument("--from-db", action="store_true", default=True)
    extract.add_argument("--out-dir", default="data/extracted_text")
    extract.add_argument("--ocr", action="store_true", help="Attempt optional OCR on image-based pages.")
    extract.add_argument("--ocr-provider", default="tesseract", choices=["tesseract"])
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command != "extract":
        build_parser().print_help()
        return
    create_db_and_tables()
    with Session(engine) as session:
        summary = extract_from_db(
            session,
            limit=args.limit,
            paper_ids=args.paper_id,
            overwrite=args.overwrite,
            output_dir=Path(args.out_dir),
            run_ocr=args.ocr,
            ocr_provider=get_ocr_provider(args.ocr_provider) if args.ocr else None,
        )
    print(
        "attempted={attempted} extracted={extracted} no_text={no_text} failed={failed} "
        "scanned_pdf={scanned_pdf} blank_pdf={blank_pdf} ocr_completed={ocr_completed} "
        "ocr_dependency_unavailable={ocr_dependency_unavailable} missing_pdf={missing_pdf} "
        "skipped_existing={skipped_existing}".format(**summary)
    )


if __name__ == "__main__":
    main()
