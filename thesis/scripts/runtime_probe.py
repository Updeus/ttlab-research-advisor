#!/usr/bin/env python3
"""Exercise representative API paths against a disposable database copy.

This script never writes to data/papers.db. It copies the local database to a
temporary directory, starts FastAPI in-process, and stores compact probe output
for the thesis evidence log.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SOURCE_DB = ROOT / "data" / "papers.db"
OUTPUT = ROOT / "thesis" / "generated" / "runtime_probe.json"


def require_ok(response: Any, label: str) -> dict[str, Any]:
    if response.status_code != 200:
        raise RuntimeError(f"{label} failed: HTTP {response.status_code}: {response.text[:500]}")
    return response.json()


def compact_search(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "query": payload.get("query"),
        "expanded_query": payload.get("expanded_query"),
        "mode": payload.get("mode"),
        "result_count": payload.get("result_count"),
        "warnings": payload.get("warnings"),
        "results": [
            {
                "rank": row.get("rank"),
                "paper_id": row.get("paper_id"),
                "paper_title": row.get("paper_title"),
                "chunk_id": row.get("chunk_id"),
                "page_start": row.get("page_start"),
                "page_end": row.get("page_end"),
                "combined_score": (row.get("scores") or {}).get("combined"),
            }
            for row in payload.get("results", [])
        ],
    }


def compact_answer(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "question": payload.get("question"),
        "answer": payload.get("answer"),
        "grounding_status": payload.get("grounding_status"),
        "provider": payload.get("provider"),
        "model": payload.get("model"),
        "citation_count": len(payload.get("citations", [])),
        "citations": [
            {
                "paper_id": row.get("paper_id"),
                "title": row.get("title"),
                "chunk_id": row.get("chunk_id"),
                "page_start": row.get("page_start"),
                "page_end": row.get("page_end"),
            }
            for row in payload.get("citations", [])
        ],
        "warnings": payload.get("warnings"),
        "unsupported_claims": payload.get("unsupported_claims"),
    }


def main() -> None:
    if not SOURCE_DB.exists():
        raise FileNotFoundError(f"Runtime database missing: {SOURCE_DB}")
    with tempfile.TemporaryDirectory(prefix="advisor-thesis-probe-") as temporary:
        temp_db = Path(temporary) / "papers.db"
        shutil.copy2(SOURCE_DB, temp_db)
        os.environ["TTLAB_DATABASE_URL"] = f"sqlite:///{temp_db}"
        os.environ["TTLAB_DEFAULT_LLM_PROVIDER"] = "offline_extractive"

        # Imports must follow environment setup because app.db creates its engine
        # at module-import time.
        from fastapi.testclient import TestClient

        from app.main import app

        with TestClient(app) as client:
            health = require_ok(client.get("/health"), "health")
            stats = require_ok(client.get("/api/stats"), "stats")
            search_diagnostics = require_ok(client.get("/api/search/diagnostics"), "search diagnostics")
            # Capture these before POST probes add temporary answers and a
            # temporary recommendation to the disposable database copy.
            evaluation = require_ok(client.get("/api/evaluation/dashboard"), "evaluation dashboard")
            admin = require_ok(client.get("/api/admin/overview"), "admin overview")
            explorer = require_ok(client.get("/api/explorer/overview"), "explorer overview")

            searches = []
            for query in [
                "retrieval augmented generation",
                "agriculture artificial intelligence",
                "limitations future work retrieval augmented generation",
            ]:
                payload = require_ok(
                    client.get("/api/search", params={"q": query, "mode": "hybrid", "limit": 5}),
                    f"search: {query}",
                )
                searches.append(compact_search(payload))

            answers = []
            for question in [
                "Which TTLAB papers discuss retrieval-augmented generation?",
                "What research relates to agriculture or AI?",
                "What limitations or future work are reported for the RAG papers?",
            ]:
                payload = require_ok(
                    client.post(
                        "/api/ask",
                        json={
                            "question": question,
                            "mode": "hybrid",
                            "top_k": 5,
                            "audience": "student",
                            "max_words": 220,
                            "provider": "offline_extractive",
                        },
                    ),
                    f"ask: {question}",
                )
                answers.append(compact_answer(payload))

            recommendation = require_ok(
                client.post(
                    "/api/recommendations/extensions",
                    json={
                        "interests": "RAG, web applications, and research discovery",
                        "skills": ["Python", "React", "FastAPI"],
                        "available_time": "semester",
                        "project_type": "software prototype",
                        "data_constraints": "prefer public or synthetic data",
                        "preferred_difficulty": "medium",
                        "preferred_topics": ["RAG", "research discovery"],
                        "avoid_topics": [],
                        "top_k": 3,
                        "retrieval_mode": "hybrid",
                        "provider": "offline_deterministic",
                    },
                ),
                "extension recommendation",
            )
        payload = {
            "generated_at_utc": datetime.now(UTC).isoformat(),
            "database_source": str(SOURCE_DB.relative_to(ROOT)),
            "database_mode": "disposable copy",
            "health": health,
            "stats": {
                key: value
                for key, value in stats.items()
                if not isinstance(value, list)
            },
            "search_diagnostics": search_diagnostics,
            "searches": searches,
            "answers": answers,
            "recommendation": {
                "grounding_status": recommendation.get("grounding_status"),
                "provider": recommendation.get("provider"),
                "model": recommendation.get("model"),
                "warnings": recommendation.get("warnings"),
                "recommendations": [
                    {
                        "rank": row.get("rank"),
                        "paper_id": row.get("paper_id"),
                        "paper_title": row.get("paper_title"),
                        "fit_score": row.get("fit_score"),
                        "difficulty": row.get("difficulty"),
                        "risk_level": row.get("risk_level"),
                        "gap_support_status": (row.get("identified_gap") or {}).get("support_status"),
                        "citation_count": len(row.get("citations", [])),
                    }
                    for row in recommendation.get("recommendations", [])
                ],
            },
            "evaluation": {
                key: {
                    field: value
                    for field, value in evaluation.get(key, {}).items()
                    if field
                    in {
                        "status",
                        "question_count",
                        "answer_count",
                        "case_count",
                        "recommendation_count",
                        "artifact_count",
                        "recall_at_3",
                        "recall_at_5",
                        "mrr",
                        "citation_coverage",
                        "grounding_counts",
                    }
                }
                for key in ["retrieval", "qa", "extension", "artifact"]
            },
            "admin": {
                key: value
                for key, value in admin.items()
                if key != "recent_review_events"
            },
            "explorer": {
                "topic_count": explorer.get("topic_count"),
                "author_count": explorer.get("author_count"),
                "paper_count": explorer.get("paper_count"),
                "linked_paper_topics": explorer.get("linked_paper_topics"),
                "linked_author_topics": explorer.get("linked_author_topics"),
                "explorer_index_status": explorer.get("explorer_index_status"),
                "top_topics": [row.get("name") for row in explorer.get("top_topics", [])],
                "top_authors": [row.get("name") for row in explorer.get("top_authors", [])],
            },
        }
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote={OUTPUT}")
        print(f"searches={len(searches)} answers={len(answers)}")
        print(f"recommendations={len(payload['recommendation']['recommendations'])}")


if __name__ == "__main__":
    main()
