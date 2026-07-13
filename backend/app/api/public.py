from __future__ import annotations

from typing import Any

LOCAL_PATH_KEYS = {
    "path",
    "index_path",
    "manifest_path",
    "local_pdf_path",
    "extracted_json_path",
    "extracted_text_path",
    "full_text_path",
    "saved_json_path",
}


def redact_local_paths(value: Any) -> Any:
    """Recursively omit server-local storage locations from public JSON."""

    if isinstance(value, dict):
        return {
            key: redact_local_paths(item)
            for key, item in value.items()
            if key not in LOCAL_PATH_KEYS
        }
    if isinstance(value, list):
        return [redact_local_paths(item) for item in value]
    return value
