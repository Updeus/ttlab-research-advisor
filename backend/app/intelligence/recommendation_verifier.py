from __future__ import annotations

from typing import Any


def verify_recommendations(
    recommendations: list[dict[str, Any]],
    retrieved_chunks_by_id: dict[str, dict[str, Any]],
    *,
    available_time: str | None = None,
) -> dict[str, Any]:
    warnings: list[str] = []
    if not recommendations:
        return {
            "grounding_status": "unsupported",
            "warnings": ["No recommendations were generated."],
        }

    has_any_citation = False
    all_recommendations_have_citations = True
    all_claims_map_to_retrieved_chunks = True
    has_inferred_or_missing_gap = False
    has_structural_support = False

    for recommendation in recommendations:
        rank = recommendation.get("rank", "?")
        citations = recommendation.get("citations") or []
        if not citations:
            all_recommendations_have_citations = False
            warnings.append(f"Recommendation {rank} has no source chunk citations.")
        else:
            has_any_citation = True

        for citation in citations:
            chunk_id = str(citation.get("chunk_id") or "")
            if chunk_id not in retrieved_chunks_by_id:
                all_claims_map_to_retrieved_chunks = False
                warnings.append(f"Recommendation {rank} cites chunk {chunk_id or 'unknown'} that was not retrieved.")

        for fact in recommendation.get("source_supported_facts") or []:
            chunk_id = str(fact.get("chunk_id") or "")
            if chunk_id not in retrieved_chunks_by_id:
                all_claims_map_to_retrieved_chunks = False
                warnings.append(f"Recommendation {rank} has a source-supported fact without a retrieved chunk.")
            else:
                has_structural_support = True

        gap = recommendation.get("identified_gap") or {}
        support_status = gap.get("support_status")
        if support_status in {"inferred_from_paper", "not_found"}:
            has_inferred_or_missing_gap = True
            if support_status == "not_found":
                warnings.append(f"Recommendation {rank} did not find explicit limitations or future work in retrieved chunks.")

        if recommendation.get("data_availability") == "unknown":
            warnings.append(f"Recommendation {rank} has unknown data availability.")

        if recommendation.get("skills_gap"):
            warnings.append(f"Recommendation {rank} has student skill gaps: {', '.join(recommendation['skills_gap'])}.")

        if is_likely_too_ambitious(available_time, recommendation):
            warnings.append(f"Recommendation {rank} may be too ambitious for the stated timeline.")

        citation_scores = [
            float(citation.get("score") or 0.0)
            for citation in citations
            if isinstance(citation, dict)
        ]
        if citation_scores and max(citation_scores) < 0.05:
            warnings.append(f"Recommendation {rank} has weak retrieval evidence.")

    if not has_any_citation or not has_structural_support:
        status = "unsupported"
    else:
        # Structural IDs and lexical source excerpts do not establish semantic
        # entailment, so automatic verification cannot report fully grounded.
        status = "partial"
        warnings.append(
            "Recommendation source links are structurally valid but semantic support remains unverified."
        )

    return {
        "grounding_status": status,
        "support_status": "support_unverified" if status == "partial" else "unsupported",
        "warnings": dedupe_preserve_order(warnings),
    }


def is_likely_too_ambitious(available_time: str | None, recommendation: dict[str, Any]) -> bool:
    timeline = (available_time or "").lower()
    difficulty = str(recommendation.get("difficulty") or "").lower()
    implementation_time = str(recommendation.get("implementation_time") or "").lower()
    if "2 week" in timeline and (difficulty == "hard" or implementation_time in {"1 month", "semester"}):
        return True
    if "1 month" in timeline and implementation_time == "semester":
        return True
    return False


def dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped
