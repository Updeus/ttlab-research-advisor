#!/usr/bin/env python3
"""Remap reviewed retrieval evidence to the frozen 735-chunk corpus.

This is not a retrieval run.  Each choice below records the chunk index selected
after reopening the same-paper, page-overlapping source candidates.  The script
will run only against the exact reviewed chunk inventory, copies authoritative
page/section/hash fields from SQLite, and preserves the original create-pass
semantic labels and timestamps.  The generated audit log retains every stale
pre-rechunk evidence record and the reviewer note behind the replacement.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "data/evaluation/retrieval_silver_create_v1.jsonl"
DATABASE = ROOT / "data/papers.db"
AUDIT = ROOT / "data/evaluation/retrieval_silver_remap_v1.json"
ORIGINAL_DATASET_SHA256 = "c450ea84da13fac1e822d82619ae7ed4b4d6d0a58ca7969223d30f35b1b00199"
EXPECTED_CHUNK_COUNT = 735
EXPECTED_CHUNK_INVENTORY_SHA256 = "29c21402bfe69894a358edfbf8f3c9c5c7a59740c5e16425baf2251ad2aebd88"
REMAPPED_AT = "2026-07-12T23:15:08Z"
EXCLUDED_MISMATCHED_PAPERS = {
    "vector-search-performance-enhancements-on-limited-memory-edge-devices-cdd944e8",
    "pricing-esim-services-ecosystem-challenges-and-opportunities-93b2f94f",
}


# Exact per-evidence selections made after inspecting current source text and
# all same-paper chunks overlapping the original page range.  Values are
# current chunk_index values, not lexical ranks.
CHOICES: dict[str, list[int]] = {
    "ret-create-001": [2],
    "ret-create-002": [0],
    "ret-create-003": [3],
    "ret-create-004": [7],
    "ret-create-005": [5],
    "ret-create-006": [2],
    "ret-create-007": [2, 4],
    "ret-create-008": [1, 5],
    "ret-create-009": [3],
    "ret-create-010": [5, 6],
    "ret-create-011": [5],
    "ret-create-012": [5],
    "ret-create-013": [3],
    "ret-create-014": [4],
    "ret-create-015": [3],
    "ret-create-016": [6],
    "ret-create-017": [5],
    "ret-create-018": [6],
    "ret-create-019": [5],
    "ret-create-020": [6],
    "ret-create-021": [0],
    "ret-create-022": [0],
    "ret-create-023": [0],
    "ret-create-024": [0],
    "ret-create-025": [0],
    "ret-create-026": [0],
    "ret-create-027": [0, 1],
    "ret-create-028": [0],
    "ret-create-029": [0],
    "ret-create-030": [0],
    "ret-create-031": [5],
    "ret-create-032": [5, 6],
    "ret-create-033": [1, 3],
    "ret-create-034": [0, 4],
    "ret-create-035": [0, 0],
    "ret-create-036": [0, 0],
    "ret-create-037": [0, 0, 0, 0],
    "ret-create-038": [0, 0, 0, 0],
    "ret-create-039": [6, 0, 0],
    "ret-create-040": [0, 0, 0, 0],
    "ret-create-041": [0, 0],
    "ret-create-042": [0, 0, 0, 0],
    "ret-create-043": [0],
    "ret-create-044": [0],
    "ret-create-045": [0],
    "ret-create-046": [2],
}


REVIEW_NOTES: dict[str, list[str]] = {
    "ret-create-001": ["Selected the methodology passage stating the literal total of 23 technical machine manuals."],
    "ret-create-002": ["Selected the first-page passage naming Qwen3-Embedding-0.6B, PostgreSQL, and LangChain pgVector."],
    "ret-create-003": ["Selected the results passage that varies alpha from 0.1 to 0.9 and reports alpha=0.5; adjacent overlap lacked the complete finding."],
    "ret-create-004": ["Selected the results passage containing all three University-only accuracies; the overlapping methodology chunk did not contain the full result."],
    "ret-create-005": ["Selected the resource table/discussion passage containing 4.65% CPU, 353.7 MB memory, 4.68 mAh, and the 67-minute trial."],
    "ret-create-006": ["Selected the single methodology passage covering scraping, preprocessing, SkillNER, and LDA; the next chunk only expands later stages."],
    "ret-create-007": ["Selected the architecture passage containing the ingestion layer and all three agents.", "Selected the implementation passage explicitly naming ChromaDB retrieval and Llama 3.1 diagnostics."],
    "ret-create-008": ["Selected the branching passage explaining that respondents see only applicable questions.", "Selected the beta-response passage specifying expansion and zero-response leaf pruning."],
    "ret-create-009": ["Selected the implementation passage containing OCR, expiry ordering, soft deletion, security questions, FastAPI, and offline SQLite; the verification pass remains responsible for implemented-versus-planned adjudication."],
    "ret-create-010": ["Selected the passage connecting LiDAR-derived DBH prediction to species-specific allometric biomass equations.", "Selected the numerical-results passage reporting detected trees and model-derived DBH/AGB calculations."],
    "ret-create-011": ["Selected the discussion passage reporting the precision leader, recall leader, and F1 tie."],
    "ret-create-012": ["Selected the conclusion passage naming seven direct-strategy wins and recursion's computation-time advantage."],
    "ret-create-013": ["Selected the passage reporting canopy-area/width R-squared values and explaining poor height estimation in dense canopy."],
    "ret-create-014": ["Selected the results/discussion passage containing all four percentage MAE reductions."],
    "ret-create-015": ["Selected the results boundary passage containing test R-squared 0.919 and the two leading wave-period importances."],
    "ret-create-016": ["Selected the overlapping limitations passage containing corpus, embedding, BERTScore/human-review, and RTX 4050 constraints."],
    "ret-create-017": ["Selected the discussion/limitations passage containing OCR, history, notification, caregiver, testing, and planned enhancement limitations."],
    "ret-create-018": ["Selected the conclusion passage explicitly covering education-level, Caribbean-sample, and thematic underrepresentation bias."],
    "ret-create-019": ["Selected the limitations passage stating subsample-CV bias, unoptimized LSH meta-parameters, stratification, and local adaptation."],
    "ret-create-020": ["Selected the future-work passage covering industrial data, knowledge-base expansion, HR/safety/CMMS, interfaces, ethics, and cybersecurity."],
    "ret-create-021": ["Selected the first-page byline/abstract; venue remains checked separately against SQLite metadata."],
    "ret-create-022": ["Selected the first-page byline/abstract; venue remains checked separately against SQLite metadata."],
    "ret-create-023": ["Selected the first-page byline/abstract spanning pages 1-2; venue remains checked separately against SQLite metadata."],
    "ret-create-024": ["Selected the first-page byline/abstract; venue remains checked separately against SQLite metadata."],
    "ret-create-025": ["Selected the first-page byline/abstract; venue remains checked separately against SQLite metadata."],
    "ret-create-026": ["Selected the abstract passage directly describing weighted school-discipline analytics and planning dashboard."],
    "ret-create-027": ["Selected the abstract passage introducing XGBoost-derived coastal-vulnerability weights.", "Selected the introduction/method boundary passage explicitly describing SHAP interpretation of ecological and geomorphic protection."],
    "ret-create-028": ["Selected the first-page passage that jointly names eligibility, segmentation, and supervised adoption prediction."],
    "ret-create-029": ["Selected the first-page passage describing on-device anomaly detection, no cloud sharing, and SMS alerts."],
    "ret-create-030": ["Selected the first-page passage linking the released tropical-crop imagery to SIDS food security and data scarcity."],
    "ret-create-031": ["Retained the create-pass conclusion passage naming seven direct wins and recursion's time advantage; the verification pass adds the complete ten-crop table passage."],
    "ret-create-032": ["Selected the discussion passage containing precision/recall/F1 trade-offs.", "Selected the conclusion-overlap passage supporting unanswerable-question performance and task-dependent choice."],
    "ret-create-033": ["Selected the introduction/literature overlap summarizing traditional-versus-DNN error and runtime trade-offs.", "Selected the results passage reporting DNN-W3 2.64%, stable sub-3% DNN-SA, and 400-epoch performance."],
    "ret-create-034": ["Selected the first-page study comparison and MAE framing.", "Selected the results/discussion passage reporting lowest MAE and reductions against all four baselines."],
    "ret-create-035": ["Selected the school-discipline abstract describing analytics and planning.", "Selected the curriculum-alignment first-page abstract rather than the lexically stronger literature overlap."],
    "ret-create-036": ["Selected the medication-app abstract explicitly describing vulnerable users and offline use.", "Selected the travel-app abstract explicitly describing on-device operation without cloud sharing."],
    "ret-create-037": ["Selected the tropical-crop abstract.", "Selected the cocoa-biomass abstract.", "Selected the crop-price abstract.", "Selected the agricultural-market-price abstract."],
    "ret-create-038": ["Selected the EV-demand first-page passage.", "Selected the load-forecasting abstract.", "Selected the renewable-energy abstract.", "Selected the AMR fault-management abstract."],
    "ret-create-039": ["Selected the academic-publication discussion passage that proposes future RAG retrieval.", "Selected the factory-maintenance abstract.", "Selected the machine-manual RAG abstract rather than the adjacent literature overlap."],
    "ret-create-040": ["Selected the telecom-upsell abstract.", "Selected the eligibility-aware banking abstract.", "Selected the forgotten-basket abstract.", "Selected the long-term-profit abstract."],
    "ret-create-041": ["Selected the academic-publication first-page abstract.", "Selected the print-news audio first-page abstract."],
    "ret-create-042": ["Selected the crop-price abstract.", "Selected the agricultural-market-price abstract.", "Selected the energy-indicator foreign-exchange abstract.", "Selected the electricity-load abstract."],
    "ret-create-043": ["Selected the academic-publication first-page passage establishing the source domain and podcast presentation."],
    "ret-create-044": ["Selected the agricultural-market-price first-page passage stating 25 products and monthly price/volume inputs."],
    "ret-create-045": ["Selected the telecom-upsell first-page passage specifying corporate customers and voice products/services."],
    "ret-create-046": ["Selected the methodology passage explicitly stating that suspension duration weights infraction severity."],
}


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def load_cases() -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in DATASET.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def inventory(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    connection.row_factory = sqlite3.Row
    return [
        dict(row)
        for row in connection.execute(
            "SELECT chunk_id, paper_id, chunk_index, page_start, page_end, "
            "section, source_hash FROM chunk "
            "ORDER BY paper_id, chunk_index, chunk_id"
        )
    ]


def current_absence_count(
    connection: sqlite3.Connection, terms: list[str]
) -> int:
    matched: set[str] = set()
    for term in terms:
        matched.update(
            row[0]
            for row in connection.execute(
                "SELECT chunk_id FROM chunk WHERE instr(lower(text), ?) > 0",
                (str(term).casefold(),),
            )
        )
    return len(matched)


def atomic_write(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def main() -> None:
    initial_bytes = DATASET.read_bytes()
    initial_sha = sha256_bytes(initial_bytes)
    cases = load_cases()
    case_ids = {case["case_id"] for case in cases if case["supporting_evidence"]}
    if case_ids != set(CHOICES) or set(CHOICES) != set(REVIEW_NOTES):
        raise RuntimeError("choice/note coverage does not match answerable create cases")

    existing_audit: dict[str, Any] | None = None
    if AUDIT.is_file():
        existing_audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    elif initial_sha != ORIGINAL_DATASET_SHA256:
        raise RuntimeError(
            "first remap requires the preserved pre-rechunk create dataset; "
            f"expected {ORIGINAL_DATASET_SHA256}, got {initial_sha}"
        )
    prior_by_key = {
        (entry["case_id"], entry["evidence_index"]): entry["pre_rechunk_evidence"]
        for entry in (existing_audit or {}).get("choices", [])
    }

    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    try:
        rows = inventory(connection)
        inventory_sha = sha256_bytes(canonical_json_bytes(rows))
        if len(rows) != EXPECTED_CHUNK_COUNT or inventory_sha != EXPECTED_CHUNK_INVENTORY_SHA256:
            raise RuntimeError(
                "chunk inventory differs from the manually reviewed corpus: "
                f"count={len(rows)} sha256={inventory_sha}"
            )

        audit_choices: list[dict[str, Any]] = []
        absence_updates: list[dict[str, Any]] = []
        for case in cases:
            case_id = case["case_id"]
            evidence = case["supporting_evidence"]
            if evidence:
                indexes = CHOICES[case_id]
                notes = REVIEW_NOTES[case_id]
                if len(indexes) != len(evidence) or len(notes) != len(evidence):
                    raise RuntimeError(f"evidence choice count mismatch for {case_id}")
                for position, (item, chunk_index, note) in enumerate(
                    zip(evidence, indexes, notes, strict=True)
                ):
                    prior = prior_by_key.get((case_id, position), dict(item))
                    row = connection.execute(
                        "SELECT chunk_id, paper_id, chunk_index, page_start, page_end, "
                        "section, source_hash FROM chunk WHERE paper_id=? AND chunk_index=?",
                        (item["paper_id"], chunk_index),
                    ).fetchone()
                    if row is None:
                        raise RuntimeError(
                            f"selected chunk missing for {case_id} evidence {position}"
                        )
                    if row["paper_id"] in EXCLUDED_MISMATCHED_PAPERS:
                        raise RuntimeError(f"excluded mismatch selected for {case_id}")
                    old_start, old_end = prior.get("page_start"), prior.get("page_end")
                    if (
                        old_start is not None
                        and old_end is not None
                        and (row["page_end"] < old_start or row["page_start"] > old_end)
                    ):
                        raise RuntimeError(
                            f"selected chunk does not overlap preserved pages for {case_id} evidence {position}"
                        )
                    selected = {
                        "paper_id": row["paper_id"],
                        "chunk_id": row["chunk_id"],
                        "page_start": row["page_start"],
                        "page_end": row["page_end"],
                        "section": row["section"],
                        "source_hash": row["source_hash"],
                        "evidence_summary": item["evidence_summary"],
                    }
                    case["supporting_evidence"][position] = selected
                    audit_choices.append(
                        {
                            "case_id": case_id,
                            "evidence_index": position,
                            "selection_method": "manual_same_paper_page_overlap_source_text_review",
                            "pre_rechunk_evidence": prior,
                            "selected_current_evidence": selected,
                            "review_note": note,
                        }
                    )
            referenced = set(case.get("relevant_paper_ids", [])) | set(
                case.get("distractor_paper_ids", [])
            )
            if referenced & EXCLUDED_MISMATCHED_PAPERS:
                raise RuntimeError(f"excluded mismatch referenced by {case_id}")
            absence = case.get("corpus_absence_check")
            if isinstance(absence, dict):
                old_count = absence["matching_chunk_count"]
                new_count = current_absence_count(connection, absence["terms"])
                absence["matching_chunk_count"] = new_count
                absence_updates.append(
                    {
                        "case_id": case_id,
                        "terms": absence["terms"],
                        "pre_rechunk_matching_chunk_count": old_count,
                        "current_matching_chunk_count": new_count,
                    }
                )
    finally:
        connection.close()

    output = "".join(
        json.dumps(case, ensure_ascii=False, separators=(",", ":")) + "\n"
        for case in cases
    )
    output_sha = sha256_bytes(output.encode("utf-8"))
    audit = {
        "remap_id": "ttlab-retrieval-silver-remap-v1",
        "remapped_at": REMAPPED_AT,
        "dataset_path": "data/evaluation/retrieval_silver_create_v1.jsonl",
        "database_path": "data/papers.db",
        "pre_rechunk_dataset_sha256": ORIGINAL_DATASET_SHA256,
        "chunk_count": EXPECTED_CHUNK_COUNT,
        "chunk_inventory_sha256": EXPECTED_CHUNK_INVENTORY_SHA256,
        "remapped_dataset_sha256": output_sha,
        "supporting_evidence_count": len(audit_choices),
        "procedure": (
            "Every evidence row was reopened against current same-paper chunks overlapping "
            "the preserved page range. Ambiguous candidates were resolved from source text, "
            "not by retrieval output or automatic lexical top-1 selection. Semantic create- "
            "and verify-pass judgments were retained; only current evidence provenance and "
            "rechunk-dependent absence counts were migrated."
        ),
        "retrieval_or_ranking_inspected": False,
        "choices": audit_choices,
        "absence_count_updates": absence_updates,
    }
    atomic_write(DATASET, output)
    atomic_write(
        AUDIT,
        json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    print(f"dataset={DATASET}")
    print(f"audit={AUDIT}")
    print(f"evidence_rows={len(audit_choices)}")
    print(f"chunk_inventory_sha256={EXPECTED_CHUNK_INVENTORY_SHA256}")
    print(f"dataset_sha256={output_sha}")


if __name__ == "__main__":
    main()
