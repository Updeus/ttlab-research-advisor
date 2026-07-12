#!/usr/bin/env python3
"""Build the verified silver set from the preserved creation pass.

This script performs no retrieval. Its fixed revision map records judgments made
after reopening source chunks and metadata in a fixed-seed shuffled order.
"""

from __future__ import annotations

import copy
import json
import random
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data/evaluation/retrieval_silver_create_v1.jsonl"
OUTPUT = ROOT / "data/evaluation/retrieval_silver_v1.jsonl"
SHUFFLE_SEED = 20260712
VERIFIED_AT = "2026-07-12T22:23:17Z"


REVISIONS: dict[str, dict[str, Any]] = {
    "ret-create-006": {
        "add_evidence": [
            {
                "paper_id": "using-natural-language-processing-to-correlate-university-curricula-with-6838a3b6",
                "chunk_id": "using-natural-language-processing-to-correlate-university-curricula-with-6838a3b6-chunk-0003-c6666cec71b8",
                "page_start": 3,
                "page_end": 3,
                "section": "Methodology",
                "evidence_summary": "The implemented extraction stage uses SkillNER, a spaCy-based NER pipeline, to normalize technical and soft skills before topic analysis.",
            }
        ],
        "uncertainty": "low",
        "fields": ["annotation_uncertainty", "supporting_evidence"],
        "finding": "The creation evidence described the broad pipeline but did not cite the chunk that explicitly confirms SkillNER was used.",
        "resolution": "Added the page-3 SkillNER implementation passage; query, category, paper relevance, and split remain unchanged.",
    },
    "ret-create-009": {
        "replace_evidence": [
            {
                "paper_id": "design-and-evaluation-of-a-mobile-medication-management-system-for-vulne-2c0301ce",
                "chunk_id": "design-and-evaluation-of-a-mobile-medication-management-system-for-vulne-2c0301ce-chunk-0001-b23ace62200e",
                "page_start": 1,
                "page_end": 2,
                "section": "Unknown",
                "evidence_summary": "The paper describes prescription-label scanning for auto-fill, expiry-ordered medication stock, security questions for edits, and an offline-first design; verification codes and contact alerts are identified as planned.",
            },
            {
                "paper_id": "design-and-evaluation-of-a-mobile-medication-management-system-for-vulne-2c0301ce",
                "chunk_id": "design-and-evaluation-of-a-mobile-medication-management-system-for-vulne-2c0301ce-chunk-0003-9c22b6b1adb5",
                "page_start": 3,
                "page_end": 4,
                "section": "Unknown",
                "evidence_summary": "The implemented workflows include expiry-ordered stock, soft deletion, and security-question gates; the backend is FastAPI, while stronger OAuth/JWT protection and OCR parsing are described as planned.",
            },
        ],
        "uncertainty": "low",
        "fields": ["annotation_uncertainty", "supporting_evidence"],
        "finding": "The creation summary blurred implemented safeguards with planned OCR/backend security work.",
        "resolution": "Replaced the evidence summaries with two passages that explicitly separate implemented and planned features.",
    },
    "ret-create-031": {
        "add_evidence": [
            {
                "paper_id": "crop-price-prediction-a-comparison-of-the-recursive-and-direct-forecasti-5e0aaa71",
                "chunk_id": "crop-price-prediction-a-comparison-of-the-recursive-and-direct-forecasti-5e0aaa71-chunk-0004-1e6316e65b60",
                "page_start": 3,
                "page_end": 4,
                "section": "Methodology",
                "evidence_summary": "The complete multi-step table and discussion show recursive wins for tomato, ginger, and cabbage and direct wins for the other seven crops, with per-crop MAPE values.",
            }
        ],
        "uncertainty": "low",
        "fields": ["annotation_uncertainty", "supporting_evidence"],
        "finding": "The creation evidence named the seven direct wins but did not explicitly support the three recursive wins needed for a ten-crop comparison.",
        "resolution": "Added the page-3-to-4 results table/discussion passage covering all ten crops.",
    },
    "ret-create-037": {
        "add_relevant_papers": ["weed-and-water-stress-detection-using-drone-video-03885d3b"],
        "add_evidence": [
            {
                "paper_id": "weed-and-water-stress-detection-using-drone-video-03885d3b",
                "chunk_id": "weed-and-water-stress-detection-using-drone-video-03885d3b-chunk-0000-90b1478af03b",
                "page_start": 1,
                "page_end": 2,
                "section": "Abstract",
                "evidence_summary": "The FAAIR study applies UAV data and machine-learning models to tropical-island weed detection and water-stress estimation, motivated by climate and food-security concerns.",
            }
        ],
        "uncertainty": "medium",
        "fields": ["annotation_uncertainty", "relevant_paper_ids", "supporting_evidence"],
        "finding": "A shuffled inventory check found an additional directly relevant Caribbean precision-agriculture paper omitted during creation.",
        "resolution": "Added the weed-and-water-stress paper and its abstract evidence; retained medium uncertainty because broad-intent set completeness remains harder than exact lookup.",
    },
    "ret-create-038": {
        "add_relevant_papers": [
            "improving-power-generation-efficiency-using-deep-neural-networks-a98f1c29",
            "power-grid-fault-detection-using-an-amr-network-0c474959",
        ],
        "add_evidence": [
            {
                "paper_id": "improving-power-generation-efficiency-using-deep-neural-networks-a98f1c29",
                "chunk_id": "improving-power-generation-efficiency-using-deep-neural-networks-a98f1c29-chunk-0000-79f80a434b4e",
                "page_start": 1,
                "page_end": 2,
                "section": "Abstract",
                "evidence_summary": "Smart-meter readings and deep neural networks are used to estimate network loading and improve capacity planning through load forecasting.",
            },
            {
                "paper_id": "power-grid-fault-detection-using-an-amr-network-0c474959",
                "chunk_id": "power-grid-fault-detection-using-an-amr-network-0c474959-chunk-0000-a666b11c558e",
                "page_start": 1,
                "page_end": 1,
                "section": "Abstract",
                "evidence_summary": "The paper uses AMR meter reports and power-outage notifications for grid fault detection without requiring a full AMI deployment.",
            },
        ],
        "uncertainty": "medium",
        "fields": ["annotation_uncertainty", "relevant_paper_ids", "supporting_evidence"],
        "finding": "The creation set omitted one additional load-forecasting paper and one additional AMR fault-detection paper that match the broad query's named functions.",
        "resolution": "Added both papers with first-page evidence and retained medium uncertainty for the broad-intent judgment.",
    },
    "ret-create-041": {
        "question": "Which papers address podcast presentation of academic publications and personalized audio from print news, and how do their source domains and workflows differ?",
        "replace_evidence": [
            {
                "paper_id": "automating-the-collection-display-summarization-and-podcasting-of-academ-498c837a",
                "chunk_id": "automating-the-collection-display-summarization-and-podcasting-of-academ-498c837a-chunk-0000-39b2a5f562ad",
                "page_start": 1,
                "page_end": 1,
                "section": "Abstract",
                "evidence_summary": "The academic-research platform addresses publication visibility through lay summaries and optional podcast presentation; the evidence does not by itself establish a fully automated audio pipeline.",
            },
            {
                "paper_id": "generating-personalized-news-podcasts-from-print-media-for-those-on-the--11532982",
                "chunk_id": "generating-personalized-news-podcasts-from-print-media-for-those-on-the--11532982-chunk-0000-a8ab61a355bc",
                "page_start": 1,
                "page_end": 1,
                "section": "Abstract",
                "evidence_summary": "The news system converts trusted print-media content into personalized audio for time-constrained and blind listeners.",
            },
        ],
        "uncertainty": "low",
        "fields": ["question", "supporting_evidence"],
        "finding": "The creation wording could imply that the academic predecessor automated spoken-summary generation, which the cited abstract alone does not prove.",
        "resolution": "Narrowed the wording to podcast presentation and made the evidence summary explicitly conservative about automation.",
    },
}


def verification_rationale(case: dict[str, Any]) -> str:
    category = case["category"]
    if category == "unanswerable_out_of_corpus":
        return "Expanded direct corpus-text and title checks found no study matching the requested domain; incidental bibliography terms did not constitute a relevant paper."
    if category == "hard_negative":
        return "Reopened the relevant and distractor source passages; the query's domain qualifier cleanly separates the directly relevant paper from the lexical hard negative."
    if category == "title_author_venue":
        return "Reopened the cited first-page chunk and current SQLite metadata; title, author list, year, venue, paper ID, and pages agree with the creation label."
    return "Reopened every cited SQLite chunk and page and rechecked the question, category, relevance set, evidence summary, answerability, and split; the creation label is directly supported."


def build() -> list[dict[str, Any]]:
    source_cases = [json.loads(line) for line in SOURCE.read_text(encoding="utf-8").splitlines() if line.strip()]
    random.Random(SHUFFLE_SEED).shuffle(source_cases)
    final_cases: list[dict[str, Any]] = []
    for shuffled_position, source in enumerate(source_cases, start=1):
        source_case_id = source["case_id"]
        case = copy.deepcopy(source)
        creation_annotation = {
            "reviewer_id": case.pop("reviewer_id"),
            "reviewer_type": case.pop("reviewer_type"),
            "pass": case.pop("pass"),
            "timestamp": case["timestamp"],
        }
        case["source_case_id"] = source_case_id
        case["case_id"] = source_case_id.replace("ret-create-", "ret-silver-")
        revision = REVISIONS.get(source_case_id)
        if revision:
            if "question" in revision:
                case["question"] = revision["question"]
            if "replace_evidence" in revision:
                case["supporting_evidence"] = copy.deepcopy(revision["replace_evidence"])
            case["supporting_evidence"].extend(copy.deepcopy(revision.get("add_evidence", [])))
            case["relevant_paper_ids"].extend(revision.get("add_relevant_papers", []))
            case["annotation_uncertainty"] = revision["uncertainty"]
            case["decision"] = "revise"
            case["verification_rationale"] = revision["finding"]
            case["disagreement"] = {
                "fields": revision["fields"],
                "creation_label": "See source_case_id in the preserved create-pass JSONL.",
                "verification_finding": revision["finding"],
            }
            case["adjudication"] = {
                "status": "resolved_by_ai_verifier",
                "resolution": revision["resolution"],
            }
        else:
            case["decision"] = "agree"
            case["verification_rationale"] = verification_rationale(case)
            case["disagreement"] = None
            case["adjudication"] = {
                "status": "not_needed",
                "resolution": "Creation label retained after independent source reinspection.",
            }
        case["relevance_judgments"] = [
            {"paper_id": paper_id, "grade": 2, "label": "directly_relevant"}
            for paper_id in case["relevant_paper_ids"]
        ] + [
            {"paper_id": paper_id, "grade": 0, "label": "hard_negative"}
            for paper_id in case["distractor_paper_ids"]
        ]
        case["creation_annotation"] = creation_annotation
        case["verifier_id"] = "codex-ai-review"
        case["reviewer_type"] = "ai"
        case["pass"] = "verify"
        case["shuffled_position"] = shuffled_position
        case["shuffle_seed"] = SHUFFLE_SEED
        case["timestamp"] = VERIFIED_AT
        final_cases.append(case)
    return final_cases


def main() -> None:
    cases = build()
    OUTPUT.write_text(
        "".join(json.dumps(case, ensure_ascii=False, separators=(",", ":")) + "\n" for case in cases),
        encoding="utf-8",
    )
    print(f"wrote={OUTPUT} cases={len(cases)} seed={SHUFFLE_SEED}")


if __name__ == "__main__":
    main()
