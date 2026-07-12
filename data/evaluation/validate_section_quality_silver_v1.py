#!/usr/bin/env python3
"""Validate section-quality labels against the live DB and source pages."""

from __future__ import annotations

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


def main() -> None:
    create, final = load(CREATE), load(FINAL)
    assert len(create) == len(final) == 40
    assert len({row["chunk_id"] for row in final}) == 40
    assert Counter(row["predicted_section"] for row in final) == {label: 5 for label in LABELS[:-1]}
    assert Counter(row["sampling_stratum"] for row in final) == {"front_matter": 7, "section_boundary": 22, "section_interior": 11}
    shuffled = list(create)
    random.Random(SEED).shuffle(shuffled)
    assert [row["source_case_id"] for row in final] == [row["case_id"] for row in shuffled]
    connection = sqlite3.connect(DB)
    connection.row_factory = sqlite3.Row
    create_by_id = {row["case_id"]: row for row in create}
    for position, case in enumerate(final, start=1):
        assert case["reviewer_id"] == case["verifier_id"] == "codex-ai-review"
        assert case["reviewer_type"] == "ai" and case["label_quality"] == "silver" and case["pass"] == "verify"
        assert case["shuffle_seed"] == SEED and case["shuffled_position"] == position
        assert case["predicted_section"] in LABELS and case["expected_section"] in LABELS
        row = connection.execute("SELECT c.*,p.extracted_json_path FROM chunk c JOIN paper p ON p.paper_id=c.paper_id WHERE c.chunk_id=?", (case["chunk_id"],)).fetchone()
        assert row is not None
        for field in ("paper_id", "chunk_index", "page_start", "page_end", "source_hash", "section"):
            key = "predicted_section" if field == "section" else field
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

    predicted = [row["predicted_section"] for row in final]
    expected = [row["expected_section"] for row in final]
    correct = sum(left == right for left, right in zip(predicted, expected))
    supported = sum(label != "Unknown" for label in expected)
    per_label = {}
    for label in LABELS:
        tp = sum(p == label and e == label for p, e in zip(predicted, expected))
        pred_n, gold_n = predicted.count(label), expected.count(label)
        per_label[label] = {"support": gold_n, "predicted": pred_n, "precision": None if not pred_n else round(tp / pred_n, 6), "recall": None if not gold_n else round(tp / gold_n, 6)}
    precisions = [row["precision"] for row in per_label.values() if row["precision"] is not None]
    recalls = [row["recall"] for row in per_label.values() if row["recall"] is not None]
    decisions = Counter(row["decision"] for row in final)
    print(f"cases={len(final)} accuracy={correct/len(final):.6f} labeled_accuracy={correct/supported:.6f}")
    print(f"labeled_coverage={supported/len(final):.6f} expected_unknown_rate={expected.count('Unknown')/len(final):.6f} predicted_unknown_rate={predicted.count('Unknown')/len(final):.6f}")
    print(f"macro_precision={sum(precisions)/len(precisions):.6f} macro_recall={sum(recalls)/len(recalls):.6f}")
    print("decisions=" + json.dumps(dict(sorted(decisions.items())), sort_keys=True))
    print("per_label=" + json.dumps(per_label, sort_keys=True))
    print("status=valid")


if __name__ == "__main__":
    main()
