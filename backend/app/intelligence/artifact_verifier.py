from __future__ import annotations

from typing import Any

from app.models import Paper


def verify_artifact_payload(
    artifact_type: str,
    payload: dict[str, Any],
    valid_chunk_ids: set[str],
    paper: Paper,
    *,
    source_chunk_count: int,
) -> dict[str, Any]:
    warnings: list[str] = extraction_warnings(paper, source_chunk_count)
    cited_chunk_ids = collect_cited_chunk_ids(payload)
    invalid_chunk_ids = sorted(cited_chunk_ids.difference(valid_chunk_ids))
    if invalid_chunk_ids:
        warnings.append(f"Artifact cites unknown chunks: {', '.join(invalid_chunk_ids)}.")

    generated_section_warnings = generated_content_warnings(artifact_type, payload)
    warnings.extend(generated_section_warnings)

    if artifact_type == "paper_intelligence_bundle":
        citation_status = bundle_citation_status(payload)
        support_statuses = bundle_support_statuses(payload)
    else:
        citation_status = single_artifact_citation_status(payload)
        support_statuses = single_artifact_support_statuses(payload)

    if not cited_chunk_ids:
        grounding_status = "unsupported"
    elif invalid_chunk_ids or citation_status == "weak" or any(status in {"inferred", "not_found", "suggested_by_system"} for status in support_statuses):
        grounding_status = "partial"
    else:
        grounding_status = "grounded"

    if "not_found" in support_statuses and artifact_type in {"limitations", "future_work", "paper_intelligence_bundle"}:
        if artifact_type in {"limitations", "paper_intelligence_bundle"}:
            warnings.append("No explicit limitations found.")
        if artifact_type in {"future_work", "paper_intelligence_bundle"}:
            warnings.append("No explicit future work found.")

    return {
        "grounding_status": grounding_status,
        "warnings": dedupe_preserve_order(warnings),
    }


def extraction_warnings(paper: Paper, source_chunk_count: int) -> list[str]:
    warnings: list[str] = []
    if paper.possible_scanned_pdf:
        warnings.append("Paper may be scanned or image-heavy; generated outputs may be incomplete.")
    if source_chunk_count < 3:
        warnings.append("Too few chunks are available for strong paper-level artifacts.")
    if paper.pdf_text_status not in {"extracted", "chunked"}:
        warnings.append(f"Paper text status is {paper.pdf_text_status}; generated outputs may be limited.")
    if paper.pages_with_text == 0 and paper.page_count:
        warnings.append("No extracted text pages were recorded for this paper.")
    return warnings


def generated_content_warnings(artifact_type: str, payload: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    if artifact_type == "paper_intelligence_bundle":
        extensions = payload.get("possible_extensions") or []
        if extensions:
            warnings.append("Generated extension ideas are system suggestions and require supervisor review.")
    if artifact_type == "possible_extensions":
        warnings.append("Generated extension ideas are system suggestions and require supervisor review.")
    if artifact_type == "podcast_script":
        warnings.append("Podcast script is text-only and must be reviewed before public use.")
    return warnings


def collect_cited_chunk_ids(value: Any) -> set[str]:
    chunk_ids: set[str] = set()
    if isinstance(value, dict):
        if "chunk_id" in value and value.get("chunk_id"):
            chunk_ids.add(str(value["chunk_id"]))
        for item in value.values():
            chunk_ids.update(collect_cited_chunk_ids(item))
    elif isinstance(value, list):
        for item in value:
            chunk_ids.update(collect_cited_chunk_ids(item))
    return chunk_ids


def bundle_citation_status(payload: dict[str, Any]) -> str:
    required_sections = [
        "public_summary",
        "technical_summary",
        "contribution",
        "methods",
        "required_skills",
        "evaluation_plan",
    ]
    cited_count = 0
    for section in required_sections:
        section_payload = payload.get(section) or {}
        if section_payload.get("citations"):
            cited_count += 1
    if cited_count >= 5:
        return "strong"
    if cited_count >= 2:
        return "weak"
    return "missing"


def bundle_support_statuses(payload: dict[str, Any]) -> list[str]:
    statuses: list[str] = []
    for section in ("limitations", "future_work"):
        section_payload = payload.get(section) or {}
        status = section_payload.get("support_status")
        if status:
            statuses.append(str(status))
    for extension in payload.get("possible_extensions") or []:
        status = extension.get("support_status")
        if status:
            statuses.append(str(status))
    evaluation = payload.get("evaluation_plan") or {}
    if evaluation.get("basis"):
        statuses.append(str(evaluation["basis"]))
    return statuses


def single_artifact_citation_status(payload: dict[str, Any]) -> str:
    if payload.get("support_status") == "not_found":
        return "strong"
    citations = payload.get("citations") or []
    if citations:
        return "strong"
    return "missing"


def single_artifact_support_statuses(value: Any) -> list[str]:
    statuses: list[str] = []
    if isinstance(value, dict):
        if value.get("support_status"):
            statuses.append(str(value["support_status"]))
        if value.get("basis"):
            statuses.append(str(value["basis"]))
        for child in value.values():
            statuses.extend(single_artifact_support_statuses(child))
    elif isinstance(value, list):
        for child in value:
            statuses.extend(single_artifact_support_statuses(child))
    return statuses


def dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped
