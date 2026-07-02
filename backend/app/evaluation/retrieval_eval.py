from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from sqlmodel import Session

from app.db import create_db_and_tables, engine
from app.indexing.retriever import retrieve


def load_questions(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Evaluation questions file not found: {path}")
    questions: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        record = json.loads(line)
        if not isinstance(record.get("gold_paper_ids"), list) or not record["gold_paper_ids"]:
            raise ValueError(f"Question on line {line_number} has empty gold_paper_ids.")
        questions.append(record)
    return questions


def calculate_metrics(evaluated: list[dict[str, Any]]) -> dict[str, Any]:
    if not evaluated:
        return {"question_count": 0, "recall_at_3": 0.0, "recall_at_5": 0.0, "mrr": 0.0}
    recall3 = sum(1 for item in evaluated if item["hit_at_3"]) / len(evaluated)
    recall5 = sum(1 for item in evaluated if item["hit_at_5"]) / len(evaluated)
    mrr = sum(item["reciprocal_rank"] for item in evaluated) / len(evaluated)
    return {
        "question_count": len(evaluated),
        "recall_at_3": round(recall3, 6),
        "recall_at_5": round(recall5, 6),
        "mrr": round(mrr, 6),
    }


def evaluate_retrieval(
    session: Session,
    questions: list[dict[str, Any]],
    *,
    mode: str = "hybrid",
    top_k: int = 5,
) -> dict[str, Any]:
    evaluated: list[dict[str, Any]] = []
    warnings: list[str] = []
    for question in questions:
        gold = set(str(paper_id) for paper_id in question.get("gold_paper_ids", []))
        response = retrieve(session, str(question["question"]), mode=mode, top_k=top_k)
        result_papers = [result["paper_id"] for result in response["results"]]
        first_hit_rank = next((index for index, paper_id in enumerate(result_papers, start=1) if paper_id in gold), None)
        if not gold:
            warnings.append(f"Question has no gold labels: {question['question']}")
        evaluated.append(
            {
                "question": question["question"],
                "gold_paper_ids": sorted(gold),
                "retrieved_paper_ids": result_papers,
                "hit_at_3": any(paper_id in gold for paper_id in result_papers[:3]),
                "hit_at_5": any(paper_id in gold for paper_id in result_papers[:5]),
                "first_hit_rank": first_hit_rank,
                "reciprocal_rank": 0.0 if first_hit_rank is None else 1.0 / first_hit_rank,
                "warnings": response.get("warnings", []),
            }
        )
    metrics = calculate_metrics(evaluated)
    return {"mode": mode, "top_k": top_k, "metrics": metrics, "questions": evaluated, "warnings": warnings}


def write_results(result: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate retrieval against manually reviewed gold paper IDs.")
    parser.add_argument("--questions", default="data/evaluation/questions.jsonl")
    parser.add_argument("--mode", choices=["keyword", "semantic", "hybrid"], default="hybrid")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--out", default="data/evaluation/retrieval_eval_results.json")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        questions = load_questions(Path(args.questions))
    except (FileNotFoundError, ValueError) as exc:
        print(f"error={exc}")
        raise SystemExit(1)
    create_db_and_tables()
    with Session(engine) as session:
        result = evaluate_retrieval(session, questions, mode=args.mode, top_k=args.top_k)
    write_results(result, Path(args.out))
    metrics = result["metrics"]
    print(
        "question_count={question_count} recall_at_3={recall_at_3} "
        "recall_at_5={recall_at_5} mrr={mrr} out={out}".format(**metrics, out=args.out)
    )


if __name__ == "__main__":
    main()
