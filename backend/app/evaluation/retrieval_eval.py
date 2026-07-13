from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from statistics import fmean
from typing import Any, Iterable, Mapping, Sequence

from sqlmodel import Session

from app.db import create_db_and_tables, engine
from app.evaluation.statistics import bootstrap_mean_interval
from app.indexing.embedder import corpus_descriptor, eligible_chunks
from app.indexing.retriever import retrieve


RESULT_SCHEMA_VERSION = "2.0.0"
RESULT_SCHEMA_ID = "https://github.com/Updeus/ttlab-research-advisor/data/evaluation/retrieval_eval_results.schema.json"
DEFAULT_CUTOFFS = (3, 5, 10)
DEFAULT_BOOTSTRAP_SEED = 20260712
DEFAULT_BOOTSTRAP_REPETITIONS = 10_000

METRIC_DEFINITIONS = {
    "set_recall_at_k": "For answerable queries, |unique relevant papers in the first k unique papers| / |all judged relevant papers|.",
    "hit_at_k": "For answerable queries, 1 when at least one judged relevant paper occurs in the first k unique papers; otherwise 0.",
    "precision_at_k": "For answerable queries, |unique relevant papers in the first k unique papers| / k; unjudged papers are treated as non-relevant.",
    "reciprocal_rank": "For answerable queries, reciprocal of the rank of the first judged relevant unique paper; 0 when none is retrieved.",
    "ndcg_at_10": "For answerable queries with explicit graded judgments, DCG@10 using gain 2^grade-1 divided by the ideal DCG@10.",
    "unanswerable_abstention": "For a judged-unanswerable query, 1 only when the retriever returns no unique paper; otherwise 0.",
    "unanswerable_false_positive_at_k": "For a judged-unanswerable query, 1 when any paper is returned in the first k unique papers; otherwise 0.",
}


def load_questions(path: Path) -> list[dict[str, Any]]:
    """Load and validate legacy or silver retrieval judgments.

    Modern records use ``answerability``, ``relevant_paper_ids``, and optional
    grades. Legacy ``gold_paper_ids`` records remain accepted only when their
    relevance set is non-empty; an empty legacy set is ambiguous rather than an
    implicit unanswerable label.
    """

    if not path.exists():
        raise FileNotFoundError(f"Evaluation questions file not found: {path}")
    questions: list[dict[str, Any]] = []
    seen_case_ids: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON on line {line_number}: {exc}") from exc
        if not isinstance(record, dict):
            raise ValueError(f"Question on line {line_number} must be a JSON object.")
        normalized = normalize_question(record, line_number=line_number)
        case_id = normalized["case_id"]
        if case_id in seen_case_ids:
            raise ValueError(f"Duplicate case_id on line {line_number}: {case_id}")
        seen_case_ids.add(case_id)
        questions.append(normalized)
    if not questions:
        raise ValueError("Evaluation questions file contains no records.")
    return questions


def normalize_question(record: Mapping[str, Any], *, line_number: int = 1) -> dict[str, Any]:
    question = str(record.get("question") or "").strip()
    if not question:
        raise ValueError(f"Question on line {line_number} has no question text.")
    case_id = str(record.get("case_id") or f"query-{line_number:04d}").strip()
    answerability_value = record.get("answerability")

    if "relevant_paper_ids" in record:
        raw_relevant = record.get("relevant_paper_ids")
    else:
        raw_relevant = record.get("gold_paper_ids")
    if not isinstance(raw_relevant, list):
        raise ValueError(f"Question on line {line_number} must define a relevance-ID list.")
    relevant = _unique_strings(raw_relevant, field="relevant_paper_ids", line_number=line_number)

    if answerability_value is None:
        if not relevant:
            raise ValueError(
                f"Question on line {line_number} has an empty legacy relevance set; "
                "set answerability='unanswerable' explicitly or add reviewed relevant IDs."
            )
        answerability = "answerable"
    else:
        answerability = str(answerability_value)
        if answerability not in {"answerable", "unanswerable"}:
            raise ValueError(f"Question on line {line_number} has invalid answerability={answerability!r}.")
    if answerability == "answerable" and not relevant:
        raise ValueError(f"Answerable question on line {line_number} has no relevant papers.")
    if answerability == "unanswerable" and relevant:
        raise ValueError(f"Unanswerable question on line {line_number} cannot have relevant papers.")

    raw_judgments = record.get("relevance_judgments", [])
    if not isinstance(raw_judgments, list):
        raise ValueError(f"Question on line {line_number} has non-list relevance_judgments.")
    judgments: list[dict[str, Any]] = []
    judged_ids: set[str] = set()
    positive_judgment_ids: set[str] = set()
    for judgment in raw_judgments:
        if not isinstance(judgment, dict):
            raise ValueError(f"Question on line {line_number} has a non-object relevance judgment.")
        paper_id = str(judgment.get("paper_id") or "").strip()
        grade = judgment.get("grade")
        if not paper_id or isinstance(grade, bool) or not isinstance(grade, int) or grade < 0:
            raise ValueError(f"Question on line {line_number} has an invalid graded judgment.")
        if paper_id in judged_ids:
            raise ValueError(f"Question on line {line_number} has duplicate judgment for {paper_id!r}.")
        judged_ids.add(paper_id)
        if grade > 0:
            positive_judgment_ids.add(paper_id)
        judgments.append({**judgment, "paper_id": paper_id, "grade": grade})
    if judgments and positive_judgment_ids != set(relevant):
        raise ValueError(
            f"Question on line {line_number} has inconsistent relevant_paper_ids and positive graded judgments."
        )

    return {
        **record,
        "case_id": case_id,
        "question": question,
        "answerability": answerability,
        "relevant_paper_ids": relevant,
        "relevance_judgments": judgments,
    }


def evaluate_ranked_query(
    question: Mapping[str, Any],
    ranked_paper_ids: Sequence[str],
    *,
    cutoffs: Sequence[int] = DEFAULT_CUTOFFS,
) -> dict[str, Any]:
    """Compute paper-level metrics for one ranked query without I/O."""

    normalized = normalize_question(question)
    validated_cutoffs = _validate_cutoffs(cutoffs)
    ranked = _unique_strings(ranked_paper_ids, field="ranked_paper_ids", line_number=1)
    relevant = set(normalized["relevant_paper_ids"])
    answerable = normalized["answerability"] == "answerable"
    grade_by_paper = {
        str(judgment["paper_id"]): int(judgment["grade"])
        for judgment in normalized["relevance_judgments"]
    }
    has_explicit_grades = bool(normalized["relevance_judgments"])

    metrics: dict[str, Any] = {}
    if answerable:
        for cutoff in validated_cutoffs:
            retrieved_relevant = len(relevant.intersection(ranked[:cutoff]))
            metrics[f"set_recall_at_{cutoff}"] = retrieved_relevant / len(relevant)
            metrics[f"hit_at_{cutoff}"] = retrieved_relevant > 0
            metrics[f"precision_at_{cutoff}"] = retrieved_relevant / cutoff
            metrics[f"unanswerable_false_positive_at_{cutoff}"] = None
        first_hit_rank = next((rank for rank, paper_id in enumerate(ranked, start=1) if paper_id in relevant), None)
        metrics["first_relevant_rank"] = first_hit_rank
        metrics["reciprocal_rank"] = 0.0 if first_hit_rank is None else 1.0 / first_hit_rank
        metrics["ndcg_at_10"] = (
            normalized_discounted_cumulative_gain(ranked, grade_by_paper, cutoff=10)
            if has_explicit_grades
            else None
        )
        metrics["unanswerable_abstention"] = None
        metrics["unanswerable_false_positive"] = None
    else:
        for cutoff in validated_cutoffs:
            metrics[f"set_recall_at_{cutoff}"] = None
            metrics[f"hit_at_{cutoff}"] = None
            metrics[f"precision_at_{cutoff}"] = None
            metrics[f"unanswerable_false_positive_at_{cutoff}"] = bool(ranked[:cutoff])
        metrics.update(
            {
                "first_relevant_rank": None,
                "reciprocal_rank": None,
                "ndcg_at_10": None,
                "unanswerable_abstention": not ranked,
                "unanswerable_false_positive": bool(ranked),
            }
        )

    return {
        "case_id": normalized["case_id"],
        "question": normalized["question"],
        "category": normalized.get("category"),
        "split": normalized.get("split"),
        "answerability": normalized["answerability"],
        "relevant_paper_ids": sorted(relevant),
        "relevance_judgments": normalized["relevance_judgments"],
        "retrieved_paper_ids": ranked,
        "retrieved_unique_paper_count": len(ranked),
        "metrics": metrics,
    }


def normalized_discounted_cumulative_gain(
    ranked_paper_ids: Sequence[str],
    grade_by_paper: Mapping[str, int],
    *,
    cutoff: int = 10,
) -> float | None:
    """nDCG with exponential gains; null means no positive graded relevance."""

    if cutoff < 1:
        raise ValueError("cutoff must be at least 1")
    positive_grades = [int(grade) for grade in grade_by_paper.values() if int(grade) > 0]
    if not positive_grades:
        return None

    def gain(grade: int, rank: int) -> float:
        return (2.0**grade - 1.0) / math.log2(rank + 1.0)

    ranked = _unique_strings(ranked_paper_ids, field="ranked_paper_ids", line_number=1)
    dcg = sum(gain(int(grade_by_paper.get(paper_id, 0)), rank) for rank, paper_id in enumerate(ranked[:cutoff], start=1))
    ideal = sum(gain(grade, rank) for rank, grade in enumerate(sorted(positive_grades, reverse=True)[:cutoff], start=1))
    return dcg / ideal if ideal else None


def calculate_metrics(
    evaluated: Sequence[Mapping[str, Any]],
    *,
    cutoffs: Sequence[int] = DEFAULT_CUTOFFS,
) -> dict[str, Any]:
    """Macro-average query metrics over their applicable query cohorts."""

    validated_cutoffs = _validate_cutoffs(cutoffs)
    answerable = [item for item in evaluated if item.get("answerability") == "answerable"]
    unanswerable = [item for item in evaluated if item.get("answerability") == "unanswerable"]
    metrics: dict[str, Any] = {
        "question_count": len(evaluated),
        "answerable_question_count": len(answerable),
        "unanswerable_question_count": len(unanswerable),
    }
    for cutoff in validated_cutoffs:
        metrics[f"set_recall_at_{cutoff}"] = _mean_metric(answerable, f"set_recall_at_{cutoff}")
        metrics[f"hit_at_{cutoff}"] = _mean_metric(answerable, f"hit_at_{cutoff}")
        metrics[f"precision_at_{cutoff}"] = _mean_metric(answerable, f"precision_at_{cutoff}")
        metrics[f"unanswerable_false_positive_at_{cutoff}"] = _mean_metric(
            unanswerable, f"unanswerable_false_positive_at_{cutoff}"
        )
    metrics["mrr"] = _mean_metric(answerable, "reciprocal_rank")
    metrics["ndcg_at_10"] = _mean_metric(answerable, "ndcg_at_10")
    metrics["ndcg_at_10_query_count"] = sum(
        _per_query_metrics(item).get("ndcg_at_10") is not None for item in answerable
    )
    metrics["unanswerable_abstention_rate"] = _mean_metric(unanswerable, "unanswerable_abstention")
    metrics["unanswerable_false_positive_rate"] = _mean_metric(unanswerable, "unanswerable_false_positive")
    return {key: _round_metric(value) for key, value in metrics.items()}


def bootstrap_metric_intervals(
    evaluated: Sequence[Mapping[str, Any]],
    *,
    cutoffs: Sequence[int] = DEFAULT_CUTOFFS,
    repetitions: int = DEFAULT_BOOTSTRAP_REPETITIONS,
    confidence_level: float = 0.95,
    seed: int = DEFAULT_BOOTSTRAP_SEED,
    retain_replicates: bool = True,
) -> dict[str, Any]:
    """Bootstrap every reported macro metric over its applicable query cohort."""

    validated_cutoffs = _validate_cutoffs(cutoffs)
    metric_names = [
        *(f"set_recall_at_{cutoff}" for cutoff in validated_cutoffs),
        *(f"hit_at_{cutoff}" for cutoff in validated_cutoffs),
        *(f"precision_at_{cutoff}" for cutoff in validated_cutoffs),
        "reciprocal_rank",
        "ndcg_at_10",
        "unanswerable_abstention",
        "unanswerable_false_positive",
        *(f"unanswerable_false_positive_at_{cutoff}" for cutoff in validated_cutoffs),
    ]
    intervals: dict[str, Any] = {}
    for offset, metric_name in enumerate(metric_names):
        values = [
            float(value)
            for item in evaluated
            if (value := _per_query_metrics(item).get(metric_name)) is not None
        ]
        output_name = {
            "reciprocal_rank": "mrr",
            "unanswerable_abstention": "unanswerable_abstention_rate",
            "unanswerable_false_positive": "unanswerable_false_positive_rate",
        }.get(metric_name, metric_name)
        intervals[output_name] = bootstrap_mean_interval(
            values,
            repetitions=repetitions,
            confidence_level=confidence_level,
            seed=seed + offset,
            retain_replicates=retain_replicates,
        )
    return {
        "method": "metric_specific_query_bootstrap",
        "confidence_level": confidence_level,
        "base_seed": seed,
        "repetitions_per_metric": repetitions,
        "label_uncertainty_included": False,
        "limitation": "Intervals sample evaluation queries only and do not model silver-label or corpus-selection uncertainty.",
        "metrics": intervals,
    }


def evaluate_retrieval(
    session: Session,
    questions: Sequence[Mapping[str, Any]],
    *,
    mode: str = "hybrid",
    top_k: int = 10,
    cutoffs: Sequence[int] = DEFAULT_CUTOFFS,
    bootstrap_repetitions: int = DEFAULT_BOOTSTRAP_REPETITIONS,
    bootstrap_seed: int = DEFAULT_BOOTSTRAP_SEED,
    retain_bootstrap_replicates: bool = True,
    run_config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    validated_cutoffs = _validate_cutoffs(cutoffs)
    required_top_k = max(validated_cutoffs)
    if top_k < required_top_k:
        raise ValueError(f"top_k={top_k} cannot compute requested cutoff {required_top_k}; use top_k >= {required_top_k}.")

    evaluated: list[dict[str, Any]] = []
    warnings: list[str] = []
    observed_vector_providers: set[str] = set()
    for line_number, raw_question in enumerate(questions, start=1):
        question = normalize_question(raw_question, line_number=line_number)
        response = retrieve(session, question["question"], mode=mode, top_k=top_k)
        raw_results = response.get("results", [])
        if not isinstance(raw_results, list):
            raise ValueError("Retriever response 'results' must be a list.")
        ranking_rows = capture_ranking_rows(raw_results)
        paper_ids = [row["paper_id"] for row in ranking_rows]
        query_result = evaluate_ranked_query(question, paper_ids, cutoffs=validated_cutoffs)
        response_warnings = [str(value) for value in response.get("warnings", [])]
        warnings.extend(f"{question['case_id']}: {warning}" for warning in response_warnings)
        vector_provider = response.get("vector_provider")
        if vector_provider:
            observed_vector_providers.add(str(vector_provider))
        evaluated.append(
            {
                **query_result,
                "raw_chunk_result_count": len(raw_results),
                "duplicate_paper_results_removed": len(raw_results) - len(ranking_rows),
                "ranked_results": ranking_rows,
                "retrieval_metadata": {
                    "mode": mode,
                    "vector_provider": vector_provider,
                    "retrieval_strategy": response.get("retrieval_strategy"),
                    "expanded_query": response.get("expanded_query"),
                    "query_expansions": response.get("query_expansions", []),
                    "warnings": response_warnings,
                },
            }
        )

    metrics = calculate_metrics(evaluated, cutoffs=validated_cutoffs)
    statistics = bootstrap_metric_intervals(
        evaluated,
        cutoffs=validated_cutoffs,
        repetitions=bootstrap_repetitions,
        seed=bootstrap_seed,
        retain_replicates=retain_bootstrap_replicates,
    )
    corpus = corpus_descriptor(eligible_chunks(session))
    return {
        "$schema": RESULT_SCHEMA_ID,
        "schema_version": RESULT_SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "run_config": {
            **dict(run_config or {}),
            "mode": mode,
            "top_k": top_k,
            "cutoffs": list(validated_cutoffs),
            "bootstrap_repetitions": bootstrap_repetitions,
            "bootstrap_seed": bootstrap_seed,
            "retain_bootstrap_replicates": retain_bootstrap_replicates,
            "observed_vector_providers": sorted(observed_vector_providers),
            "corpus": corpus,
        },
        "metric_definitions": METRIC_DEFINITIONS,
        "judgment_policy": {
            "unit": "unique_paper",
            "deduplication": "first retrieved chunk establishes each paper's rank",
            "precision_scope": "answerable queries only",
            "unjudged_policy": "unjudged retrieved papers count as non-relevant",
            "abstention_rule": "no unique paper returned",
            "limitation": "Precision assumes the reviewed silver relevance set is complete; interpret it cautiously if relevance pooling is incomplete.",
        },
        "metrics": metrics,
        "statistics": statistics,
        "questions": evaluated,
        "warnings": sorted(set(warnings)),
    }


def capture_ranking_rows(raw_results: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Keep the first chunk for each paper and persist scores needed for audit."""

    rows: list[dict[str, Any]] = []
    seen_papers: set[str] = set()
    score_fields = (
        "score",
        "keyword_score",
        "semantic_score",
        "metadata_score",
        "section_boost",
        "evidence_quality_score",
        "topical_alignment_score",
        "diversity_penalty",
    )
    for raw_rank, result in enumerate(raw_results, start=1):
        paper_id = str(result.get("paper_id") or "").strip()
        if not paper_id or paper_id in seen_papers:
            continue
        seen_papers.add(paper_id)
        row: dict[str, Any] = {
            "rank": len(rows) + 1,
            "raw_chunk_rank": raw_rank,
            "paper_id": paper_id,
            "chunk_id": result.get("chunk_id"),
            "page_start": result.get("page_start"),
            "page_end": result.get("page_end"),
            "section": result.get("section"),
        }
        for field in score_fields:
            value = result.get(field)
            if isinstance(value, (float, int)) and not isinstance(value, bool):
                row[field] = float(value)
        rows.append(row)
    return rows


def build_run_config(
    questions_path: Path,
    *,
    mode: str,
    top_k: int,
    cutoffs: Sequence[int],
) -> dict[str, Any]:
    source = questions_path.resolve()
    return {
        "questions_path": str(source),
        "questions_sha256": _sha256_path(source),
        "mode": mode,
        "top_k": top_k,
        "cutoffs": list(_validate_cutoffs(cutoffs)),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "git_commit": _git_commit(),
        "evaluator_sha256": _sha256_path(Path(__file__)),
    }


def write_results(result: Mapping[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(output_path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate paper retrieval against reviewed relevance judgments.")
    parser.add_argument("--questions", default="data/evaluation/questions.jsonl")
    parser.add_argument(
        "--mode",
        choices=["keyword", "feature_hashing", "dense", "semantic", "hybrid"],
        default="hybrid",
    )
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--cutoffs", type=int, nargs="+", default=list(DEFAULT_CUTOFFS))
    parser.add_argument("--bootstrap-repetitions", type=int, default=DEFAULT_BOOTSTRAP_REPETITIONS)
    parser.add_argument("--bootstrap-seed", type=int, default=DEFAULT_BOOTSTRAP_SEED)
    parser.add_argument("--omit-bootstrap-replicates", action="store_true")
    parser.add_argument("--out", default="data/evaluation/retrieval_eval_results.json")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    questions_path = Path(args.questions)
    try:
        questions = load_questions(questions_path)
        run_config = build_run_config(
            questions_path,
            mode=args.mode,
            top_k=args.top_k,
            cutoffs=args.cutoffs,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"error={exc}")
        raise SystemExit(1) from exc
    create_db_and_tables()
    with Session(engine) as session:
        result = evaluate_retrieval(
            session,
            questions,
            mode=args.mode,
            top_k=args.top_k,
            cutoffs=args.cutoffs,
            bootstrap_repetitions=args.bootstrap_repetitions,
            bootstrap_seed=args.bootstrap_seed,
            retain_bootstrap_replicates=not args.omit_bootstrap_replicates,
            run_config=run_config,
        )
    write_results(result, Path(args.out))
    metrics = result["metrics"]
    print(
        f"question_count={metrics['question_count']} answerable={metrics['answerable_question_count']} "
        f"unanswerable={metrics['unanswerable_question_count']} "
        f"set_recall_at_3={metrics.get('set_recall_at_3')} "
        f"set_recall_at_5={metrics.get('set_recall_at_5')} "
        f"set_recall_at_10={metrics.get('set_recall_at_10')} mrr={metrics.get('mrr')} out={args.out}"
    )


def _mean_metric(rows: Iterable[Mapping[str, Any]], metric_name: str) -> float | None:
    values = [
        float(value)
        for row in rows
        if (value := _per_query_metrics(row).get(metric_name)) is not None
    ]
    return fmean(values) if values else None


def _per_query_metrics(row: Mapping[str, Any]) -> Mapping[str, Any]:
    value = row.get("metrics", {})
    return value if isinstance(value, Mapping) else {}


def _round_metric(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 6)
    return value


def _validate_cutoffs(cutoffs: Sequence[int]) -> tuple[int, ...]:
    validated = tuple(sorted(set(int(cutoff) for cutoff in cutoffs)))
    if not validated or any(cutoff < 1 for cutoff in validated):
        raise ValueError("cutoffs must contain positive integers")
    missing = sorted(set(DEFAULT_CUTOFFS) - set(validated))
    if missing:
        raise ValueError(f"cutoffs must include required values {list(DEFAULT_CUTOFFS)}; missing={missing}")
    return validated


def _unique_strings(values: Sequence[Any], *, field: str, line_number: int) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for raw_value in values:
        value = str(raw_value).strip()
        if not value:
            raise ValueError(f"Question on line {line_number} has a blank {field} entry.")
        if value not in seen:
            seen.add(value)
            output.append(value)
    return output


def _sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_commit() -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout.strip() or None


if __name__ == "__main__":
    main()
