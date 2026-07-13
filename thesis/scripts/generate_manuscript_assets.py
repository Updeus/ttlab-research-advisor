#!/usr/bin/env python3
"""Generate manuscript numbers and compact tables only from frozen artefacts."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "thesis" / "generated"
SOURCES = {
    "phase1": ROOT / "artifacts" / "phase1" / "phase1_evidence.json",
    "retrieval": ROOT / "artifacts" / "phase2" / "retrieval" / "summary.json",
    "retrieval_labels": ROOT / "data" / "evaluation" / "retrieval_silver_v1.jsonl",
    "qa": ROOT / "artifacts" / "phase3" / "qa" / "qa_faithfulness_metrics_v1.json",
    "recommendation": ROOT / "artifacts" / "phase4" / "recommendation_proxy_v1" / "aggregate_results.json",
    "topics": ROOT / "artifacts" / "phase4" / "topic_author" / "topic_metrics.json",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_sources() -> dict[str, dict[str, Any]]:
    missing = [str(path.relative_to(ROOT)) for path in SOURCES.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError("Required frozen artefacts are missing: " + ", ".join(missing))
    return {
        name: json.loads(path.read_text(encoding="utf-8"))
        for name, path in SOURCES.items()
        if name != "retrieval_labels"
    }


def number(value: float, digits: int = 3) -> str:
    return f"{float(value):.{digits}f}"


def percent(value: float, digits: int = 1) -> str:
    return f"{100.0 * float(value):.{digits}f}"


def macro(name: str, value: Any) -> str:
    return f"\\newcommand{{\\{name}}}{{{value}}}"


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    data = load_sources()
    phase1 = data["phase1"]
    retrieval = data["retrieval"]
    retrieval_cases = [
        json.loads(line)
        for line in SOURCES["retrieval_labels"].read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    qa = data["qa"]
    recommendation = data["recommendation"]
    topics = data["topics"]

    corpus = phase1["corpus"]
    qa_metrics = qa["metrics"]
    qa_ci = qa["confidence_intervals"]["metrics"]
    rec_metrics = recommendation["metrics"]
    rec_comparison = rec_metrics["arm_comparison"]
    lexical_topic = topics["methods"]["controlled_lexical"]["test"]
    dense_topic = topics["methods"]["dense_prototype"]["test"]

    values: dict[str, Any] = {
        "CorpusSnapshotId": phase1["indexes"]["dense"]["manifest"]["corpus"]["snapshot_id"],
        "CatalogPaperCount": corpus["paper_count"],
        "AvailablePdfCount": corpus["pdf_unavailability_reasons"]["available"],
        "EligiblePaperCount": corpus["eligible_paper_count"],
        "NoTextPaperCount": corpus["eligibility_statuses"]["needs_review"],
        "MismatchPaperCount": corpus["eligibility_statuses"]["excluded_pdf_metadata_mismatch"],
        "RawChunkCount": corpus["raw_chunk_count"],
        "EligibleChunkCount": corpus["eligible_chunk_count"],
        "EligibleUnknownChunkCount": corpus["section_counts_eligible"]["Unknown"],
        "SectionSilverAccuracy": number(phase1["section_silver_validation"]["stdout"].split("accuracy=")[1].split()[0]),
        "RetrievalCaseCount": retrieval["dataset"]["case_count"],
        "RetrievalDevCount": retrieval["dataset"]["dev_count"],
        "RetrievalTestCount": retrieval["dataset"]["test_count"],
        "RetrievalAnswerableTestCount": sum(
            case["split"] == "test" and case["answerability"] == "answerable"
            for case in retrieval_cases
        ),
        "RetrievalUnanswerableTestCount": sum(
            case["split"] == "test" and case["answerability"] != "answerable"
            for case in retrieval_cases
        ),
        "QaCaseCount": qa["case_count"],
        "QaClaimCount": qa["counts"]["claim_count"],
        "QaSupportedClaimRate": number(qa_metrics["supported_claim_rate"]),
        "QaSupportedClaimRateLow": number(qa_ci["supported_claim_rate"]["ci_lower"]),
        "QaSupportedClaimRateHigh": number(qa_ci["supported_claim_rate"]["ci_upper"]),
        "QaCitationCorrectness": number(qa_metrics["citation_precision_correctness"]),
        "QaCitationCorrectnessLow": number(qa_ci["citation_precision_correctness"]["ci_lower"]),
        "QaCitationCorrectnessHigh": number(qa_ci["citation_precision_correctness"]["ci_upper"]),
        "QaCitationCompleteness": number(qa_metrics["citation_completeness"]),
        "QaAnswerPointCoverage": number(qa_metrics["answer_point_coverage"]),
        "QaAnswerPointCoverageLow": number(qa_ci["answer_point_coverage"]["ci_lower"]),
        "QaAnswerPointCoverageHigh": number(qa_ci["answer_point_coverage"]["ci_upper"]),
        "QaUnanswerableAbstentionRate": number(qa_metrics["unanswerable_abstention_rate"]),
        "RecommendationProfileCount": recommendation["profile_coverage"]["profile_count"],
        "RecommendationEvidenceRelevance": number(rec_comparison["baseline_mean_relevance_score"]),
        "RecommendationFullRelevance": number(rec_comparison["full_finder_mean_relevance_score"]),
        "RecommendationRelevanceDifference": number(rec_comparison["full_minus_baseline_relevance"]["estimate"]),
        "RecommendationDifferenceLow": number(rec_comparison["full_minus_baseline_relevance"]["ci_lower"]),
        "RecommendationDifferenceHigh": number(rec_comparison["full_minus_baseline_relevance"]["ci_upper"]),
        "TopicCaseCount": (
            topics["methods"]["controlled_lexical"]["dev"]["case_count"]
            + topics["methods"]["controlled_lexical"]["test"]["case_count"]
        ),
        "TopicTestCount": lexical_topic["case_count"],
        "TopicLexicalPrecision": number(lexical_topic["micro"]["precision"]),
        "TopicLexicalRecall": number(lexical_topic["micro"]["recall"]),
        "TopicLexicalFone": number(lexical_topic["micro"]["f1"]),
        "TopicLexicalCoverage": number(lexical_topic["coverage"]),
        "TopicDensePrecision": number(dense_topic["micro"]["precision"]),
        "TopicDenseRecall": number(dense_topic["micro"]["recall"]),
        "TopicDenseFone": number(dense_topic["micro"]["f1"]),
        "TopicDenseCoverage": number(dense_topic["coverage"]),
    }

    retrieval_rows: list[dict[str, Any]] = []
    mode_labels = {
        "keyword": "Keyword",
        "feature_hashing": "Feature hashing",
        "dense": "Learned dense",
        "heuristic_hybrid": "Heuristic hybrid",
        "tuned_hybrid": "Tuned hybrid",
    }
    for mode in ("keyword", "feature_hashing", "dense", "heuristic_hybrid", "tuned_hybrid"):
        metrics = retrieval["test_results"][mode]
        retrieval_rows.append(
            {
                "mode": mode,
                "label": mode_labels[mode],
                "set_recall_at_3": number(metrics["set_recall_at_3"]["estimate"]),
                "set_recall_at_3_low": number(metrics["set_recall_at_3"]["ci_lower"]),
                "set_recall_at_3_high": number(metrics["set_recall_at_3"]["ci_upper"]),
                "set_recall_at_10": number(metrics["set_recall_at_10"]["estimate"]),
                "mrr": number(metrics["mrr"]["estimate"]),
                "ndcg_at_10": number(metrics["ndcg_at_10"]["estimate"]),
                "unanswerable_false_positive_rate": number(
                    metrics["unanswerable_false_positive_rate"]["estimate"]
                ),
            }
        )
        prefix = "Retrieval" + "".join(part.capitalize() for part in mode.split("_"))
        values[prefix + "RecallThree"] = number(metrics["set_recall_at_3"]["estimate"])
        values[prefix + "RecallTen"] = number(metrics["set_recall_at_10"]["estimate"])
        values[prefix + "Mrr"] = number(metrics["mrr"]["estimate"])
        values[prefix + "NdcgTen"] = number(metrics["ndcg_at_10"]["estimate"])

    qa_rows = [
        {
            "metric": label,
            "estimate": number(qa_metrics[key]),
            "ci_low": number(qa_ci[key]["ci_lower"]),
            "ci_high": number(qa_ci[key]["ci_upper"]),
        }
        for key, label in (
            ("supported_claim_rate", "Supported-claim rate"),
            ("citation_precision_correctness", "Citation correctness"),
            ("citation_completeness", "Citation completeness"),
            ("answer_point_coverage", "Answer-point coverage"),
            ("abstention_accuracy", "Answerability decision accuracy"),
            ("unanswerable_abstention_rate", "Unanswerable abstention"),
        )
    ]

    topic_rows = [
        {
            "method": "Controlled lexical",
            "precision": number(lexical_topic["micro"]["precision"]),
            "recall": number(lexical_topic["micro"]["recall"]),
            "f1": number(lexical_topic["micro"]["f1"]),
            "coverage": number(lexical_topic["coverage"]),
        },
        {
            "method": "Dense prototype",
            "precision": number(dense_topic["micro"]["precision"]),
            "recall": number(dense_topic["micro"]["recall"]),
            "f1": number(dense_topic["micro"]["f1"]),
            "coverage": number(dense_topic["coverage"]),
        },
    ]

    OUT.mkdir(parents=True, exist_ok=True)
    macro_text = "% Generated by thesis/scripts/generate_manuscript_assets.py; do not edit.\n"
    macro_text += "\n".join(macro(name, value) for name, value in sorted(values.items())) + "\n"
    (OUT / "evidence_macros.tex").write_text(macro_text, encoding="utf-8")
    write_csv(
        OUT / "retrieval_results.csv",
        retrieval_rows,
        [
            "mode",
            "label",
            "set_recall_at_3",
            "set_recall_at_3_low",
            "set_recall_at_3_high",
            "set_recall_at_10",
            "mrr",
            "ndcg_at_10",
            "unanswerable_false_positive_rate",
        ],
    )
    write_csv(OUT / "qa_results.csv", qa_rows, ["metric", "estimate", "ci_low", "ci_high"])
    write_csv(OUT / "topic_results.csv", topic_rows, ["method", "precision", "recall", "f1", "coverage"])

    manifest = {
        "schema_version": 1,
        "generator": "thesis/scripts/generate_manuscript_assets.py",
        "sources": {
            name: {"path": str(path.relative_to(ROOT)), "sha256": sha256(path)}
            for name, path in SOURCES.items()
        },
        "outputs": {
            name: {"path": str(path.relative_to(ROOT)), "sha256": sha256(path)}
            for name, path in {
                "macros": OUT / "evidence_macros.tex",
                "retrieval_csv": OUT / "retrieval_results.csv",
                "qa_csv": OUT / "qa_results.csv",
                "topic_csv": OUT / "topic_results.csv",
            }.items()
        },
        "values": values,
    }
    (OUT / "manuscript_metrics_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"macros={OUT / 'evidence_macros.tex'}")
    print(f"manifest={OUT / 'manuscript_metrics_manifest.json'}")


if __name__ == "__main__":
    main()
