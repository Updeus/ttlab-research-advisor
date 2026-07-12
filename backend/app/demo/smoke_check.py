from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from app.db import create_db_and_tables
from app.main import app

CheckLevel = str


def run_smoke_check(client: TestClient | None = None) -> dict[str, Any]:
    own_client = client is None
    if own_client:
        create_db_and_tables()
        client = TestClient(app)
    assert client is not None

    checks: list[dict[str, Any]] = []
    payloads: dict[str, Any] = {}

    endpoint_plan = [
        ("health", "/health", 200),
        ("stats", "/api/stats", 200),
        ("search_diagnostics", "/api/search/diagnostics", 200),
        ("ask_diagnostics", "/api/ask/diagnostics", 200),
        ("recommendation_diagnostics", "/api/recommendations/extensions/diagnostics", 200),
        ("artifact_diagnostics", "/api/artifacts/diagnostics", 200),
        ("admin_protection", "/api/admin/overview", 401),
        ("evaluation_dashboard", "/api/evaluation/dashboard", 200),
        ("explorer_overview", "/api/explorer/overview", 200),
    ]
    for name, path, expected_status in endpoint_plan:
        payload = check_endpoint(client, name, path, checks, expected_status=expected_status)
        if payload is not None:
            payloads[name] = payload

    stats = payloads.get("stats", {}) if isinstance(payloads.get("stats"), dict) else {}
    search = payloads.get("search_diagnostics", {}) if isinstance(payloads.get("search_diagnostics"), dict) else {}
    explorer = payloads.get("explorer_overview", {}) if isinstance(payloads.get("explorer_overview"), dict) else {}
    artifacts = payloads.get("artifact_diagnostics", {}) if isinstance(payloads.get("artifact_diagnostics"), dict) else {}

    add_threshold_check(checks, "papers_imported", stats.get("papers", 0), "papers available in SQLite")
    add_threshold_check(checks, "chunks_available", stats.get("total_chunks", 0), "full-paper chunks available")
    add_index_health_check(checks, "keyword_index", search.get("keyword"), required=True)
    add_index_health_check(checks, "feature_hashing_index", search.get("feature_hashing"), required=True)
    # A local installation may deliberately omit the optional learned model,
    # but a present, stale, partial, or corrupt dense index is still a failure.
    add_index_health_check(checks, "dense_index", search.get("dense"), required=False)
    add_threshold_check(checks, "topics_built", explorer.get("topic_count", 0), "topic explorer has topics")
    add_threshold_check(checks, "authors_built", explorer.get("author_count", 0), "author explorer has authors")
    add_threshold_check(
        checks,
        "paper_artifacts",
        artifacts.get("total_artifacts", stats.get("total_paper_artifacts", 0)),
        "sample paper artifacts exist",
    )

    counts = {
        "pass": sum(1 for check in checks if check["level"] == "PASS"),
        "warn": sum(1 for check in checks if check["level"] == "WARN"),
        "fail": sum(1 for check in checks if check["level"] == "FAIL"),
    }
    overall = "FAIL" if counts["fail"] else "WARN" if counts["warn"] else "PASS"
    return {
        "overall_status": overall,
        "counts": counts,
        "checks": checks,
        "summary": {
            "papers": stats.get("papers", 0),
            "chunks": stats.get("total_chunks", 0),
            "topics": explorer.get("topic_count", 0),
            "authors": explorer.get("author_count", 0),
            "artifacts": artifacts.get("total_artifacts", stats.get("total_paper_artifacts", 0)),
        },
    }


def check_endpoint(
    client: TestClient,
    name: str,
    path: str,
    checks: list[dict[str, Any]],
    *,
    expected_status: int = 200,
) -> Any | None:
    try:
        response = client.get(path)
    except Exception as exc:
        checks.append({"name": name, "level": "FAIL", "message": f"{path} raised {exc.__class__.__name__}: {exc}"})
        return None
    if response.status_code != expected_status:
        checks.append(
            {
                "name": name,
                "level": "FAIL",
                "message": f"{path} returned HTTP {response.status_code}; expected {expected_status}",
            }
        )
        return None
    checks.append(
        {
            "name": name,
            "level": "PASS",
            "message": f"{path} returned expected HTTP {response.status_code}",
        }
    )
    try:
        return response.json()
    except ValueError:
        return None


def add_threshold_check(checks: list[dict[str, Any]], name: str, value: Any, message: str) -> None:
    numeric = int(value or 0)
    if numeric > 0:
        checks.append({"name": name, "level": "PASS", "message": f"{message}: {numeric}", "value": numeric})
    else:
        checks.append(
            {
                "name": name,
                "level": "WARN",
                "message": f"{message}: 0. Run prepare_demo before a full demo.",
                "value": numeric,
            }
        )


def add_index_health_check(
    checks: list[dict[str, Any]],
    name: str,
    report: Any,
    *,
    required: bool,
) -> None:
    if not isinstance(report, dict):
        level = "FAIL" if required else "WARN"
        checks.append({"name": name, "level": level, "message": "index diagnostics are unavailable"})
        return

    status = str(report.get("status") or report.get("index_status") or "unknown")
    indexed = int(report.get("indexed_chunks") or report.get("keyword_indexed_chunks") or 0)
    eligible = int(report.get("eligible_chunks") or 0)
    completeness = str(report.get("completeness_status") or "unknown")
    errors = [str(error) for error in report.get("errors", [])]
    ready = (
        status == "ready"
        and completeness == "complete"
        and indexed == eligible
        and eligible > 0
        and not errors
    )
    if ready:
        checks.append(
            {
                "name": name,
                "level": "PASS",
                "message": f"complete authoritative coverage: {indexed}/{eligible} eligible chunks",
                "value": indexed,
            }
        )
        return

    missing = status in {"missing", "not_built"} and indexed == 0
    level = "WARN" if missing and not required else "FAIL"
    details = "; ".join(errors) if errors else f"status={status}, completeness={completeness}"
    checks.append(
        {
            "name": name,
            "level": level,
            "message": f"index is not authoritative: {indexed}/{eligible} eligible chunks; {details}",
            "value": indexed,
        }
    )


def main() -> None:
    result = run_smoke_check()
    for check in result["checks"]:
        print(f"{check['level']} {check['name']}: {check['message']}")
    print(f"summary={result['summary']}")
    print(f"counts={result['counts']}")
    print(f"overall_status={result['overall_status']}")


if __name__ == "__main__":
    main()
