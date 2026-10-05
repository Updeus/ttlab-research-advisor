from __future__ import annotations

import re
from typing import Any

_MARKER_RE = re.compile(r"\[([^\[\]]+)\]")
_BOILERPLATE_PREFIXES = (
    "based on the indexed ttlab",
    "the strongest matching papers are",
    "the most relevant sources are",
    "this is an authorship-based signal",
)


def verify_citations(
    answer_text: str,
    retrieved_chunks: list[dict[str, Any]],
    citations: list[dict[str, Any]],
) -> dict[str, Any]:
    """Perform structural claim/source checks without asserting entailment.

    Lexical overlap and valid source markers can establish only that a claim has
    a plausible cited support path.  They cannot establish semantic entailment,
    so the strongest claim-level classification is ``support_unverified``.
    """

    warnings: list[str] = []
    unsupported_claims: list[str] = []
    retrieved_by_id = {str(chunk["chunk_id"]): chunk for chunk in retrieved_chunks}
    citation_by_id = {str(citation.get("chunk_id") or ""): citation for citation in citations}
    source_aliases = {
        f"S{index}": str(citation.get("chunk_id") or "")
        for index, citation in enumerate(citations, start=1)
    }
    if not retrieved_chunks or not citations:
        return {
            "grounding_status": "unsupported",
            "support_status": "unsupported",
            "warnings": ["No structurally verifiable cited source support was available."],
            "unsupported_claims": ["No indexed source support was structurally tied to the answer."],
            "claim_support": [],
            "used_chunk_ids": [],
        }

    for citation in citations:
        chunk_id = str(citation.get("chunk_id") or "")
        if chunk_id not in retrieved_by_id:
            warnings.append(f"Citation chunk_id {chunk_id or '<missing>'} was not in retrieved chunks.")
        for required in ("paper_id", "title", "snippet"):
            if citation.get(required) in {None, ""}:
                warnings.append(f"Citation {chunk_id or '<missing>'} is missing {required}.")

    claim_support: list[dict[str, Any]] = []
    used_chunk_ids: list[str] = []
    for claim in extract_claims(answer_text):
        marker_values = []
        for marker in _MARKER_RE.findall(claim):
            # Models also emit grouped prompt aliases, e.g. [S3, S5]. Keep
            # their original retrieval numbering rather than reindexing the
            # filtered list of citations returned after verification.
            if re.fullmatch(r"\s*S\d+(?:\s*[,;]\s*S\d+)*\s*", marker, re.IGNORECASE):
                marker_values.extend(value.strip().upper() for value in re.split(r"[,;]", marker))
            else:
                marker_values.append(marker)
        resolved_ids: list[str] = []
        for marker in marker_values:
            marker = marker.strip()
            chunk_id = source_aliases.get(marker, marker if marker in citation_by_id else "")
            if chunk_id and chunk_id in retrieved_by_id and chunk_id not in resolved_ids:
                resolved_ids.append(chunk_id)
        claim_terms = set(tokenize(_MARKER_RE.sub("", claim)))
        citation_support: list[dict[str, Any]] = []
        for chunk_id in resolved_ids:
            chunk = retrieved_by_id[chunk_id]
            source_text = str(chunk.get("text") or chunk.get("snippet") or "")
            overlap = lexical_overlap(claim_terms, set(tokenize(source_text)))
            citation_support.append(
                {
                    "chunk_id": chunk_id,
                    "lexical_overlap": round(overlap, 4),
                    "classification": "support_unverified" if overlap >= 0.08 else "unsupported",
                    "entailment_verified": False,
                }
            )
        supported_ids = [
            item["chunk_id"]
            for item in citation_support
            if item["classification"] == "support_unverified"
        ]
        best_overlap = max((float(item["lexical_overlap"]) for item in citation_support), default=0.0)
        classification = "support_unverified" if supported_ids else "unsupported"
        if classification == "support_unverified":
            for chunk_id in supported_ids:
                if chunk_id not in used_chunk_ids:
                    used_chunk_ids.append(chunk_id)
        else:
            unsupported_claims.append(claim)
        claim_support.append(
            {
                "claim": claim,
                "classification": classification,
                "cited_chunk_ids": resolved_ids,
                "supporting_chunk_ids": supported_ids,
                "citation_support": citation_support,
                "lexical_overlap": round(best_overlap, 4),
                "entailment_verified": False,
            }
        )

    if not claim_support:
        unsupported_claims.append("No substantive answer claims were available for structural verification.")
    if unsupported_claims:
        warnings.append("One or more answer claims lacked a structurally usable source citation.")
    if used_chunk_ids:
        warnings.append(
            "Cited claims are classified support_unverified; structural and lexical checks do not establish entailment."
        )
    support_status = "support_unverified" if used_chunk_ids else "unsupported"
    # Do not report fully grounded based on lexical checks alone.
    grounding_status = "partial" if used_chunk_ids else "unsupported"
    return {
        "grounding_status": grounding_status,
        "support_status": support_status,
        "warnings": warnings,
        "unsupported_claims": unsupported_claims,
        "claim_support": claim_support,
        "used_chunk_ids": used_chunk_ids,
    }


def extract_claims(answer_text: str) -> list[str]:
    claims: list[str] = []
    for line in answer_text.splitlines():
        normalized = re.sub(r"\s+", " ", line).strip(" -*\t")
        if not normalized:
            continue
        pieces = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", normalized)
        for piece in pieces:
            claim = piece.strip()
            lowered = claim.lower()
            if len(tokenize(claim)) < 4 or lowered.startswith(_BOILERPLATE_PREFIXES):
                continue
            claims.append(claim)
    return claims


def lexical_overlap(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left.intersection(right)) / len(left)


def tokenize(text: str) -> list[str]:
    stopwords = {
        "about", "also", "and", "are", "based", "from", "into", "paper", "papers",
        "source", "sources", "that", "the", "their", "these", "this", "with",
    }
    return [
        token.lower()
        for token in re.findall(r"[a-zA-Z0-9]+", text)
        if len(token) > 2 and token.lower() not in stopwords
    ]
