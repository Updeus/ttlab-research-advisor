#!/usr/bin/env python3
"""Generate IEEE-paper macros and tables from committed experiment artefacts."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "paper" / "generated"
REQUIRED = {
    "phase1": ROOT / "artifacts" / "phase1" / "phase1_evidence.json",
    "section_metrics": ROOT / "artifacts" / "phase1" / "section_quality_metrics.json",
    "retrieval": ROOT / "artifacts" / "phase2" / "retrieval" / "summary.json",
    "qa": ROOT / "artifacts" / "phase3" / "qa" / "qa_faithfulness_metrics_v1.json",
    "recommendation": ROOT / "artifacts" / "phase4" / "recommendation_proxy_v1" / "aggregate_results.json",
    "topics": ROOT / "artifacts" / "phase4" / "topic_author" / "topic_metrics.json",
    "author_audit": ROOT / "artifacts" / "phase4" / "topic_author" / "author_identity_audit.json",
    "review": ROOT / "artifacts" / "phase4" / "generated_output_review" / "generated_output_review_summary.json",
    "retrieval_error": ROOT / "artifacts" / "phase2" / "retrieval" / "error_taxonomy.json",
}
SECTION_CASES = ROOT / "data" / "evaluation" / "section_quality_silver_v1.jsonl"
PERFORMANCE_CANDIDATES = (
    ROOT / "artifacts" / "phase6" / "performance" / "performance_full_results.json",
    ROOT / "artifacts" / "phase6" / "performance" / "performance_results.json",
)


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fmt(value: float, digits: int = 3) -> str:
    return f"{float(value):.{digits}f}"


def fmt_optional(value: float | None, digits: int = 3) -> str:
    return "--" if value is None else fmt(value, digits)


def tex_escape(value: Any) -> str:
    return (
        str(value)
        .replace("\\", r"\textbackslash{}")
        .replace("&", r"\&")
        .replace("%", r"\%")
        .replace("#", r"\#")
        .replace("_", r"\_")
    )


def macro(name: str, value: Any) -> str:
    return rf"\newcommand{{\{name}}}{{{value}}}"


def ci(metric: dict[str, Any]) -> str:
    return f"[{fmt(metric['ci_lower'])}, {fmt(metric['ci_upper'])}]"


def main() -> None:
    missing = [str(path.relative_to(ROOT)) for path in (*REQUIRED.values(), SECTION_CASES) if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing required paper evidence: " + ", ".join(missing))
    data = {name: load(path) for name, path in REQUIRED.items()}
    phase1 = data["phase1"]
    retrieval = data["retrieval"]
    section_metrics = data["section_metrics"]
    qa = data["qa"]
    rec = data["recommendation"]
    topics = data["topics"]
    author_audit = data["author_audit"]
    review = data["review"]
    retrieval_error = data["retrieval_error"]
    if section_metrics["dataset_sha256"] != sha256(SECTION_CASES):
        raise ValueError("Section-quality metrics do not match the committed silver dataset")
    if section_metrics["prediction_source"] != "current_database":
        raise ValueError("Paper requires section-quality metrics evaluated against the current frozen database")

    corpus = phase1["corpus"]
    dense_manifest = phase1["indexes"]["dense"]["manifest"]
    values: dict[str, Any] = {
        "PaperCorpusSnapshot": dense_manifest["corpus"]["snapshot_id"],
        "PaperCatalogCount": corpus["paper_count"],
        "PaperPdfCount": corpus["pdf_unavailability_reasons"]["available"],
        "PaperEligiblePaperCount": corpus["eligible_paper_count"],
        "PaperNoTextCount": corpus["eligibility_statuses"]["needs_review"],
        "PaperMismatchCount": corpus["eligibility_statuses"]["excluded_pdf_metadata_mismatch"],
        "PaperRawChunkCount": corpus["raw_chunk_count"],
        "PaperEligibleChunkCount": corpus["eligible_chunk_count"],
        "PaperUnknownChunkCount": corpus["section_counts_eligible"]["Unknown"],
        "PaperSectionCaseCount": section_metrics["case_count"],
        "PaperSectionAccuracy": fmt(section_metrics["metrics"]["accuracy"]),
        "PaperDenseModel": tex_escape(dense_manifest["configuration"]["model_name"]),
        "PaperDenseRevision": tex_escape(dense_manifest["configuration"]["model_revision"]),
        "PaperDenseModelDisplay": rf"\nolinkurl{{{dense_manifest['configuration']['model_name']}}}",
        "PaperDenseRevisionDisplay": rf"\nolinkurl{{{dense_manifest['configuration']['model_revision']}}}",
        "PaperDenseDimension": dense_manifest["configuration"]["dimensions"],
        "PaperHashingDimension": phase1["indexes"]["feature_hashing"]["manifest"]["configuration"]["dimensions"],
        "PaperRetrievalCaseCount": retrieval["dataset"]["case_count"],
        "PaperRetrievalDevCount": retrieval["dataset"]["dev_count"],
        "PaperRetrievalTestCount": retrieval["dataset"]["test_count"],
        "PaperRetrievalAnswerableTestCount": sum(
            row["answerability"] == "answerable" for row in retrieval_error["cases"]
        ),
        "PaperRetrievalUnanswerableTestCount": sum(
            row["answerability"] == "unanswerable" for row in retrieval_error["cases"]
        ),
        "PaperRetrievalBootstrapRepetitions": retrieval["controls"]["bootstrap_repetitions"],
        "PaperHeuristicTermCount": len(retrieval["ablations"]["individual"]),
        "PaperTunedKeywordWeight": fmt(retrieval["selected_tuned_config"]["keyword_weight"], 2),
        "PaperTunedDenseWeight": fmt(retrieval["selected_tuned_config"]["vector_weight"], 2),
        "PaperIntentMismatchCount": retrieval_error["taxonomy"]["intent_mismatch"]["case_count"],
        "PaperExtractionSignalCount": retrieval_error["taxonomy"]["extraction"]["case_count"],
        "PaperCorpusAbsenceCount": retrieval_error["taxonomy"]["corpus_absence"]["case_count"],
        "PaperRetrievalUnanswerableFalsePositive": fmt(
            retrieval["test_results"]["keyword"]["unanswerable_false_positive_rate"]["estimate"]
        ),
        "PaperQaCaseCount": qa["case_count"],
        "PaperQaClaimCount": qa["counts"]["claim_count"],
        "PaperQaCitationAttachedCount": qa["counts"]["claims_with_citation"],
        "PaperQaUnanswerableCount": qa["counts"]["unanswerable_cases"],
        "PaperQaAnswerProvider": tex_escape(qa["answer_provider"]),
        "PaperQaAnswerModel": tex_escape(qa["answer_model"]),
        "PaperQaRetrievalMode": tex_escape(qa["retrieval_mode"]),
        "PaperRecommendationProfileCount": rec["profile_coverage"]["profile_count"],
        "PaperRecommendationItemsPerArm": rec["metrics"]["evidence_only"]["reviewed_items"],
        "PaperRecommendationFeasibilityPartialCount": rec["metrics"]["full_finder"]["criteria"][
            "skills_time_data_feasibility"
        ]["counts"]["partial"],
        "PaperRecommendationPlanPartialCount": rec["metrics"]["full_finder"]["criteria"][
            "evaluation_plan_quality"
        ]["counts"]["partial"],
        "PaperRecommendationPerturbationCount": len(rec["sensitivity_summary"]) - 1,
        "PaperRecommendationConfigurationCount": len(rec["sensitivity_summary"]),
        "PaperTopicCaseCount": topics["methods"]["controlled_lexical"]["dev"]["case_count"]
        + topics["methods"]["controlled_lexical"]["test"]["case_count"],
        "PaperTopicDevCount": topics["methods"]["controlled_lexical"]["dev"]["case_count"],
        "PaperTopicTestCount": topics["methods"]["controlled_lexical"]["test"]["case_count"],
        "PaperTopicControlledLabelCount": len(topics["labels"]) - 1,
        "PaperPossibleAuthorPairCount": len(author_audit["possible_same_person_pairs_not_merged"]),
        "PaperReviewEventCount": review["counts"]["total"],
        "PaperAiReviewedCount": review["counts"]["by_target_status"]["ai_reviewed"],
        "PaperNeedsReprocessCount": review["counts"]["by_target_status"]["needs_reprocess"],
        "PaperReviewAnswerCount": review["counts"]["by_item_type"]["rag_answer"],
        "PaperReviewRecommendationCount": review["counts"]["by_item_type"]["thesis_recommendation"],
        "PaperReviewArtifactCount": review["counts"]["by_item_type"]["paper_artifact"],
    }

    for mode, prefix in {
        "keyword": "Keyword",
        "feature_hashing": "Hashing",
        "dense": "Dense",
        "heuristic_hybrid": "HeuristicHybrid",
        "tuned_hybrid": "TunedHybrid",
    }.items():
        metrics = retrieval["test_results"][mode]
        for key, suffix in {
            "set_recall_at_3": "RecallThree",
            "set_recall_at_10": "RecallTen",
            "mrr": "Mrr",
            "ndcg_at_10": "NdcgTen",
        }.items():
            values[f"Paper{prefix}{suffix}"] = fmt(metrics[key]["estimate"])
            values[f"Paper{prefix}{suffix}Ci"] = ci(metrics[key])

    no_topic = retrieval["ablations"]["individual"]["topic_adjustment"]
    all_heuristics = retrieval["ablations"]["cumulative"][
        "query_expansion+metadata_boost+section_boost+evidence_adjustment+topic_adjustment+diversity_penalty"
    ]
    values.update(
        {
            "PaperNoTopicRecallTen": fmt(no_topic["set_recall_at_10"]["estimate"]),
            "PaperNoTopicMrr": fmt(no_topic["mrr"]["estimate"]),
            "PaperNoTopicNdcgTen": fmt(no_topic["ndcg_at_10"]["estimate"]),
            "PaperNoHeuristicsRecallTen": fmt(all_heuristics["set_recall_at_10"]["estimate"]),
            "PaperNoHeuristicsMrr": fmt(all_heuristics["mrr"]["estimate"]),
            "PaperNoHeuristicsNdcgTen": fmt(all_heuristics["ndcg_at_10"]["estimate"]),
        }
    )

    qa_metrics = qa["metrics"]
    qa_intervals = qa["confidence_intervals"]["metrics"]
    for key, suffix in {
        "supported_claim_rate": "QaSupport",
        "citation_precision_correctness": "QaCitationCorrectness",
        "citation_completeness": "QaCitationCompleteness",
        "answer_point_coverage": "QaAnswerCoverage",
        "unsupported_claim_rate": "QaUnsupported",
        "abstention_accuracy": "QaAbstentionAccuracy",
        "unanswerable_abstention_rate": "QaUnanswerableAbstention",
    }.items():
        values[f"Paper{suffix}"] = fmt(qa_metrics[key])
        values[f"Paper{suffix}Ci"] = ci(qa_intervals[key])

    comparison = rec["metrics"]["arm_comparison"]
    delta = comparison["full_minus_baseline_relevance"]
    values.update(
        {
            "PaperRecBaseline": fmt(comparison["baseline_mean_relevance_score"]),
            "PaperRecFull": fmt(comparison["full_finder_mean_relevance_score"]),
            "PaperRecDelta": fmt(delta["estimate"]),
            "PaperRecDeltaCi": f"[{fmt(delta['ci_lower'])}, {fmt(delta['ci_upper'])}]",
        }
    )
    lexical = topics["methods"]["controlled_lexical"]["test"]
    dense = topics["methods"]["dense_prototype"]["test"]
    for method, result in (("TopicLexical", lexical), ("TopicDense", dense)):
        values[f"Paper{method}Precision"] = fmt(result["micro"]["precision"])
        values[f"Paper{method}Recall"] = fmt(result["micro"]["recall"])
        values[f"Paper{method}Fone"] = fmt(result["micro"]["f1"])
        values[f"Paper{method}Coverage"] = fmt(result["coverage"])

    performance_path = next((path for path in PERFORMANCE_CANDIDATES if path.is_file()), None)
    performance_present = performance_path is not None
    if not performance_present and os.environ.get("PAPER_ALLOW_MISSING_PERFORMANCE") != "1":
        raise FileNotFoundError(
            "A final paper build requires artifacts/phase6/performance/performance_full_results.json; "
            "set PAPER_ALLOW_MISSING_PERFORMANCE=1 only for an explicitly non-final work-in-progress build"
        )
    values["PaperPerformanceAvailable"] = "1" if performance_present else "0"
    if performance_present:
        assert performance_path is not None
        performance = load(performance_path)
        sys.path.insert(0, str(ROOT / "backend"))
        from app.evaluation.performance_validator import FULL_REQUIRED_STAGES, validate_performance_artifact

        validate_performance_artifact(
            performance,
            expected_profile="full",
            expected_repetitions=3,
            expected_stages=list(FULL_REQUIRED_STAGES),
        )
        hardware = performance["hardware"]
        failed_samples = sum(
            temperature["summary"]["failures"]
            for result in performance["results"].values()
            if isinstance(result, dict) and "cold" in result
            for temperature in (result["cold"], result["warm"])
        )
        values.update(
            {
                "PaperPerformanceProfile": tex_escape(performance["profile"]),
                "PaperPerformanceRepetitions": performance["methodology"]["repetitions"],
                "PaperCpuModel": tex_escape(hardware["cpu_model"]),
                "PaperLogicalCpuCount": hardware["logical_cpu_count"],
                "PaperMemoryGiB": fmt(hardware["memory_total_kib"] / 1024 / 1024, 1),
                "PaperPerformanceStageCount": len(
                    [result for result in performance["results"].values() if isinstance(result, dict) and "cold" in result]
                ),
                "PaperPerformanceFailedSamples": failed_samples,
                "PaperPerformanceSourceCommit": tex_escape(
                    performance["execution_source"]["start"]["commit"][:12]
                ),
                "PaperPerformanceProvenance": tex_escape(performance["run_provenance_sha256"][:12]),
            }
        )

    OUT.mkdir(parents=True, exist_ok=True)
    metrics_path = OUT / "metrics.tex"
    metrics_path.write_text(
        "% Generated by paper/scripts/generate_paper_assets.py; do not edit.\n"
        + "\n".join(macro(name, value) for name, value in sorted(values.items()))
        + "\n",
        encoding="utf-8",
    )

    retrieval_rows = []
    labels = {
        "keyword": "Keyword",
        "feature_hashing": "Feature hashing",
        "dense": "Learned dense",
        "heuristic_hybrid": "Heuristic hybrid",
        "tuned_hybrid": "Dev-tuned hybrid",
    }
    for mode in labels:
        metrics = retrieval["test_results"][mode]
        retrieval_rows.append(
            f"{labels[mode]} & {fmt(metrics['set_recall_at_3']['estimate'])} & "
            f"{fmt(metrics['set_recall_at_10']['estimate'])} & {fmt(metrics['mrr']['estimate'])} & "
            f"{fmt(metrics['ndcg_at_10']['estimate'])} \\\\"
        )
    (OUT / "retrieval_rows.tex").write_text("\n".join(retrieval_rows) + "\n", encoding="utf-8")

    performance_summary = OUT / "performance_summary.tex"
    if performance_present:
        assert performance_path is not None
        performance = load(performance_path)
        selected = (
            ("Discovery (network)", "discovery"),
            ("PDF extraction", "pdf_extraction"),
            ("Chunking", "chunking"),
            ("Dense indexing", "dense_index"),
            ("Keyword retrieval", "retrieval_keyword"),
            ("Dense retrieval", "retrieval_dense"),
            ("Hybrid retrieval", "retrieval_hybrid"),
            ("Extractive answer", "answer_offline"),
            ("Recommendation", "recommendation_offline"),
            ("ASGI endpoints", "api_asgi"),
            ("Frontend build", "frontend_build"),
            ("Rendered routes", "frontend_page_load"),
        )
        rows: list[str] = []
        for label, stage in selected:
            result = performance["results"][stage]
            cold = result["cold"]["summary"]
            warm = result["warm"]["summary"]
            sample = next(
                (
                    row
                    for row in result["warm"]["samples"] + result["cold"]["samples"]
                    if row.get("status") == "ok"
                ),
                None,
            )
            rss_values = [
                value
                for value in (cold.get("max_rss_kib"), warm.get("max_rss_kib"))
                if value is not None
            ]
            rss = max(rss_values) if rss_values else None
            rows.append(
                f"{label} & {tex_escape(sample['units']) if sample else '--'} & {fmt_optional(cold['elapsed_seconds']['median'])} & "
                f"{fmt_optional(cold['elapsed_seconds']['p95'])} & {fmt_optional(warm['elapsed_seconds']['median'])} & "
                f"{fmt_optional(warm['elapsed_seconds']['p95'])} & {fmt_optional(rss / 1024 if rss else None, 1)} & "
                f"{cold['failures'] + warm['failures']} \\\\"
            )
        summary_text = (
            "The full profile measured \\PaperPerformanceStageCount{} stages with "
            "\\PaperPerformanceRepetitions{} process-cold and warm repetitions at concurrency one on "
            "\\PaperCpuModel{} (\\PaperLogicalCpuCount{} logical CPUs, \\PaperMemoryGiB{}~GiB RAM). "
            "The artifact is bound to source commit \\texttt{\\PaperPerformanceSourceCommit{}} and "
            "provenance digest \\texttt{\\PaperPerformanceProvenance{}}. "
            "Cold means a fresh Python process; operating-system caches were not flushed. "
            "Across the reported samples, \\PaperPerformanceFailedSamples{} executions failed. "
            "Table~\\ref{tab:performance} reports elapsed wall time and process peak RSS; it is a "
            "single-user characterization, not a saturation or capacity test.\n\n"
            "\\begin{table*}[t]\n"
            "\\caption{Full-corpus performance on documented local hardware. Times are seconds; RSS is MiB.}\n"
            "\\label{tab:performance}\n"
            "\\centering\n\\scriptsize\n"
            "\\begin{tabular}{@{}lrrrrrrr@{}}\n"
            "\\toprule\nStage & Units & Cold med. & Cold p95 & Warm med. & Warm p95 & Peak RSS & Fail. \\\\\n"
            "\\midrule\n"
            + "\n".join(rows)
            + "\n\\bottomrule\n\\end{tabular}\n\\end{table*}\n"
        )
        performance_summary.write_text(summary_text, encoding="utf-8")
    elif performance_summary.exists():
        performance_summary.unlink()

    sources = {name: {"path": str(path.relative_to(ROOT)), "sha256": sha256(path)} for name, path in REQUIRED.items()}
    sources["section_cases"] = {
        "path": str(SECTION_CASES.relative_to(ROOT)),
        "sha256": sha256(SECTION_CASES),
    }
    if performance_present:
        assert performance_path is not None
        sources["performance"] = {
            "path": str(performance_path.relative_to(ROOT)),
            "sha256": sha256(performance_path),
        }
    manifest = {
        "schema_version": 1,
        "generator": "paper/scripts/generate_paper_assets.py",
        "generator_sha256": sha256(Path(__file__).resolve()),
        "sources": sources,
        "outputs": {
            "metrics": {"path": str(metrics_path.relative_to(ROOT)), "sha256": sha256(metrics_path)},
            "retrieval_rows": {
                "path": "paper/generated/retrieval_rows.tex",
                "sha256": sha256(OUT / "retrieval_rows.tex"),
            },
            **(
                {
                    "performance_summary": {
                        "path": "paper/generated/performance_summary.tex",
                        "sha256": sha256(performance_summary),
                    }
                }
                if performance_present
                else {}
            ),
        },
        "performance_included": performance_present,
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"generated={OUT.relative_to(ROOT)} performance={performance_present}")


if __name__ == "__main__":
    main()
