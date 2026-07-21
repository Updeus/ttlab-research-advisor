from __future__ import annotations

import importlib.util
import hashlib
import os
import re
import shutil
import subprocess
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import fitz

TESSERACT_LANGUAGE = "eng"
TESSERACT_CONFIG = "--oem 3 --psm 6"
OCR_RENDER_DPI = 144
OCR_RENDER_SCALE = OCR_RENDER_DPI / 72
OCR_ENVIRONMENT = {
    "LC_ALL": "C.UTF-8",
    "LANG": "C.UTF-8",
    "OMP_THREAD_LIMIT": "1",
}
_OCR_ENVIRONMENT_LOCK = threading.Lock()


def deterministic_ocr_configuration() -> dict[str, Any]:
    return {
        "language": TESSERACT_LANGUAGE,
        "config": TESSERACT_CONFIG,
        "render_dpi": OCR_RENDER_DPI,
        "render_scale": OCR_RENDER_SCALE,
        "environment": dict(OCR_ENVIRONMENT),
        "language_data": tesseract_language_data_identity(TESSERACT_LANGUAGE),
    }


def tesseract_language_data_identity(language: str = TESSERACT_LANGUAGE) -> dict[str, Any]:
    """Resolve and hash the selected traineddata file without claiming availability."""

    candidates: list[Path] = []
    prefix = os.environ.get("TESSDATA_PREFIX")
    if prefix:
        base = Path(prefix).expanduser()
        candidates.extend([base / f"{language}.traineddata", base / "tessdata" / f"{language}.traineddata"])
    executable = shutil.which("tesseract")
    discovery_error: str | None = None
    if executable:
        try:
            completed = subprocess.run(
                [executable, "--list-langs"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
                env={**os.environ, **OCR_ENVIRONMENT},
            )
            combined = "\n".join([completed.stdout or "", completed.stderr or ""])
            match = re.search(r'available languages in ["\']([^"\']+)["\']', combined, flags=re.IGNORECASE)
            if match:
                candidates.append(Path(match.group(1)) / f"{language}.traineddata")
            elif completed.returncode != 0:
                discovery_error = f"tesseract_list_langs_exit_{completed.returncode}"
        except (OSError, subprocess.SubprocessError) as exc:
            discovery_error = f"tesseract_list_langs_{type(exc).__name__}"
    for root in (
        Path("/usr/share/tesseract-ocr/5/tessdata"),
        Path("/usr/share/tesseract-ocr/4.00/tessdata"),
        Path("/usr/share/tessdata"),
    ):
        candidates.append(root / f"{language}.traineddata")
    seen: set[Path] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        if not resolved.is_file():
            continue
        try:
            digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
        except OSError as exc:
            return {
                "language": language,
                "status": "unavailable",
                "resolved_path": str(resolved),
                "sha256": None,
                "reason": f"traineddata_read_{type(exc).__name__}",
            }
        return {
            "language": language,
            "status": "available",
            "resolved_path": str(resolved),
            "sha256": digest,
            "reason": None,
        }
    return {
        "language": language,
        "status": "unavailable",
        "resolved_path": None,
        "sha256": None,
        "reason": discovery_error or "traineddata_path_not_resolved",
    }


@contextmanager
def deterministic_ocr_environment():  # type: ignore[no-untyped-def]
    """Temporarily pin process-global OCR locale/thread controls safely."""

    with _OCR_ENVIRONMENT_LOCK:
        prior = {key: os.environ.get(key) for key in OCR_ENVIRONMENT}
        os.environ.update(OCR_ENVIRONMENT)
        try:
            yield
        finally:
            for key, value in prior.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


@dataclass(frozen=True)
class OCRPageResult:
    """Page-level OCR output with explicit provenance and uncertainty."""

    page_number: int
    text: str
    confidence: float | None
    status: str
    provider: str
    provider_version: str | None = None
    error: str | None = None
    configuration: dict[str, Any] | None = None


class OCRProvider(Protocol):
    name: str

    def availability(self) -> tuple[bool, str | None]: ...

    def version(self) -> str | None: ...

    def extract_page(self, page: fitz.Page, page_number: int) -> OCRPageResult: ...


class TesseractOCRProvider:
    """Optional local OCR provider.

    pytesseract, Pillow, and the tesseract executable are intentionally optional.
    Missing dependencies produce a structured unavailable result rather than making
    PDF ingestion fail.
    """

    name = "tesseract"

    def availability(self) -> tuple[bool, str | None]:
        missing: list[str] = []
        if importlib.util.find_spec("pytesseract") is None:
            missing.append("pytesseract")
        if importlib.util.find_spec("PIL") is None:
            missing.append("Pillow")
        if shutil.which("tesseract") is None:
            missing.append("tesseract executable")
        if missing:
            return False, "missing optional OCR dependency: " + ", ".join(missing)
        return True, None

    def version(self) -> str | None:
        executable = shutil.which("tesseract")
        if executable is None:
            return None
        try:
            completed = subprocess.run(
                [executable, "--version"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        first_line = completed.stdout.splitlines()[0].strip() if completed.stdout else ""
        return first_line or None

    def extract_page(self, page: fitz.Page, page_number: int) -> OCRPageResult:
        available, reason = self.availability()
        if not available:
            return OCRPageResult(
                page_number=page_number,
                text="",
                confidence=None,
                status="dependency_unavailable",
                provider=self.name,
                provider_version=self.version(),
                error=reason,
            )
        try:
            import pytesseract
            from PIL import Image

            with deterministic_ocr_environment():
                pixmap = page.get_pixmap(matrix=fitz.Matrix(OCR_RENDER_SCALE, OCR_RENDER_SCALE), alpha=False)
                image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
                data = pytesseract.image_to_data(
                    image,
                    lang=TESSERACT_LANGUAGE,
                    config=TESSERACT_CONFIG,
                    output_type=pytesseract.Output.DICT,
                )
            words: list[str] = []
            confidences: list[float] = []
            for word, raw_confidence in zip(data.get("text", []), data.get("conf", []), strict=False):
                cleaned = str(word).strip()
                if not cleaned:
                    continue
                words.append(cleaned)
                try:
                    confidence = float(raw_confidence)
                except (TypeError, ValueError):
                    continue
                if confidence >= 0:
                    confidences.append(confidence / 100.0)
            text = " ".join(words)
            confidence = sum(confidences) / len(confidences) if confidences else None
            return OCRPageResult(
                page_number=page_number,
                text=text,
                confidence=round(confidence, 4) if confidence is not None else None,
                status="completed" if text else "no_text",
                provider=self.name,
                provider_version=self.version(),
                configuration=deterministic_ocr_configuration(),
            )
        except Exception as exc:  # optional provider failures must remain recoverable
            return OCRPageResult(
                page_number=page_number,
                text="",
                confidence=None,
                status="failed",
                provider=self.name,
                provider_version=self.version(),
                error=f"{type(exc).__name__}: {exc}",
                configuration=deterministic_ocr_configuration(),
            )


def get_ocr_provider(name: str = "tesseract") -> OCRProvider:
    normalized = name.strip().lower()
    if normalized == "tesseract":
        return TesseractOCRProvider()
    raise ValueError(f"Unsupported OCR provider: {name}")


def ocr_dependency_status(name: str = "tesseract") -> dict[str, str | bool | None]:
    provider = get_ocr_provider(name)
    available, reason = provider.availability()
    return {
        "provider": provider.name,
        "version": provider.version(),
        "available": available,
        "reason": reason,
        "configuration": deterministic_ocr_configuration(),
    }


def validate_local_pdf_path(path: Path) -> None:
    """Reject non-files before an OCR provider attempts to render them."""

    if not path.exists() or not path.is_file():
        raise FileNotFoundError(path)
