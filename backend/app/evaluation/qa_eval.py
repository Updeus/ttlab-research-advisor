from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from sqlmodel import Session

from app.db import create_db_and_tables, engine
from app.intelligence.rag_answerer import ask_question


def load_questions(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"QA questions file not found: {path}")
    questions: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        record = json.loads(line)
        if not record.get("gold_paper_ids"):
            raise ValueError(f"Question on line {line_number} has empty gold_paper_ids.")
        questions.append(record)
    return questions


def evaluate_qa(session: Session, questions: list[dict[str, Any]], *, mode: str = "hybrid", top_k: int = 5) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for question in questions:
        response = ask_question(session, str(question["question"]), mode=mode, top_k=top_k)
        cited_paper_ids = sorted({citation["paper_id"] for citation in response["citations"]})
        gold = set(str(paper_id) for paper_id in question["gold_paper_ids"])
        rows.append(
            {
                "question": question["question"],
                "answer_id": response["answer_id"],
                "gold_paper_ids": sorted(gold),
                "cited_paper_ids": cited_paper_ids,
                "any_gold_paper_cited": any(paper_id in gold for paper_id in cited_paper_ids),
                "citation_count": len(response["citations"]),
                "grounding_status": response["grounding_status"],
                "warnings": response["warnings"],
            }
        )
    return {"mode": mode, "top_k": top_k, "question_count": len(rows), "results": rows}


def write_results(result: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate Ask TTLAB citation behavior against manually reviewed questions.")
    parser.add_argument("--questions", default="data/evaluation/qa_questions.jsonl")
    parser.add_argument("--mode", choices=["keyword", "semantic", "hybrid"], default="hybrid")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--out", default="data/evaluation/qa_eval_results.json")
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
        result = evaluate_qa(session, questions, mode=args.mode, top_k=args.top_k)
    write_results(result, Path(args.out))
    print(f"question_count={result['question_count']} out={args.out}")


if __name__ == "__main__":
    main()
