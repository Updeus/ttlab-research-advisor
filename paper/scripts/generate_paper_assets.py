#!/usr/bin/env python3
"""Generate IEEE-paper macros and tables from committed experiment artefacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "paper" / "generated"
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
from manuscript_v2_package import load_manuscript_v2_package

V2_HELPER = SCRIPTS_DIR / "manuscript_v2_package.py"
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
    "external_sanity": ROOT / "artifacts" / "phase6" / "external_sanity" / "external_sanity_manifest.json",
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


def generation_provenance() -> dict[str, Any]:
    """Describe the committed base and the pre-generation working-tree boundary."""

    def git_value(*arguments: str) -> str:
        return subprocess.run(
            ["git", *arguments], cwd=ROOT, check=True, capture_output=True, text=True
        ).stdout.strip()

    status_lines = [
        line
        for line in git_value("status", "--porcelain=v1", "--untracked-files=all").splitlines()
        if line.strip()
    ]
    return {
        "committed_base": {
            "commit": git_value("rev-parse", "HEAD"),
            "tree": git_value("rev-parse", "HEAD^{tree}"),
        },
        "working_tree": {
            "dirty": bool(status_lines),
            "status_porcelain_before_generation": status_lines,
        },
        "expected_generated_output_boundary": [
            "paper/generated/**",
            "build/ieee-paper.pdf",
        ],
        "semantics": (
            "The commit and tree identify the committed repository base. Frozen evidence and the exact "
            "generator are bound separately by SHA-256. A dirty working tree means the PDF is a candidate "
            "built from that base plus local changes; it is not represented as a clean committed release. "
            "The status list is captured before this generator rewrites its own outputs."
        ),
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--allow-v2-not-run",
        action="store_true",
        help="Generate explicit non-submission layout placeholders before the canonical v2 run.",
    )
    args = parser.parse_args(argv)
    missing = [str(path.relative_to(ROOT)) for path in (*REQUIRED.values(), SECTION_CASES) if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing required paper evidence: " + ", ".join(missing))
    v2 = load_manuscript_v2_package(ROOT, allow_not_run=args.allow_v2_not_run)
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
    external_sanity = data["external_sanity"]
    provenance = generation_provenance()
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
        "PaperQaSupportedClaimCount": qa["counts"]["supported_claims"],
        "PaperQaPartialClaimCount": qa["counts"]["partially_supported_claims"],
        "PaperQaUnsupportedClaimCount": qa["counts"]["unsupported_claims"],
        "PaperQaCitationAttachedCount": qa["counts"]["claims_with_citation"],
        "PaperQaCorrectCitationLinkCount": qa["counts"]["correct_citation_links"],
        "PaperQaPartialCitationLinkCount": qa["counts"]["partial_citation_links"],
        "PaperQaIncorrectCitationLinkCount": qa["counts"]["incorrect_citation_links"],
        "PaperQaAnswerPointCount": qa["counts"]["answer_point_count"],
        "PaperQaCoveredAnswerPointCount": qa["counts"]["covered_answer_points"],
        "PaperQaPartialAnswerPointCount": qa["counts"]["partially_covered_answer_points"],
        "PaperQaMissingAnswerPointCount": qa["counts"]["answer_point_count"]
        - qa["counts"]["covered_answer_points"]
        - qa["counts"]["partially_covered_answer_points"],
        "PaperQaReturnedCitationCount": qa["counts"]["returned_citations"],
        "PaperQaUsedReturnedCitationCount": qa["counts"]["used_returned_citations"],
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
        "PaperTopicVocabularyCount": len(topics["labels"]),
        "PaperTopicSupportedTestLabelCount": topics["methods"]["controlled_lexical"]["test"][
            "macro_supported_label_count"
        ],
        "PaperTopicZeroGoldTestLabelCount": sum(
            row["tp"] + row["fn"] == 0
            for row in topics["methods"]["controlled_lexical"]["test"]["per_label"].values()
        ),
        "PaperPossibleAuthorPairCount": len(author_audit["possible_same_person_pairs_not_merged"]),
        "PaperReviewEventCount": review["counts"]["total"],
        "PaperAiReviewedCount": review["counts"]["by_target_status"]["ai_reviewed"],
        "PaperNeedsReprocessCount": review["counts"]["by_target_status"]["needs_reprocess"],
        "PaperReviewAnswerCount": review["counts"]["by_item_type"]["rag_answer"],
        "PaperReviewRecommendationCount": review["counts"]["by_item_type"]["thesis_recommendation"],
        "PaperReviewArtifactCount": review["counts"]["by_item_type"]["paper_artifact"],
        "PaperExternalDocumentCount": len(external_sanity["documents"]),
        "PaperExternalTopOneCount": external_sanity["sanity_check"]["top_1_matches"],
        "PaperSourceCommit": tex_escape(provenance["committed_base"]["commit"][:12]),
        "PaperSourceTree": tex_escape(provenance["committed_base"]["tree"][:12]),
        "PaperWorkingTreeDirty": str(provenance["working_tree"]["dirty"]).lower(),
        "PaperAiLabelBoundary": tex_escape(
            "AI-reviewed silver labels; no human inter-rater reliability or label-noise interval"
        ),
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
        + "\n"
        + v2["macro_text"],
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

    topic_rows = []
    topic_test_rows = topics["methods"]["controlled_lexical"]["test"]["per_label"]
    for label in ("agriculture", "ai", "clustering", "energy", "networks", "rag"):
        row = topic_test_rows[label]
        topic_rows.append(
            f"{tex_escape(label.title())} & {row['tp']} & {row['fp']} & {row['fn']} & "
            f"{fmt(row['precision'])} & {fmt(row['recall'])} \\tabularnewline"
        )
    topic_rows_path = OUT / "topic_error_rows.tex"
    topic_rows_path.write_text(
        "% Generated topic error rows; do not edit.\n"
        "\\newcommand{\\PaperTopicErrorRows}{%\n"
        + "\n".join(topic_rows)
        + "\n}\n",
        encoding="utf-8",
    )

    performance_summary = OUT / "performance_summary.tex"
    if performance_present:
        assert performance_path is not None
        performance = load(performance_path)
        selected = (
            ("Discovery", "discovery"),
            ("PDF extraction", "pdf_extraction"),
            ("Dense index", "dense_index"),
            ("Hybrid retrieval", "retrieval_hybrid"),
            ("Offline answer", "answer_offline"),
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
                f"{label} & {fmt_optional(cold['elapsed_seconds']['median'])} & "
                f"{fmt_optional(warm['elapsed_seconds']['median'])} & "
                f"{fmt_optional(rss / 1024 if rss else None, 1)} \\\\"
            )
        summary_text = (
            "\\begin{table}[t]\n"
            "\\caption{Selected local stage medians (s) and peak RSS (MiB).}\n"
            "\\label{tab:performance}\n"
            "\\centering\n\\scriptsize\n"
            "\\begin{tabular}{@{}lrrr@{}}\n"
            "\\toprule\nStage & Cold & Warm & RSS \\\\\n"
            "\\midrule\n"
            + "\n".join(rows)
            + "\n\\bottomrule\n\\end{tabular}\n\\end{table}\n"
        )
        performance_summary.write_text(summary_text, encoding="utf-8")
    elif performance_summary.exists():
        performance_summary.unlink()

    sources = {name: {"path": str(path.relative_to(ROOT)), "sha256": sha256(path)} for name, path in REQUIRED.items()}
    sources["v2_manuscript_package_helper"] = {
        "path": str(V2_HELPER.relative_to(ROOT)),
        "sha256": sha256(V2_HELPER),
    }
    sources.update(v2["sources"])
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
        "schema_version": 2,
        "generator": "paper/scripts/generate_paper_assets.py",
        "generator_sha256": sha256(Path(__file__).resolve()),
        "generation_provenance": provenance,
        "corpus_boundary": {
            "snapshot_id": dense_manifest["corpus"]["snapshot_id"],
            "eligible_papers": corpus["eligible_paper_count"],
            "eligible_chunks": corpus["eligible_chunk_count"],
            "ordered_chunk_hash": dense_manifest["corpus"].get("ordered_chunk_hash"),
        },
        "evidence_boundary": {
            "kind": "frozen committed experiment artefacts plus independently hashed generator outputs",
            "ai_label_status": (
                "Retrieval, QA, recommendation, section, topic, and generated-output judgments are "
                "AI-reviewed silver evidence, not recruited-human ground truth. Reported intervals do not "
                "model AI-label uncertainty."
            ),
            "qa_claim_labels": {
                "supported": qa["counts"]["supported_claims"],
                "partial": qa["counts"]["partially_supported_claims"],
                "unsupported": qa["counts"]["unsupported_claims"],
            },
        },
        "remediation_v2": {
            "status": v2["status"],
            "completed": v2["completed"],
            "layout_only": v2["layout_only"],
            "manifest_sha256": v2["manifest_sha256"],
            "validation_attestation_sha256": v2["validation_attestation_sha256"],
            "macro_attestation_cycle_avoided": (
                "Canonical v2 macros exclude manifest/attestation hashes; this downstream manifest "
                "binds both after completed-package validation."
            ),
        },
        "sources": sources,
        "outputs": {
            "metrics": {"path": str(metrics_path.relative_to(ROOT)), "sha256": sha256(metrics_path)},
            "retrieval_rows": {
                "path": "paper/generated/retrieval_rows.tex",
                "sha256": sha256(OUT / "retrieval_rows.tex"),
            },
            "topic_error_rows": {
                "path": "paper/generated/topic_error_rows.tex",
                "sha256": sha256(topic_rows_path),
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
    print(
        f"generated={OUT.relative_to(ROOT)} performance={performance_present} "
        f"v2={v2['status']}"
    )


if __name__ == "__main__":
    main()
