from __future__ import annotations

from typing import Any


def generate_podcast_script(
    bundle: dict[str, Any],
    source_pack: list[dict[str, Any]],
    *,
    audience: str = "general public",
) -> dict[str, Any]:
    citations = podcast_citations(bundle, source_pack)
    warnings: list[str] = []
    if len(source_pack) < 4:
        warnings.append("Podcast script is limited because few source chunks were available.")
    if not citations:
        warnings.append("Podcast script has no usable source citations.")

    title = bundle.get("paper_title") or "TTLAB Research Paper"
    public_summary = text_from_section(bundle.get("public_summary"))
    contribution = text_from_section(bundle.get("contribution"))
    methods = text_from_section(bundle.get("methods"))
    limitations = text_from_section(bundle.get("limitations"))
    future_work = text_from_section(bundle.get("future_work"))
    extensions = bundle.get("possible_extensions") or []
    extension_text = extensions[0]["summary"] if extensions else "A practical next step is to review the cited paper evidence and scope a small follow-up project."

    script = [
        {
            "speaker": "Host",
            "text": f"Welcome to TTLAB Research Briefs. Today we are looking at {title}.",
        },
        {
            "speaker": "Research Explainer",
            "text": public_summary,
        },
        {
            "speaker": "Host",
            "text": "What is the main research contribution?",
        },
        {
            "speaker": "Research Explainer",
            "text": contribution,
        },
        {
            "speaker": "Host",
            "text": "How did the researchers approach the problem?",
        },
        {
            "speaker": "Research Explainer",
            "text": methods,
        },
        {
            "speaker": "Host",
            "text": "What should listeners keep in mind about limitations or future work?",
        },
        {
            "speaker": "Research Explainer",
            "text": f"{limitations} {future_work}",
        },
        {
            "speaker": "Host",
            "text": "And what could a student build from here?",
        },
        {
            "speaker": "Research Explainer",
            "text": extension_text,
        },
        {
            "speaker": "Host",
            "text": "That is a source-cited draft, not a reviewed production script. Check the cited paper chunks before using it publicly.",
        },
    ]

    return {
        "episode_title": f"TTLAB Research Brief: {title}",
        "short_description": f"An accessible, AI-assisted draft explaining the paper '{title}' with cited source chunks.",
        "audience": audience,
        "duration_target": "3-5 minutes",
        "speakers": ["Host", "Research Explainer"],
        "script": script,
        "cited_source_papers": [
            {
                "paper_id": bundle.get("paper_id"),
                "title": title,
            }
        ],
        "citations": citations,
        "warnings": warnings,
        "review_status": "needs_review",
    }


def text_from_section(section: Any) -> str:
    if not isinstance(section, dict):
        return "The selected source chunks did not provide enough detail for this section."
    text = str(section.get("text") or "").strip()
    return text or "The selected source chunks did not provide enough detail for this section."


def podcast_citations(bundle: dict[str, Any], source_pack: list[dict[str, Any]]) -> list[dict[str, Any]]:
    citations: list[dict[str, Any]] = []
    for key in ("public_summary", "contribution", "methods", "limitations", "future_work", "evaluation_plan"):
        section = bundle.get(key)
        if isinstance(section, dict):
            citations.extend(section.get("citations") or [])
    for extension in bundle.get("possible_extensions") or []:
        citations.extend(extension.get("citations") or [])
    if not citations:
        citations = [
            {
                "paper_id": source["paper_id"],
                "title": source["title"],
                "chunk_id": source["chunk_id"],
                "section": source.get("section"),
                "page_start": source.get("page_start"),
                "page_end": source.get("page_end"),
                "snippet": source.get("snippet", ""),
            }
            for source in source_pack[:3]
        ]
    return dedupe_citations(citations)


def dedupe_citations(citations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for citation in citations:
        chunk_id = str(citation.get("chunk_id") or "")
        if not chunk_id or chunk_id in seen:
            continue
        seen.add(chunk_id)
        deduped.append(citation)
    return deduped
