from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from sqlmodel import Session

from app.db import create_db_and_tables, engine
from app.intelligence.extension_recommender import ExtensionFinderRequest, recommend_extensions

DEFAULT_OUTPUT_PATH = Path("data/evaluation/extension_eval_results.json")


def load_cases(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            cases.append(json.loads(stripped))
    return cases


def evaluate_extension_recommendations(
    session: Session,
    cases: list[dict[str, Any]],
    *,
    top_k: int = 5,
    persist: bool = False,
) -> dict[str, Any]:
    evaluated_cases: list[dict[str, Any]] = []
    for case in cases:
        request = request_from_case(case, top_k=top_k)
        response = recommend_extensions(
            session,
            request,
            persist=persist,
            retrieval_scope="technical",
        )
        evaluated_cases.append(evaluate_case(case, response))
    return {
        "case_count": len(evaluated_cases),
        "cases": evaluated_cases,
        "metrics": aggregate_metrics(evaluated_cases),
    }


def request_from_case(case: dict[str, Any], *, top_k: int) -> ExtensionFinderRequest:
    return ExtensionFinderRequest(
        interests=case.get("interests", ""),
        skills=case.get("skills", []),
        available_time=case.get("available_time", "semester"),
        project_type=case.get("project_type", "software prototype"),
        data_constraints=case.get("data_constraints", "prefer public or synthetic data"),
        preferred_difficulty=case.get("preferred_difficulty", "medium"),
        preferred_topics=case.get("expected_relevant_topics", []),
        avoid_topics=case.get("avoid_topics", []),
        top_k=top_k,
        retrieval_mode=case.get("retrieval_mode", "keyword"),
        provider=case.get("provider", "auto"),
    )


def evaluate_case(case: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    recommendations = response.get("recommendations", [])
    citation_count = sum(len(recommendation.get("citations") or []) for recommendation in recommendations)
    cited_paper_ids = {
        citation.get("paper_id")
        for recommendation in recommendations
        for citation in (recommendation.get("citations") or [])
        if citation.get("paper_id")
    }
    with_citations = sum(1 for recommendation in recommendations if recommendation.get("citations"))
    recommendation_count = len(recommendations)
    return {
        "case_id": case.get("case_id"),
        "recommendation_id": response.get("recommendation_id"),
        "recommendation_count": recommendation_count,
        "citation_count": citation_count,
        "cited_paper_count": len(cited_paper_ids),
        "grounding_status": response.get("grounding_status"),
        "percentage_recommendations_with_citations": citation_coverage_percentage(with_citations, recommendation_count),
        "warnings_count": sum(len(recommendation.get("warnings") or []) for recommendation in recommendations)
        + len(response.get("warnings") or []),
        "recommendations": [
            {
                "paper_id": recommendation.get("paper_id"),
                "extension_title": recommendation.get("extension_title"),
                "citation_count": len(recommendation.get("citations") or []),
                "difficulty": recommendation.get("difficulty"),
                "risk_level": recommendation.get("risk_level"),
            }
            for recommendation in recommendations
        ],
    }


def aggregate_metrics(evaluated_cases: list[dict[str, Any]]) -> dict[str, Any]:
    if not evaluated_cases:
        return {
            "average_recommendation_count": 0.0,
            "average_citation_count": 0.0,
            "average_citation_coverage": 0.0,
            "grounded_cases": 0,
            "partial_cases": 0,
            "unsupported_cases": 0,
        }
    return {
        "average_recommendation_count": round(
            sum(case["recommendation_count"] for case in evaluated_cases) / len(evaluated_cases), 4
        ),
        "average_citation_count": round(
            sum(case["citation_count"] for case in evaluated_cases) / len(evaluated_cases), 4
        ),
        "average_citation_coverage": round(
            sum(case["percentage_recommendations_with_citations"] for case in evaluated_cases) / len(evaluated_cases),
            4,
        ),
        "grounded_cases": sum(1 for case in evaluated_cases if case["grounding_status"] == "grounded"),
        "partial_cases": sum(1 for case in evaluated_cases if case["grounding_status"] == "partial"),
        "unsupported_cases": sum(1 for case in evaluated_cases if case["grounding_status"] == "unsupported"),
    }


def citation_coverage_percentage(with_citations: int, recommendation_count: int) -> float:
    if recommendation_count == 0:
        return 0.0
    return round(with_citations / recommendation_count, 4)


def write_results(result: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate Thesis Extension Finder citation coverage.")
    parser.add_argument("--cases", required=True, type=Path)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--persist", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    create_db_and_tables()
    cases = load_cases(args.cases)
    with Session(engine) as session:
        result = evaluate_extension_recommendations(session, cases, top_k=args.top_k, persist=args.persist)
    write_results(result, args.out)
    print(f"cases={result['case_count']} output={args.out}")
    print(json.dumps(result["metrics"], indent=2))


if __name__ == "__main__":
    main()
