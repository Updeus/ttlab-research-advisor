#!/usr/bin/env python3
"""Validate section-quality labels against the live DB and source pages."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sqlite3
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "data/papers.db"
CREATE = ROOT / "data/evaluation/section_quality_silver_create_v1.jsonl"
FINAL = ROOT / "data/evaluation/section_quality_silver_v1.jsonl"
LABELS = ["Abstract", "Introduction", "Literature Review", "Methodology", "Results", "Discussion", "Conclusion", "References", "Unknown"]
SEED = 20260712


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def norm(value: str) -> str:
    return " ".join(value.split()).casefold()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return path.name


def validate(
    *, database: Path = DB, evaluate_current: bool = False, output_json: Path | None = None
) -> dict:
    create, final = load(CREATE), load(FINAL)
    assert len(create) == len(final) == 40
    assert len({row["chunk_id"] for row in final}) == 40
    assert Counter(row["predicted_section"] for row in final) == {label: 5 for label in LABELS[:-1]}
    assert Counter(row["sampling_stratum"] for row in final) == {"front_matter": 7, "section_boundary": 22, "section_interior": 11}
    shuffled = list(create)
    random.Random(SEED).shuffle(shuffled)
    assert [row["source_case_id"] for row in final] == [row["case_id"] for row in shuffled]
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    create_by_id = {row["case_id"]: row for row in create}
    current_predictions: list[str] = []
    for position, case in enumerate(final, start=1):
        assert case["reviewer_id"] == case["verifier_id"] == "codex-ai-review"
        assert case["reviewer_type"] == "ai" and case["label_quality"] == "silver" and case["pass"] == "verify"
        assert case["shuffle_seed"] == SEED and case["shuffled_position"] == position
        assert case["predicted_section"] in LABELS and case["expected_section"] in LABELS
        row = connection.execute("SELECT c.*,p.extracted_json_path FROM chunk c JOIN paper p ON p.paper_id=c.paper_id WHERE c.chunk_id=?", (case["chunk_id"],)).fetchone()
        assert row is not None
        for field in ("paper_id", "chunk_index", "page_start", "page_end", "source_hash", "section"):
            key = "predicted_section" if field == "section" else field
            if evaluate_current and field == "section":
                current_predictions.append(str(row[field]))
                continue
            assert case[key] == row[field], (case["case_id"], key)
        extraction = json.loads((ROOT / row["extracted_json_path"]).read_text(encoding="utf-8"))
        pages = {int(page["page_number"]): str(page.get("text") or "") for page in extraction["pages"]}
        for evidence in case["source_heading_evidence"]:
            assert evidence["page_number"] in pages
            assert norm(evidence["heading_text"]) in norm(pages[evidence["page_number"]])
        source = create_by_id[case["source_case_id"]]
        expected_decision = "agree" if source["expected_section"] == case["expected_section"] else "revise"
        assert case["decision"] == expected_decision
        assert case["creation_expected_section"] == source["expected_section"]
    connection.close()

    predicted = current_predictions if evaluate_current else [row["predicted_section"] for row in final]
    expected = [row["expected_section"] for row in final]
    correct = sum(left == right for left, right in zip(predicted, expected))
    supported = sum(label != "Unknown" for label in expected)
    labeled_correct = sum(left == right and right != "Unknown" for left, right in zip(predicted, expected))
    per_label = {}
    for label in LABELS:
        tp = sum(p == label and e == label for p, e in zip(predicted, expected))
        pred_n, gold_n = predicted.count(label), expected.count(label)
        per_label[label] = {"support": gold_n, "predicted": pred_n, "precision": None if not pred_n else round(tp / pred_n, 6), "recall": None if not gold_n else round(tp / gold_n, 6)}
    precisions = [row["precision"] for row in per_label.values() if row["precision"] is not None]
    recalls = [row["recall"] for row in per_label.values() if row["recall"] is not None]
    decisions = Counter(row["decision"] for row in final)
    result = {
        "schema_version": 1,
        "status": "valid",
        "prediction_source": "current_database" if evaluate_current else "frozen_silver_snapshot",
        "database": display_path(database),
        "dataset": display_path(FINAL),
        "dataset_sha256": file_sha256(FINAL),
        "case_count": len(final),
        "metrics": {
            "accuracy": round(correct / len(final), 6),
            "labeled_accuracy": round(labeled_correct / supported, 6),
            "labeled_coverage": round(supported / len(final), 6),
            "expected_unknown_rate": round(expected.count("Unknown") / len(final), 6),
            "predicted_unknown_rate": round(predicted.count("Unknown") / len(final), 6),
            "macro_precision": round(sum(precisions) / len(precisions), 6),
            "macro_recall": round(sum(recalls) / len(recalls), 6),
        },
        "decisions": dict(sorted(decisions.items())),
        "per_label": per_label,
    }
    if output_json is not None:
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"cases={len(final)} accuracy={result['metrics']['accuracy']:.6f} labeled_accuracy={result['metrics']['labeled_accuracy']:.6f}")
    print(f"labeled_coverage={result['metrics']['labeled_coverage']:.6f} expected_unknown_rate={result['metrics']['expected_unknown_rate']:.6f} predicted_unknown_rate={result['metrics']['predicted_unknown_rate']:.6f}")
    print(f"macro_precision={result['metrics']['macro_precision']:.6f} macro_recall={result['metrics']['macro_recall']:.6f}")
    print("prediction_source=" + result["prediction_source"])
    print(f"database={result['database']}")
    print("decisions=" + json.dumps(dict(sorted(decisions.items())), sort_keys=True))
    print("per_label=" + json.dumps(per_label, sort_keys=True))
    print("status=valid")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate the section silver set and optionally score a rechunked database.")
    parser.add_argument("--database", type=Path, default=DB)
    parser.add_argument(
        "--evaluate-current",
        action="store_true",
        help="Score section labels stored in --database while preserving the frozen silver expectations.",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        help="Write a path-sanitized structured metrics artifact in addition to the text report.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    validate(database=args.database, evaluate_current=args.evaluate_current, output_json=args.json_out)


if __name__ == "__main__":
    main()
