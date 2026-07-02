from __future__ import annotations

import re
from typing import Any


def verify_citations(
    answer_text: str,
    retrieved_chunks: list[dict[str, Any]],
    citations: list[dict[str, Any]],
) -> dict[str, Any]:
    warnings: list[str] = []
    unsupported_claims: list[str] = []
    retrieved_by_id = {chunk["chunk_id"]: chunk for chunk in retrieved_chunks}
    if not retrieved_chunks:
        return {
            "grounding_status": "unsupported",
            "warnings": ["No retrieved chunks were available for citation grounding."],
            "unsupported_claims": ["No indexed source support was retrieved."],
        }
    if not citations:
        return {
            "grounding_status": "unsupported",
            "warnings": ["The answer has retrieved chunks but no citations."],
            "unsupported_claims": ["Answer is not tied to cited source chunks."],
        }
    for citation in citations:
        chunk_id = citation.get("chunk_id")
        if chunk_id not in retrieved_by_id:
            warnings.append(f"Citation chunk_id {chunk_id} was not in retrieved chunks.")
        for required in ["paper_id", "title", "page_start", "page_end", "snippet"]:
            if citation.get(required) in {None, ""}:
                warnings.append(f"Citation {chunk_id} is missing {required}.")
    answer_terms = set(tokenize(answer_text))
    source_terms = set()
    for citation in citations:
        source_terms.update(tokenize(str(citation.get("snippet") or "")))
    overlap = len(answer_terms.intersection(source_terms)) / max(len(answer_terms), 1)
    if overlap < 0.08:
        warnings.append("Answer has weak lexical overlap with cited snippets.")
        unsupported_claims.append("Some answer wording may not be directly supported by retrieved snippets.")
    if any("not in retrieved" in warning or "missing" in warning for warning in warnings):
        status = "partial"
    elif unsupported_claims:
        status = "partial"
    else:
        status = "grounded"
    return {"grounding_status": status, "warnings": warnings, "unsupported_claims": unsupported_claims}


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in re.findall(r"[a-zA-Z0-9]+", text) if len(token) > 2]
