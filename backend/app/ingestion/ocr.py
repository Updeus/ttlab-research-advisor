from __future__ import annotations

import importlib.util
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import fitz


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

            pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
            data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
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
            )


def get_ocr_provider(name: str = "tesseract") -> OCRProvider:
    normalized = name.strip().lower()
    if normalized == "tesseract":
        return TesseractOCRProvider()
    raise ValueError(f"Unsupported OCR provider: {name}")


def ocr_dependency_status(name: str = "tesseract") -> dict[str, str | bool | None]:
    provider = get_ocr_provider(name)
    available, reason = provider.availability()
    return {"provider": provider.name, "version": provider.version(), "available": available, "reason": reason}


def validate_local_pdf_path(path: Path) -> None:
    """Reject non-files before an OCR provider attempts to render them."""

    if not path.exists() or not path.is_file():
        raise FileNotFoundError(path)
