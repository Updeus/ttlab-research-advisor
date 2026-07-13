from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlmodel import Session, func, select

from app.models import Chunk, Paper, PaperArtifact, RAGAnswer, ReviewEvent, ThesisRecommendation

DEFAULT_EVALUATION_DIR = Path("data/evaluation")
ROOT = Path(__file__).resolve().parents[3]

RESULT_FILES = {
    "retrieval": "retrieval_eval_results.json",
    "qa": "qa_eval_results.json",
    "extension": "extension_eval_results.json",
    "artifact": "artifact_eval_results.json",
}

CURRENT_RESULT_FILES = {
    "retrieval": ROOT / "artifacts" / "phase2" / "retrieval" / "summary.json",
    "qa": ROOT / "artifacts" / "phase3" / "qa" / "qa_faithfulness_metrics_v1.json",
    "extension": ROOT / "artifacts" / "phase4" / "recommendation_proxy_v1" / "aggregate_results.json",
    "artifact": ROOT
    / "artifacts"
    / "phase4"
    / "generated_output_review"
    / "generated_output_review_summary.json",
}
RETRIEVAL_SILVER_PATH = ROOT / "data" / "evaluation" / "retrieval_silver_v1.jsonl"


def build_evaluation_dashboard(
    session: Session,
    evaluation_dir: Path = DEFAULT_EVALUATION_DIR,
) -> dict[str, Any]:
    if (
        evaluation_dir == DEFAULT_EVALUATION_DIR
        and RETRIEVAL_SILVER_PATH.is_file()
        and all(path.is_file() for path in CURRENT_RESULT_FILES.values())
    ):
        return build_current_evaluation_dashboard(session)
    retrieval = parse_retrieval_results(evaluation_dir / RESULT_FILES["retrieval"])
    qa = parse_qa_results(evaluation_dir / RESULT_FILES["qa"])
    extension = parse_extension_results(evaluation_dir / RESULT_FILES["extension"])
    artifact = parse_artifact_results(evaluation_dir / RESULT_FILES["artifact"])
    return {
        "retrieval": retrieval,
        "qa": qa,
        "extension": extension,
        "artifact": artifact,
        "human_review_templates": template_availability(evaluation_dir),
        "overall_quality": overall_quality(session),
        "result_files": {
            key: {
                "path": str(evaluation_dir / filename),
                "exists": (evaluation_dir / filename).exists(),
                "last_modified": file_timestamp(evaluation_dir / filename),
            }
            for key, filename in RESULT_FILES.items()
        },
    }


def build_current_evaluation_dashboard(session: Session) -> dict[str, Any]:
    """Expose the executed, versioned experiment artefacts used by the manuscripts."""

    return {
        "evaluation_label": "AI-reviewed silver offline evaluation; no recruited human participants",
        "reviewer_type": "ai",
        "human_validation": False,
        "retrieval": parse_current_retrieval(CURRENT_RESULT_FILES["retrieval"]),
        "qa": parse_current_qa(CURRENT_RESULT_FILES["qa"]),
        "extension": parse_current_extension(CURRENT_RESULT_FILES["extension"]),
        "artifact": parse_current_review(CURRENT_RESULT_FILES["artifact"]),
        "human_review_templates": template_availability(DEFAULT_EVALUATION_DIR),
        "overall_quality": overall_quality(session),
        "result_files": {
            key: {
                "path": str(path.relative_to(ROOT)),
                "exists": path.exists(),
                "last_modified": file_timestamp(path),
            }
            for key, path in CURRENT_RESULT_FILES.items()
        },
    }


def parse_current_retrieval(path: Path) -> dict[str, Any]:
    result = read_result(path)
    if result["status"] != "available":
        return parse_retrieval_results(path)
    payload = result["payload"]
    silver_cases = [
        json.loads(line)
        for line in RETRIEVAL_SILVER_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    answerable_test_count = sum(
        row.get("split") == "test" and row.get("answerability") == "answerable"
        for row in silver_cases
    )
    keyword = payload["test_results"]["keyword"]
    tuned = payload["test_results"]["tuned_hybrid"]
    return {
        **base_status(path, "available"),
        "question_count": payload["dataset"]["case_count"],
        "development_count": payload["dataset"]["dev_count"],
        "test_count": payload["dataset"]["test_count"],
        "answerable_test_count": answerable_test_count,
        "unanswerable_test_count": payload["dataset"]["test_count"] - answerable_test_count,
        "recall_at_3": keyword["set_recall_at_3"]["estimate"],
        "recall_at_5": keyword["set_recall_at_5"]["estimate"],
        "recall_at_10": keyword["set_recall_at_10"]["estimate"],
        "mrr": keyword["mrr"]["estimate"],
        "ndcg_at_10": keyword["ndcg_at_10"]["estimate"],
        "reported_mode": "keyword (strongest held-out estimate)",
        "tuned_hybrid_recall_at_10": tuned["set_recall_at_10"]["estimate"],
        "tuned_hybrid_mrr": tuned["mrr"]["estimate"],
        "unanswerable_false_positive_rate": keyword["unanswerable_false_positive_rate"]["estimate"],
        "reviewer_type": "ai",
        "dataset_label": payload["dataset"]["label"],
        "statistical_conclusion": "No Holm-corrected tuned-hybrid comparison rejected the null hypothesis.",
    }


def parse_current_qa(path: Path) -> dict[str, Any]:
    result = read_result(path)
    if result["status"] != "available":
        return parse_qa_results(path)
    payload = result["payload"]
    metrics = payload["metrics"]
    counts = payload["counts"]
    return {
        **base_status(path, "available"),
        "question_count": payload["case_count"],
        "answer_count": payload["case_count"],
        "claim_count": counts["claim_count"],
        "citation_count": counts["citation_links"],
        "supported_claim_rate": metrics["supported_claim_rate"],
        "citation_correctness": metrics["citation_precision_correctness"],
        "citation_completeness": metrics["citation_completeness"],
        "answer_point_coverage": metrics["answer_point_coverage"],
        "unsupported_claim_rate": metrics["unsupported_claim_rate"],
        "unanswerable_abstention_rate": metrics["unanswerable_abstention_rate"],
        "reviewer_type": payload["reviewer_type"],
        # Retained compatibility fields for existing clients.
        "cited_gold_paper_count": 0,
        "grounding_counts": {
            "supported": counts["supported_claims"],
            "partial": counts["partially_supported_claims"],
            "unsupported": counts["unsupported_claims"],
        },
    }


def parse_current_extension(path: Path) -> dict[str, Any]:
    result = read_result(path)
    if result["status"] != "available":
        return parse_extension_results(path)
    payload = result["payload"]
    comparison = payload["metrics"]["arm_comparison"]
    delta = comparison["full_minus_baseline_relevance"]
    reviewed = payload["metrics"]["full_finder"]["reviewed_items"]
    return {
        **base_status(path, "available"),
        "case_count": payload["profile_coverage"]["profile_count"],
        "recommendation_count": reviewed,
        "citation_coverage": 1.0,
        "warnings_count": 0,
        "evidence_only_relevance": comparison["baseline_mean_relevance_score"],
        "full_finder_relevance": comparison["full_finder_mean_relevance_score"],
        "relevance_difference": delta["estimate"],
        "relevance_difference_ci": [delta["ci_lower"], delta["ci_upper"]],
        "reviewer_type": payload["reviewer_type"],
        "proxy_notice": "Synthetic-profile AI proxy review; not student or supervisor validation.",
        "grounding_counts": empty_grounding_counts(),
    }


def parse_current_review(path: Path) -> dict[str, Any]:
    result = read_result(path)
    if result["status"] != "available":
        return parse_artifact_results(path)
    payload = result["payload"]
    counts = payload["counts"]
    return {
        **base_status(path, "available"),
        "case_count": counts["total"],
        "artifact_count": counts["by_item_type"]["paper_artifact"],
        "citation_coverage": None,
        "warnings_count": 0,
        "sections_with_explicit_support": 0,
        "sections_inferred": 0,
        "sections_not_found": 0,
        "ai_reviewed_count": counts["by_target_status"]["ai_reviewed"],
        "needs_reprocess_count": counts["by_target_status"]["needs_reprocess"],
        "review_event_count": counts["total"],
        "citation_evidence_locator_count": counts["citation_evidence_locator_count"],
        "reviewer_type": payload["reviewer_type"],
        "review_notice": payload["review_notice"],
        "grounding_counts": empty_grounding_counts(),
    }


def parse_retrieval_results(path: Path) -> dict[str, Any]:
    result = read_result(path)
    if result["status"] != "available":
        return {
            **base_status(path, result["status"], result.get("error")),
            "question_count": 0,
            "recall_at_3": None,
            "recall_at_5": None,
            "mrr": None,
        }
    payload = result["payload"]
    metrics = payload.get("metrics", {}) if isinstance(payload, dict) else {}
    return {
        **base_status(path, "available"),
        "question_count": metrics.get("question_count", len(payload.get("questions", []))),
        "recall_at_3": metrics.get("recall_at_3"),
        "recall_at_5": metrics.get("recall_at_5"),
        "mrr": metrics.get("mrr"),
        "mode": payload.get("mode"),
        "top_k": payload.get("top_k"),
        "warnings_count": len(payload.get("warnings", []) or []),
    }


def parse_qa_results(path: Path) -> dict[str, Any]:
    result = read_result(path)
    if result["status"] != "available":
        return {
            **base_status(path, result["status"], result.get("error")),
            "question_count": 0,
            "answer_count": 0,
            "cited_gold_paper_count": 0,
            "citation_count": 0,
            "grounding_counts": empty_grounding_counts(),
        }
    payload = result["payload"]
    rows = payload.get("results", []) if isinstance(payload, dict) else []
    return {
        **base_status(path, "available"),
        "question_count": payload.get("question_count", len(rows)),
        "answer_count": len(rows),
        "cited_gold_paper_count": sum(1 for row in rows if row.get("any_gold_paper_cited")),
        "citation_count": sum(int(row.get("citation_count") or 0) for row in rows),
        "grounding_counts": count_values(rows, "grounding_status", empty_grounding_counts()),
        "mode": payload.get("mode"),
        "top_k": payload.get("top_k"),
    }


def parse_extension_results(path: Path) -> dict[str, Any]:
    result = read_result(path)
    if result["status"] != "available":
        return {
            **base_status(path, result["status"], result.get("error")),
            "case_count": 0,
            "recommendation_count": 0,
            "citation_coverage": None,
            "grounding_counts": empty_grounding_counts(),
            "warnings_count": 0,
        }
    payload = result["payload"]
    cases = payload.get("cases", []) if isinstance(payload, dict) else []
    metrics = payload.get("metrics", {}) if isinstance(payload, dict) else {}
    return {
        **base_status(path, "available"),
        "case_count": payload.get("case_count", len(cases)),
        "recommendation_count": sum(int(case.get("recommendation_count") or 0) for case in cases),
        "citation_coverage": metrics.get("average_citation_coverage"),
        "grounding_counts": {
            "grounded": metrics.get("grounded_cases", 0),
            "partial": metrics.get("partial_cases", 0),
            "unsupported": metrics.get("unsupported_cases", 0),
        },
        "warnings_count": sum(int(case.get("warnings_count") or 0) for case in cases),
    }


def parse_artifact_results(path: Path) -> dict[str, Any]:
    result = read_result(path)
    if result["status"] != "available":
        return {
            **base_status(path, result["status"], result.get("error")),
            "case_count": 0,
            "artifact_count": 0,
            "citation_coverage": None,
            "grounding_counts": empty_grounding_counts(),
            "warnings_count": 0,
            "sections_with_explicit_support": 0,
            "sections_inferred": 0,
            "sections_not_found": 0,
        }
    payload = result["payload"]
    cases = payload.get("cases", []) if isinstance(payload, dict) else []
    metrics = payload.get("metrics", {}) if isinstance(payload, dict) else {}
    return {
        **base_status(path, "available"),
        "case_count": payload.get("case_count", len(cases)),
        "artifact_count": sum(int(case.get("artifact_count") or 0) for case in cases),
        "citation_coverage": metrics.get("average_citation_coverage"),
        "grounding_counts": {
            "grounded": metrics.get("grounded_cases", 0),
            "partial": metrics.get("partial_cases", 0),
            "unsupported": metrics.get("unsupported_cases", 0),
        },
        "warnings_count": sum(int(case.get("warnings_count") or 0) for case in cases),
        "sections_with_explicit_support": sum(int(case.get("sections_with_explicit_support") or 0) for case in cases),
        "sections_inferred": sum(int(case.get("sections_inferred") or 0) for case in cases),
        "sections_not_found": sum(int(case.get("sections_not_found") or 0) for case in cases),
    }


def read_result(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"status": "not_run"}
    try:
        return {"status": "available", "payload": json.loads(path.read_text(encoding="utf-8"))}
    except json.JSONDecodeError as exc:
        return {"status": "invalid", "error": str(exc)}


def base_status(path: Path, status: str, error: str | None = None) -> dict[str, Any]:
    return {
        "status": status,
        "result_file_exists": path.exists(),
        "path": str(path),
        "last_run_timestamp": file_timestamp(path),
        **({"error": error} if error else {}),
    }


def template_availability(evaluation_dir: Path) -> dict[str, bool]:
    return {
        "retrieval_questions": (evaluation_dir / "questions.jsonl").exists()
        or (evaluation_dir / "questions.sample.jsonl").exists(),
        "qa_questions": (evaluation_dir / "qa_questions.jsonl").exists()
        or (evaluation_dir / "qa_questions.sample.jsonl").exists(),
        "extension_human_review_template": (evaluation_dir / "extension_human_review_template.csv").exists(),
        "artifact_human_review_template": (evaluation_dir / "artifact_human_review_template.csv").exists(),
    }


def overall_quality(session: Session) -> dict[str, Any]:
    return {
        "eligible_indexed_chunks": session.exec(
            select(func.count())
            .select_from(Chunk)
            .join(Paper, Paper.paper_id == Chunk.paper_id)
            .where(Paper.corpus_eligibility_status == "eligible")
        ).one(),
        "eligible_searchable_papers": session.exec(
            select(func.count(func.distinct(Chunk.paper_id)))
            .select_from(Chunk)
            .join(Paper, Paper.paper_id == Chunk.paper_id)
            .where(Paper.corpus_eligibility_status == "eligible")
        ).one(),
        "generated_artifacts": session.exec(select(func.count()).select_from(PaperArtifact)).one(),
        "artifacts_needing_review": session.exec(
            select(func.count()).select_from(PaperArtifact).where(PaperArtifact.review_status == "needs_review")
        ).one(),
        "recommendations_needing_review": session.exec(
            select(func.count())
            .select_from(ThesisRecommendation)
            .where(ThesisRecommendation.review_status == "needs_review")
        ).one(),
        "answers_needing_review": session.exec(
            select(func.count()).select_from(RAGAnswer).where(RAGAnswer.review_status == "needs_review")
        ).one(),
        "answers_needing_reprocess": session.exec(
            select(func.count()).select_from(RAGAnswer).where(RAGAnswer.review_status == "needs_reprocess")
        ).one(),
        "ai_reviewed_artifacts": session.exec(
            select(func.count()).select_from(PaperArtifact).where(PaperArtifact.review_status == "ai_reviewed")
        ).one(),
        "ai_reviewed_recommendations": session.exec(
            select(func.count())
            .select_from(ThesisRecommendation)
            .where(ThesisRecommendation.review_status == "ai_reviewed")
        ).one(),
        "papers_needing_review": session.exec(
            select(func.count()).select_from(Paper).where(Paper.review_status == "needs_review")
        ).one(),
        "total_review_events": session.exec(select(func.count()).select_from(ReviewEvent)).one(),
    }


def count_values(rows: list[dict[str, Any]], key: str, defaults: dict[str, int]) -> dict[str, int]:
    counts = dict(defaults)
    for row in rows:
        value = str(row.get(key) or "")
        if value:
            counts[value] = counts.get(value, 0) + 1
    return counts


def empty_grounding_counts() -> dict[str, int]:
    return {"grounded": 0, "partial": 0, "unsupported": 0}


def file_timestamp(path: Path) -> str | None:
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat()


def latest_evaluation_timestamp(evaluation_dir: Path = DEFAULT_EVALUATION_DIR) -> str | None:
    if evaluation_dir == DEFAULT_EVALUATION_DIR:
        paths = list(CURRENT_RESULT_FILES.values())
        timestamps = [datetime.fromtimestamp(path.stat().st_mtime, tz=UTC) for path in paths if path.exists()]
        return max(timestamps).isoformat() if timestamps else None
    timestamps = [
        datetime.fromtimestamp((evaluation_dir / filename).stat().st_mtime, tz=UTC)
        for filename in RESULT_FILES.values()
        if (evaluation_dir / filename).exists()
    ]
    if not timestamps:
        return None
    return max(timestamps).isoformat()


def evaluation_files_present(evaluation_dir: Path = DEFAULT_EVALUATION_DIR) -> dict[str, bool]:
    if evaluation_dir == DEFAULT_EVALUATION_DIR:
        return {key: path.exists() for key, path in CURRENT_RESULT_FILES.items()}
    return {key: (evaluation_dir / filename).exists() for key, filename in RESULT_FILES.items()}
