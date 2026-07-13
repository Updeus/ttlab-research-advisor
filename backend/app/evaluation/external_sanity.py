from __future__ import annotations

import argparse
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from app.indexing.chunker import build_chunks_from_extraction


EUROPE_PMC_BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest"
USER_AGENT = "ttlab-research-advisor-external-sanity/1.0 (jarod.esareesingh@my.uwi.edu)"
PINNED_DOCUMENTS: tuple[dict[str, str], ...] = (
    {
        "pmcid": "PMC4302049",
        "expected_title_fragment": "DESeq2",
        "query": "RNA sequencing fold change dispersion estimation",
    },
    {
        "pmcid": "PMC8005924",
        "expected_title_fragment": "PRISMA 2020",
        "query": "systematic review reporting guideline checklist",
    },
    {
        "pmcid": "PMC4103590",
        "expected_title_fragment": "Trimmomatic",
        "query": "Illumina sequence read trimming adapter quality",
    },
)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256_bytes(payload.encode("utf-8"))


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def first_text(root: ET.Element, names: set[str]) -> str:
    for element in root.iter():
        if local_name(element.tag) in names:
            text = normalize_space(" ".join(element.itertext()))
            if text:
                return text
    return ""


def article_identifier(root: ET.Element, kind: str) -> str | None:
    for element in root.iter():
        if local_name(element.tag) != "article-id":
            continue
        if str(element.attrib.get("pub-id-type") or "").lower() == kind.lower():
            value = normalize_space("".join(element.itertext()))
            return value or None
    return None


def license_evidence(root: ET.Element) -> tuple[str, str]:
    texts: list[str] = []
    urls: list[str] = []
    for element in root.iter():
        if local_name(element.tag) not in {"license", "license-p"}:
            continue
        text = normalize_space(" ".join(element.itertext()))
        if text:
            texts.append(text)
        for key, value in element.attrib.items():
            if key.endswith("href") and value:
                urls.append(str(value))
    joined = normalize_space(" ".join(texts))
    url = next((value for value in urls if "creativecommons.org/licenses/by/" in value.lower()), "")
    if not url:
        match = re.search(r"https?://creativecommons\.org/licenses/by/[0-9.]+/?", joined, re.IGNORECASE)
        url = match.group(0) if match else ""
    if not url:
        raise ValueError("Article does not contain machine-verifiable CC BY license evidence")
    return joined, url


def jats_pages(root: ET.Element) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    body = next((element for element in root.iter() if local_name(element.tag) == "body"), None)
    if body is None:
        raise ValueError("JATS document has no body")
    sections = [element for element in body.iter() if local_name(element.tag) == "sec"]
    if not sections:
        sections = [body]
    for index, section in enumerate(sections, start=1):
        title = next(
            (
                normalize_space(" ".join(child.itertext()))
                for child in list(section)
                if local_name(child.tag) == "title"
            ),
            "",
        )
        paragraphs = [
            normalize_space(" ".join(element.itertext()))
            for element in section.iter()
            if local_name(element.tag) == "p"
        ]
        text = "\n".join(value for value in ([title] + paragraphs) if value)
        if text:
            pages.append({"page_number": index, "text": text})
    if not pages:
        raise ValueError("JATS document has no readable section text")
    return pages


def parse_open_article(xml_bytes: bytes, expected: dict[str, str]) -> dict[str, Any]:
    if b"<!DOCTYPE" in xml_bytes.upper() or b"<!ENTITY" in xml_bytes.upper():
        raise ValueError("DTD/entity-bearing XML is rejected")
    root = ET.fromstring(xml_bytes)
    pmcid = article_identifier(root, "pmc") or expected["pmcid"].removeprefix("PMC")
    normalized_pmcid = pmcid if pmcid.upper().startswith("PMC") else f"PMC{pmcid}"
    if normalized_pmcid.upper() != expected["pmcid"].upper():
        raise ValueError(f"Expected {expected['pmcid']}, received {normalized_pmcid}")
    title = first_text(root, {"article-title"})
    if expected["expected_title_fragment"].lower() not in title.lower():
        raise ValueError(f"Title mismatch for {expected['pmcid']}: {title}")
    license_text, license_url = license_evidence(root)
    pages = jats_pages(root)
    paper_id = expected["pmcid"].lower()
    chunks = build_chunks_from_extraction({"paper_id": paper_id, "pages": pages})
    return {
        "pmcid": expected["pmcid"],
        "paper_id": paper_id,
        "title": title,
        "doi": article_identifier(root, "doi"),
        "license": "CC BY",
        "license_url": license_url,
        "license_evidence_excerpt": license_text[:500],
        "source_url": f"{EUROPE_PMC_BASE}/{expected['pmcid']}/fullTextXML",
        "xml_sha256": sha256_bytes(xml_bytes),
        "xml_bytes": len(xml_bytes),
        "section_count": len(pages),
        "word_count": sum(len(page["text"].split()) for page in pages),
        "chunk_count": len(chunks),
        "chunks": chunks,
        "query": expected["query"],
    }


def token_score(query: str, text: str) -> float:
    tokens = set(re.findall(r"[a-z0-9]+", query.lower()))
    haystack = set(re.findall(r"[a-z0-9]+", text.lower()))
    return len(tokens & haystack) / max(len(tokens), 1)


def external_retrieval_sanity(documents: list[dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for document in documents:
        ranked = sorted(
            (
                {
                    "paper_id": candidate["paper_id"],
                    "score": max(
                        (token_score(document["query"], chunk["text"]) for chunk in candidate["chunks"]),
                        default=0.0,
                    ),
                }
                for candidate in documents
            ),
            key=lambda row: (-row["score"], row["paper_id"]),
        )
        rows.append(
            {
                "query": document["query"],
                "expected_paper_id": document["paper_id"],
                "top_paper_id": ranked[0]["paper_id"],
                "top_score": round(float(ranked[0]["score"]), 6),
                "top_1_match": ranked[0]["paper_id"] == document["paper_id"],
                "ranking": ranked,
            }
        )
    return {
        "method": "lowercase_alphanumeric_set_overlap_smoke_check",
        "case_count": len(rows),
        "top_1_matches": sum(bool(row["top_1_match"]) for row in rows),
        "cases": rows,
        "claim_boundary": (
            "A format-compatibility and lexical-discrimination sanity check on three Europe PMC CC BY documents; "
            "not TTLAB effectiveness evidence and not broad external validation."
        ),
    }


def acquire(
    output_dir: Path,
    *,
    timeout_seconds: float = 45.0,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = output_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    own_client = client is None
    active_client = client or httpx.Client(
        timeout=httpx.Timeout(timeout_seconds),
        follow_redirects=False,
        headers={"User-Agent": USER_AGENT, "Accept": "application/xml"},
    )
    documents: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []
    try:
        for expected in PINNED_DOCUMENTS:
            url = f"{EUROPE_PMC_BASE}/{expected['pmcid']}/fullTextXML"
            try:
                response = active_client.get(url)
                response.raise_for_status()
                content_type = response.headers.get("content-type", "").lower()
                if "xml" not in content_type:
                    raise ValueError(f"Unexpected content type: {content_type or 'missing'}")
                parsed = parse_open_article(response.content, expected)
                raw_path = raw_dir / f"{expected['pmcid']}.xml"
                raw_path.write_bytes(response.content)
                documents.append(parsed)
                attempts.append({"pmcid": expected["pmcid"], "status": "acquired", "http_status": response.status_code})
            except Exception as exc:
                attempts.append(
                    {
                        "pmcid": expected["pmcid"],
                        "status": "failed",
                        "error_type": type(exc).__name__,
                        "error": str(exc)[:500],
                    }
                )
    finally:
        if own_client:
            active_client.close()

    public_documents = [{key: value for key, value in row.items() if key not in {"chunks", "query"}} for row in documents]
    result = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "source": {
            "name": "Europe PMC Articles RESTful API",
            "base_url": EUROPE_PMC_BASE,
            "open_access_policy_url": "https://europepmc.org/downloads/openaccess",
            "api_documentation_url": "https://europepmc.org/RestfulWebService",
            "selection": "three pinned PMCID records; each fullTextXML response must carry CC BY evidence",
        },
        "status": "complete" if len(documents) == len(PINNED_DOCUMENTS) else "attempted_with_failures",
        "attempts": attempts,
        "documents": public_documents,
        "sanity_check": external_retrieval_sanity(documents) if documents else None,
        "redistribution": {
            "raw_xml_location": str(raw_dir),
            "raw_xml_in_release": False,
            "reason": (
                "Raw XML is retained only as an ignored local acquisition cache. The sanitized release contains "
                "source IDs, license evidence, counts, and hashes so each recipient reacquires from the official API."
            ),
        },
        "limitations": [
            "Three life-science articles do not represent the disciplinary or linguistic diversity of scholarly literature.",
            "The smoke check tests format compatibility and trivial lexical discrimination, not transfer of TTLAB quality metrics.",
            "Availability and article license statements may change; reproduction revalidates the license embedded in each response.",
        ],
    }
    result["logical_manifest_sha256"] = canonical_sha256({key: value for key, value in result.items() if key != "generated_at"})
    manifest_path = output_dir / "external_sanity_manifest.json"
    manifest_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Acquire and validate a separated Europe PMC CC BY sanity corpus.")
    parser.add_argument("--out-dir", type=Path, default=Path("artifacts/phase6/external_sanity"))
    parser.add_argument("--timeout", type=float, default=45.0)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    result = acquire(args.out_dir, timeout_seconds=args.timeout)
    print(
        json.dumps(
            {
                "status": result["status"],
                "documents": len(result["documents"]),
                "top_1_matches": (result.get("sanity_check") or {}).get("top_1_matches", 0),
                "manifest": str(args.out_dir / "external_sanity_manifest.json"),
            },
            indent=2,
        )
    )
    if result["status"] != "complete":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
