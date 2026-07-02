from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlmodel import Session, func, select

from app.models import Chunk, Paper, PaperArtifact, RAGAnswer, ReviewEvent, ThesisRecommendation

DEFAULT_EVALUATION_DIR = Path("data/evaluation")

RESULT_FILES = {
    "retrieval": "retrieval_eval_results.json",
    "qa": "qa_eval_results.json",
    "extension": "extension_eval_results.json",
    "artifact": "artifact_eval_results.json",
}


def build_evaluation_dashboard(
    session: Session,
    evaluation_dir: Path = DEFAULT_EVALUATION_DIR,
) -> dict[str, Any]:
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
        "indexed_chunks": session.exec(select(func.count()).select_from(Chunk)).one(),
        "searchable_papers": session.exec(select(func.count(func.distinct(Chunk.paper_id))).select_from(Chunk)).one(),
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
    timestamps = [
        datetime.fromtimestamp((evaluation_dir / filename).stat().st_mtime, tz=UTC)
        for filename in RESULT_FILES.values()
        if (evaluation_dir / filename).exists()
    ]
    if not timestamps:
        return None
    return max(timestamps).isoformat()


def evaluation_files_present(evaluation_dir: Path = DEFAULT_EVALUATION_DIR) -> dict[str, bool]:
    return {key: (evaluation_dir / filename).exists() for key, filename in RESULT_FILES.items()}
