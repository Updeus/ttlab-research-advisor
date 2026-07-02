from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

USER_AGENT = "TTLABResearchIntelligence/0.1 (+https://lab.tt)"


def is_direct_pdf_candidate(url: str | None) -> bool:
    if not url:
        return False
    return urlparse(url).path.lower().endswith(".pdf")


def verify_pdf_response(response: httpx.Response) -> bool:
    content_type = response.headers.get("content-type", "").lower()
    if "application/pdf" in content_type:
        return True
    return response.content[:5] == b"%PDF-"


def deterministic_pdf_path(output_dir: Path, paper_id: str) -> Path:
    safe_name = "".join(char if char.isalnum() or char in "-_" else "-" for char in paper_id).strip("-")
    return output_dir / f"{safe_name}.pdf"


def download_pdfs(seed_path: Path, output_dir: Path, limit: int | None, download: bool) -> dict[str, int]:
    records = json.loads(seed_path.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise ValueError("Seed file must contain a JSON array.")
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = {"checked": 0, "downloaded": 0, "skipped": 0, "failed": 0}
    client = httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30, follow_redirects=True)
    try:
        for record in records:
            if limit is not None and summary["checked"] >= limit:
                break
            if not isinstance(record, dict):
                summary["skipped"] += 1
                continue
            paper_id = record.get("paper_id")
            pdf_url = record.get("pdf_url")
            if not paper_id or not is_direct_pdf_candidate(str(pdf_url) if pdf_url else None):
                summary["skipped"] += 1
                continue
            summary["checked"] += 1
            target = deterministic_pdf_path(output_dir, str(paper_id))
            if not download:
                print(f"dry-run would_download paper_id={paper_id} url={pdf_url} target={target}")
                continue
            try:
                response = client.get(str(pdf_url), headers={"Accept": "application/pdf,*/*"})
                response.raise_for_status()
                if not verify_pdf_response(response):
                    print(f"failed paper_id={paper_id} reason=not_pdf url={pdf_url}")
                    summary["failed"] += 1
                    continue
                target.write_bytes(response.content)
                print(f"downloaded paper_id={paper_id} target={target}")
                summary["downloaded"] += 1
            except httpx.HTTPError as exc:
                print(f"failed paper_id={paper_id} reason={exc}")
                summary["failed"] += 1
    finally:
        client.close()
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Safely download direct TTLAB PDF URLs from seed JSON.")
    parser.add_argument("--seed", default="data/seed/ttlab_publications_discovered.json")
    parser.add_argument("--out-dir", default="data/pdfs")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--download", action="store_true", help="Actually save PDFs. Default is dry-run.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    summary = download_pdfs(Path(args.seed), Path(args.out_dir), args.limit, args.download)
    print(
        "checked={checked} downloaded={downloaded} skipped={skipped} failed={failed}".format(
            **summary
        )
    )


if __name__ == "__main__":
    main()
