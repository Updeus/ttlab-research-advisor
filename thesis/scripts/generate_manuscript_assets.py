#!/usr/bin/env python3
"""Generate manuscript numbers and compact tables only from frozen artefacts."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from app.evaluation.performance_validator import (
    FULL_REQUIRED_STAGES,
    validate_performance_artifact,
)


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "thesis" / "generated"
SOURCES = {
    "evidence_snapshot": ROOT / "thesis" / "generated" / "evidence_snapshot.json",
    "phase1": ROOT / "artifacts" / "phase1" / "phase1_evidence.json",
    "retrieval": ROOT / "artifacts" / "phase2" / "retrieval" / "summary.json",
    "retrieval_statistics": ROOT / "artifacts" / "phase2" / "retrieval" / "paired_statistics.json",
    "retrieval_errors": ROOT / "artifacts" / "phase2" / "retrieval" / "error_taxonomy.json",
    "retrieval_labels": ROOT / "data" / "evaluation" / "retrieval_silver_v1.jsonl",
    "qa": ROOT / "artifacts" / "phase3" / "qa" / "qa_faithfulness_metrics_v1.json",
    "recommendation": ROOT / "artifacts" / "phase4" / "recommendation_proxy_v1" / "aggregate_results.json",
    "topics": ROOT / "artifacts" / "phase4" / "topic_author" / "topic_metrics.json",
    "authors": ROOT / "artifacts" / "phase4" / "topic_author" / "author_identity_audit.json",
    "generated_review": ROOT / "artifacts" / "phase4" / "generated_output_review" / "generated_output_review_summary.json",
    "external_sanity": ROOT / "artifacts" / "phase6" / "external_sanity" / "external_sanity_manifest.json",
    "performance": ROOT / "artifacts" / "phase6" / "performance" / "performance_full_results.json",
    "performance_validation": ROOT / "artifacts" / "phase6" / "performance" / "performance_validation.json",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def generation_provenance() -> dict[str, Any]:
    backend_status = subprocess.run(
        ["git", "status", "--porcelain", "--", "backend"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if backend_status:
        raise RuntimeError("Backend source must be clean before manuscript asset generation")

    def git_value(*arguments: str) -> str:
        return subprocess.run(
            ["git", *arguments], cwd=ROOT, check=True, capture_output=True, text=True
        ).stdout.strip()

    script = Path(__file__).resolve()
    return {
        "committed_base": {
            "commit": git_value("rev-parse", "HEAD"),
            "tree": git_value("rev-parse", "HEAD^{tree}"),
            "backend_dirty": False,
        },
        "exact_generator": {
            "path": script.relative_to(ROOT).as_posix(),
            "sha256": sha256(script),
        },
        "expected_manuscript_output_dirty_boundary": [
            "thesis/generated/**",
            "build/thesis.pdf",
        ],
        "semantics": (
            "The commit/tree identify the clean committed application base. Exact generator, input, and output "
            "hashes bind this asset set. The generated manuscript outputs are an explicit self-referential dirty "
            "boundary and are not claimed to originate from a final clean commit."
        ),
    }


def load_sources() -> dict[str, dict[str, Any]]:
    missing = [
        str(path.relative_to(ROOT))
        for name, path in SOURCES.items()
        if not path.is_file()
    ]
    if missing:
        raise FileNotFoundError("Required frozen artefacts are missing: " + ", ".join(missing))
    return {
        name: json.loads(path.read_text(encoding="utf-8"))
        for name, path in SOURCES.items()
        if name != "retrieval_labels" and path.is_file()
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
    evidence_snapshot = data["evidence_snapshot"]
    retrieval = data["retrieval"]
    retrieval_statistics = data["retrieval_statistics"]
    retrieval_errors = data["retrieval_errors"]
    retrieval_cases = [
        json.loads(line)
        for line in SOURCES["retrieval_labels"].read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    qa = data["qa"]
    recommendation = data["recommendation"]
    topics = data["topics"]
    authors = data["authors"]
    generated_review = data["generated_review"]
    external_sanity = data["external_sanity"]
    performance = data["performance"]
    performance_validation = validate_performance_artifact(
        performance,
        expected_profile="full",
        expected_repetitions=3,
        expected_stages=list(FULL_REQUIRED_STAGES),
    )
    if performance_validation != data["performance_validation"]:
        raise ValueError(
            "Strict performance validation does not match "
            "artifacts/phase6/performance/performance_validation.json"
        )

    corpus = phase1["corpus"]
    qa_metrics = qa["metrics"]
    qa_ci = qa["confidence_intervals"]["metrics"]
    rec_metrics = recommendation["metrics"]
    rec_comparison = rec_metrics["arm_comparison"]
    lexical_topic = topics["methods"]["controlled_lexical"]["test"]
    dense_topic = topics["methods"]["dense_prototype"]["test"]
    database = evidence_snapshot["database"]
    retrieval_pairs = retrieval_statistics["comparisons"]
    review_counts = generated_review["counts"]
    section_stdout = phase1["section_silver_validation"]["stdout"]

    def section_value(name: str) -> float:
        match = re.search(rf"\b{re.escape(name)}=([0-9.]+)", section_stdout)
        if not match:
            raise ValueError(f"Missing {name} in frozen section validation output")
        return float(match.group(1))

    values: dict[str, Any] = {
        "CorpusSnapshotId": phase1["indexes"]["dense"]["manifest"]["corpus"]["snapshot_id"],
        "CatalogPaperCount": corpus["paper_count"],
        "AvailablePdfCount": corpus["pdf_unavailability_reasons"]["available"],
        "NoPdfUrlCount": corpus["pdf_unavailability_reasons"]["no_pdf_url"],
        "PdfNetworkErrorCount": corpus["pdf_unavailability_reasons"]["network_error"],
        "PdfNotFoundCount": corpus["pdf_unavailability_reasons"]["not_found"],
        "EligiblePaperCount": corpus["eligible_paper_count"],
        "NoTextPaperCount": corpus["eligibility_statuses"]["needs_review"],
        "MismatchPaperCount": corpus["eligibility_statuses"]["excluded_pdf_metadata_mismatch"],
        "MismatchChunkCount": sum(item["chunk_count"] for item in corpus["excluded_records"]),
        "RawChunkCount": corpus["raw_chunk_count"],
        "EligibleChunkCount": corpus["eligible_chunk_count"],
        "EligibleUnknownChunkCount": corpus["section_counts_eligible"]["Unknown"],
        "EligibleUnknownChunkPercent": number(
            corpus["section_counts_eligible"]["Unknown"] / corpus["eligible_chunk_count"] * 100,
            1,
        ),
        "ExtractedPageCount": database["extracted_page_count"],
        "ExtractedWordCount": f"{database['extracted_word_count']:,}",
        "SectionSilverAccuracy": number(section_value("accuracy")),
        "SectionSilverCaseCount": int(section_value("cases")),
        "SectionSilverMacroPrecision": number(section_value("macro_precision")),
        "SectionSilverMacroRecall": number(section_value("macro_recall")),
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
        "QaSupportedClaimCount": qa["counts"]["supported_claims"],
        "QaPartiallySupportedClaimCount": qa["counts"]["partially_supported_claims"],
        "QaUnsupportedClaimCount": qa["counts"]["unsupported_claims"],
        "QaCorrectCitationCount": qa["counts"]["correct_citation_links"],
        "QaAnswerPointCount": qa["counts"]["answer_point_count"],
        "QaCoveredAnswerPointCount": qa["counts"]["covered_answer_points"],
        "QaUnanswerableCaseCount": qa["counts"]["unanswerable_cases"],
        "QaUnanswerableAbstentionCount": qa["counts"]["unanswerable_abstentions"],
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
        "QaAbstentionAccuracy": number(qa_metrics["abstention_accuracy"]),
        "QaAbstentionAccuracyLow": number(qa_ci["abstention_accuracy"]["ci_lower"]),
        "QaAbstentionAccuracyHigh": number(qa_ci["abstention_accuracy"]["ci_upper"]),
        "QaCitationUtilization": number(qa_metrics["returned_citation_utilization"]),
        "RecommendationProfileCount": recommendation["profile_coverage"]["profile_count"],
        "RecommendationEvidenceRelevance": number(rec_comparison["baseline_mean_relevance_score"]),
        "RecommendationFullRelevance": number(rec_comparison["full_finder_mean_relevance_score"]),
        "RecommendationRelevanceDifference": number(rec_comparison["full_minus_baseline_relevance"]["estimate"]),
        "RecommendationDifferenceLow": number(rec_comparison["full_minus_baseline_relevance"]["ci_lower"]),
        "RecommendationDifferenceHigh": number(rec_comparison["full_minus_baseline_relevance"]["ci_upper"]),
        "RecommendationEvidenceRelevanceLow": number(rec_metrics["evidence_only"]["criteria"]["paper_relevance"]["weighted_score_ci"]["ci_lower"]),
        "RecommendationEvidenceRelevanceHigh": number(rec_metrics["evidence_only"]["criteria"]["paper_relevance"]["weighted_score_ci"]["ci_upper"]),
        "RecommendationFullRelevanceLow": number(rec_metrics["full_finder"]["criteria"]["paper_relevance"]["weighted_score_ci"]["ci_lower"]),
        "RecommendationFullRelevanceHigh": number(rec_metrics["full_finder"]["criteria"]["paper_relevance"]["weighted_score_ci"]["ci_upper"]),
        "RecommendationItemCountPerArm": rec_metrics["evidence_only"]["reviewed_items"],
        "RecommendationFeasibilityPartialCount": rec_metrics["full_finder"]["criteria"]["skills_time_data_feasibility"]["counts"]["partial"],
        "RecommendationEvaluationPlanPassCount": rec_metrics["full_finder"]["criteria"]["evaluation_plan_quality"]["counts"]["pass"],
        "RecommendationEvaluationPlanPartialCount": rec_metrics["full_finder"]["criteria"]["evaluation_plan_quality"]["counts"]["partial"],
        "RecommendationReviewAgreement": number(rec_metrics["repeatability"]["exact_agreement"]),
        "RecommendationCriterionCount": rec_metrics["repeatability"]["criterion_judgments_compared"],
        "TopicCaseCount": (
            topics["methods"]["controlled_lexical"]["dev"]["case_count"]
            + topics["methods"]["controlled_lexical"]["test"]["case_count"]
        ),
        "TopicTestCount": lexical_topic["case_count"],
        "TopicDevCount": topics["methods"]["controlled_lexical"]["dev"]["case_count"],
        "TopicLexicalPrecision": number(lexical_topic["micro"]["precision"]),
        "TopicLexicalRecall": number(lexical_topic["micro"]["recall"]),
        "TopicLexicalFone": number(lexical_topic["micro"]["f1"]),
        "TopicLexicalCoverage": number(lexical_topic["coverage"]),
        "TopicDensePrecision": number(dense_topic["micro"]["precision"]),
        "TopicDenseRecall": number(dense_topic["micro"]["recall"]),
        "TopicDenseFone": number(dense_topic["micro"]["f1"]),
        "TopicDenseCoverage": number(dense_topic["coverage"]),
        "RawAuthorRowCount": phase1["metadata_identity"]["author_count"],
        "CanonicalAuthorCount": authors["active_canonical_identity_count"],
        "PossibleAuthorMergeCount": len(authors["possible_same_person_pairs_not_merged"]),
        "AuthorTopicLinkCount": authors["publication_derived_author_topic_link_count"],
        "GeneratedReviewTotalCount": review_counts["total"],
        "GeneratedRagAnswerCount": review_counts["by_item_type"]["rag_answer"],
        "GeneratedRecommendationCount": review_counts["by_item_type"]["thesis_recommendation"],
        "GeneratedArtifactCount": review_counts["by_item_type"]["paper_artifact"],
        "GeneratedAiReviewedCount": review_counts["by_target_status"]["ai_reviewed"],
        "GeneratedNeedsReprocessCount": review_counts["by_target_status"]["needs_reprocess"],
        "GeneratedReviewEventCount": generated_review["apply_result"]["created_events"],
        "ExternalSanityDocumentCount": external_sanity["sanity_check"]["case_count"],
        "ExternalSanityTopOneCount": external_sanity["sanity_check"]["top_1_matches"],
        "ExternalSanityChunkCount": sum(document["chunk_count"] for document in external_sanity["documents"]),
    }

    performance_stages = (
        ("Dense indexing", "dense_index"),
        ("Keyword retrieval", "retrieval_keyword"),
        ("Dense retrieval", "retrieval_dense"),
        ("Hybrid retrieval", "retrieval_hybrid"),
        ("Offline answer", "answer_offline"),
        ("Recommendation", "recommendation_offline"),
        ("ASGI endpoint set", "api_asgi"),
        ("Frontend route set", "frontend_page_load"),
    )
    performance_rows: list[dict[str, Any]] = []
    values["PerformanceRepetitions"] = performance["methodology"]["repetitions"]
    values["PerformanceStageCount"] = performance_validation["stages"]
    values["PerformanceAttemptCount"] = performance_validation["samples"]
    values["PerformanceFailureCount"] = performance_validation["failures"]
    values["PerformanceCpu"] = performance["hardware"]["cpu_model"]
    values["PerformanceMemoryGiB"] = number(
        performance["hardware"]["memory_total_kib"] / 1_048_576, 1
    )
    values["PerformanceSourceCommit"] = performance_validation["source_commit"][:8]
    values["PerformanceProvenancePrefix"] = performance_validation["provenance_sha256"][:12]
    max_rss_kib = max(
        int(series["summary"].get("max_rss_kib") or 0)
        for stage in FULL_REQUIRED_STAGES
        for series in (
            performance["results"][stage]["cold"],
            performance["results"][stage]["warm"],
        )
    )
    latex_rows: list[str] = []
    for label, key in performance_stages:
        stage = performance["results"][key]
        cold = stage["cold"]["summary"]
        warm = stage["warm"]["summary"]
        row = {
            "stage": key,
            "label": label,
            "cold_median": number(cold["elapsed_seconds"]["median"]),
            "cold_p95": number(cold["elapsed_seconds"]["p95"]),
            "warm_median": number(warm["elapsed_seconds"]["median"]),
            "warm_p95": number(warm["elapsed_seconds"]["p95"]),
            "failure_count": int(cold["failures"]) + int(warm["failures"]),
        }
        performance_rows.append(row)
        latex_rows.append(
            f"{label} & {row['cold_median']} & {row['cold_p95']} & "
            f"{row['warm_median']} & {row['warm_p95']} \\\\"
        )
    values["PerformanceMaxRssMiB"] = number(max_rss_kib / 1024, 1)
    values["PerformanceTableRows"] = "\n".join(latex_rows)

    for label, comparison_key in (
        ("Keyword", "tuned_minus_keyword"),
        ("Dense", "tuned_minus_dense"),
        ("FeatureHashing", "tuned_minus_feature_hashing"),
    ):
        comparison = retrieval_pairs[comparison_key]["comparisons"]["mrr"]
        values[f"TunedMinus{label}Mrr"] = number(comparison["mean_difference"])
        values[f"TunedMinus{label}MrrLow"] = number(comparison["confidence_interval"]["ci_lower"])
        values[f"TunedMinus{label}MrrHigh"] = number(comparison["confidence_interval"]["ci_upper"])
        values[f"TunedMinus{label}RawP"] = number(comparison["paired_test"]["p_value"])
        values[f"TunedMinus{label}AdjustedP"] = number(
            comparison["experiment_family_correction"]["adjusted_p_value"]
        )

    qa_errors = qa["error_taxonomy"]["affected_cases"]
    for macro_name, key in (
        ("QaIncompleteCaseCount", "incomplete_answer"),
        ("QaOffTopicRetrievalCaseCount", "off_topic_retrieval"),
        ("QaWithinPaperMissCaseCount", "within_paper_evidence_retrieval_miss"),
        ("QaAnswerPointOmissionCaseCount", "answer_point_omission"),
        ("QaSentenceSelectionMissCaseCount", "answer_sentence_selection_miss"),
        ("QaIncorrectCitationCaseCount", "incorrect_citation"),
        ("QaFalsePositiveCaseCount", "unanswerable_false_positive"),
    ):
        values[macro_name] = qa_errors[key]

    retrieval_error_counts = retrieval_errors["taxonomy"]
    values["RetrievalExtractionErrorCaseCount"] = retrieval_error_counts["extraction"]["case_count"]
    values["RetrievalIntentMismatchCaseCount"] = retrieval_error_counts["intent_mismatch"]["case_count"]
    values["RetrievalCorpusAbsenceCaseCount"] = retrieval_error_counts["corpus_absence"]["case_count"]

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
        values[prefix + "RecallThreeLow"] = number(metrics["set_recall_at_3"]["ci_lower"])
        values[prefix + "RecallThreeHigh"] = number(metrics["set_recall_at_3"]["ci_upper"])
        values[prefix + "RecallTen"] = number(metrics["set_recall_at_10"]["estimate"])
        values[prefix + "Mrr"] = number(metrics["mrr"]["estimate"])
        values[prefix + "NdcgTen"] = number(metrics["ndcg_at_10"]["estimate"])

    values["RetrievalUnanswerableFalsePositiveCount"] = round(
        retrieval["test_results"]["keyword"]["unanswerable_false_positive_rate"]["estimate"]
        * values["RetrievalUnanswerableTestCount"]
    )

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
    write_csv(
        OUT / "performance_results.csv",
        performance_rows,
        ["stage", "label", "cold_median", "cold_p95", "warm_median", "warm_p95", "failure_count"],
    )

    manifest = {
        "schema_version": 2,
        "generator": "thesis/scripts/generate_manuscript_assets.py",
        "generation_provenance": generation_provenance(),
        "sources": {
            name: {"path": str(path.relative_to(ROOT)), "sha256": sha256(path)}
            for name, path in SOURCES.items()
            if path.is_file()
        },
        "outputs": {
            name: {"path": str(path.relative_to(ROOT)), "sha256": sha256(path)}
            for name, path in {
                "macros": OUT / "evidence_macros.tex",
                "retrieval_csv": OUT / "retrieval_results.csv",
                "qa_csv": OUT / "qa_results.csv",
                "topic_csv": OUT / "topic_results.csv",
                "performance_csv": OUT / "performance_results.csv",
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
