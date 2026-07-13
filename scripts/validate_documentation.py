#!/usr/bin/env python3
"""Validate repository-local links in tracked Markdown documentation."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
INLINE_LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
REFERENCE_LINK = re.compile(r"^\s*\[[^\]]+\]:\s*(\S+)", re.MULTILINE)
IGNORED_SCHEMES = {"http", "https", "mailto", "data", "app"}
MACHINE_PATH = re.compile(r"^(?:[A-Za-z]:[\\/]|/(?:home|mnt|Users)/)")


def tracked_markdown() -> list[Path]:
    completed = subprocess.run(
        ["git", "ls-files", "-z", "*.md"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return [ROOT / value.decode("utf-8") for value in completed.stdout.split(b"\0") if value]


def target_token(raw: str) -> str:
    value = raw.strip()
    if value.startswith("<") and ">" in value:
        return value[1 : value.index(">")]
    return value.split(maxsplit=1)[0] if value else ""


def local_target(source: Path, raw: str) -> tuple[Path | None, str | None]:
    token = target_token(raw)
    if not token or token.startswith("#"):
        return None, None
    if MACHINE_PATH.match(token):
        return None, f"machine-local absolute path: {token}"
    split = urlsplit(token)
    if split.scheme.casefold() in IGNORED_SCHEMES or split.netloc:
        return None, None
    path_text = unquote(split.path)
    if not path_text:
        return None, None
    candidate = (ROOT / path_text.lstrip("/")) if path_text.startswith("/") else (source.parent / path_text)
    resolved = candidate.resolve()
    try:
        resolved.relative_to(ROOT)
    except ValueError:
        return None, f"link escapes repository root: {token}"
    return resolved, None


def validate() -> dict[str, object]:
    errors: list[str] = []
    paths = tracked_markdown()
    checked_links = 0
    for path in paths:
        text = path.read_text(encoding="utf-8")
        matches = [*INLINE_LINK.finditer(text), *REFERENCE_LINK.finditer(text)]
        for match in matches:
            raw = match.group(1)
            target, error = local_target(path, raw)
            if target is None and error is None:
                continue
            checked_links += 1
            line = text.count("\n", 0, match.start()) + 1
            location = f"{path.relative_to(ROOT)}:{line}"
            if error:
                errors.append(f"{location}: {error}")
            elif target is not None and not target.exists():
                errors.append(f"{location}: missing local link target: {raw}")
    return {
        "status": "PASS" if not errors else "FAIL",
        "markdown_files": len(paths),
        "local_links_checked": checked_links,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    report = validate()
    if args.json_out:
        destination = args.json_out if args.json_out.is_absolute() else ROOT / args.json_out
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
