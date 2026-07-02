from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from sqlmodel import Session

from app.db import create_db_and_tables, engine
from app.intelligence.paper_artifact_generator import generate_paper_artifacts

DEFAULT_OUTPUT_PATH = Path("data/evaluation/artifact_eval_results.json")


def load_cases(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                cases.append(json.loads(stripped))
    return cases


def evaluate_artifacts(
    session: Session,
    cases: list[dict[str, Any]],
    *,
    persist: bool = False,
) -> dict[str, Any]:
    evaluated_cases = [evaluate_case(session, case, persist=persist) for case in cases]
    return {
        "case_count": len(evaluated_cases),
        "cases": evaluated_cases,
        "metrics": aggregate_metrics(evaluated_cases),
    }


def evaluate_case(session: Session, case: dict[str, Any], *, persist: bool = False) -> dict[str, Any]:
    response = generate_paper_artifacts(
        session,
        case["paper_id"],
        case.get("artifact_types") or ["paper_intelligence_bundle", "podcast_script"],
        overwrite=True if persist else False,
    )
    artifacts = response.get("artifacts", [])
    citation_count = sum(len(artifact.get("citations") or []) for artifact in artifacts)
    artifacts_with_citations = sum(1 for artifact in artifacts if artifact.get("citations"))
    support_counts = count_support_statuses(artifacts)
    return {
        "case_id": case.get("case_id"),
        "paper_id": case.get("paper_id"),
        "artifact_count": len(artifacts),
        "citation_count": citation_count,
        "percentage_artifacts_with_citations": citation_coverage_percentage(artifacts_with_citations, len(artifacts)),
        "grounding_status": response.get("grounding_status"),
        "warnings_count": len(response.get("warnings") or []) + sum(len(artifact.get("warnings") or []) for artifact in artifacts),
        "sections_with_explicit_support": support_counts["explicit"],
        "sections_inferred": support_counts["inferred"],
        "sections_not_found": support_counts["not_found"],
    }


def count_support_statuses(artifacts: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"explicit": 0, "inferred": 0, "not_found": 0}
    for artifact in artifacts:
        payload = artifact.get("generated_json") or {}
        for status in iter_support_statuses(payload):
            if status in counts:
                counts[status] += 1
    return counts


def iter_support_statuses(value: Any) -> list[str]:
    statuses: list[str] = []
    if isinstance(value, dict):
        if value.get("support_status"):
            statuses.append(str(value["support_status"]))
        if value.get("basis") in {"explicit", "inferred", "not_found"}:
            statuses.append(str(value["basis"]))
        for child in value.values():
            statuses.extend(iter_support_statuses(child))
    elif isinstance(value, list):
        for child in value:
            statuses.extend(iter_support_statuses(child))
    return statuses


def citation_coverage_percentage(with_citations: int, artifact_count: int) -> float:
    if artifact_count == 0:
        return 0.0
    return round(with_citations / artifact_count, 4)


def aggregate_metrics(evaluated_cases: list[dict[str, Any]]) -> dict[str, Any]:
    if not evaluated_cases:
        return {
            "average_artifact_count": 0.0,
            "average_citation_count": 0.0,
            "average_citation_coverage": 0.0,
            "grounded_cases": 0,
            "partial_cases": 0,
            "unsupported_cases": 0,
        }
    return {
        "average_artifact_count": round(sum(case["artifact_count"] for case in evaluated_cases) / len(evaluated_cases), 4),
        "average_citation_count": round(sum(case["citation_count"] for case in evaluated_cases) / len(evaluated_cases), 4),
        "average_citation_coverage": round(
            sum(case["percentage_artifacts_with_citations"] for case in evaluated_cases) / len(evaluated_cases),
            4,
        ),
        "grounded_cases": sum(1 for case in evaluated_cases if case["grounding_status"] == "grounded"),
        "partial_cases": sum(1 for case in evaluated_cases if case["grounding_status"] == "partial"),
        "unsupported_cases": sum(1 for case in evaluated_cases if case["grounding_status"] == "unsupported"),
    }


def write_results(result: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate paper intelligence artifact citation coverage.")
    parser.add_argument("--cases", required=True, type=Path)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--persist", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    create_db_and_tables()
    cases = load_cases(args.cases)
    with Session(engine) as session:
        result = evaluate_artifacts(session, cases, persist=args.persist)
    write_results(result, args.out)
    print(f"cases={result['case_count']} output={args.out}")
    print(json.dumps(result["metrics"], indent=2))


if __name__ == "__main__":
    main()
