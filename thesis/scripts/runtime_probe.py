#!/usr/bin/env python3
"""Exercise representative public and protected API contracts on a DB copy."""

from __future__ import annotations

import json
import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SOURCE_DB = ROOT / "data" / "papers.db"
OUTPUT = ROOT / "thesis" / "generated" / "runtime_probe.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def generation_provenance() -> dict[str, Any]:
    backend_status = subprocess.run(
        ["git", "status", "--porcelain", "--", "backend"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if backend_status:
        raise RuntimeError("Backend source must be clean before the thesis runtime probe")

    def git_value(*arguments: str) -> str:
        return subprocess.run(
            ["git", *arguments], cwd=ROOT, check=True, capture_output=True, text=True
        ).stdout.strip()

    script = Path(__file__).resolve()
    return {
        "committed_base": {
            "commit": git_value("rev-parse", "HEAD"),
            "tree": git_value("rev-parse", "HEAD^{tree}"),
            "backend_dirty": False,
        },
        "exact_probe": {
            "path": script.relative_to(ROOT).as_posix(),
            "sha256": sha256(script),
        },
        "expected_manuscript_output_dirty_boundary": [
            "thesis/generated/runtime_probe.json",
            "build/thesis.pdf",
        ],
        "semantics": (
            "The commit/tree identify the clean committed backend used by the disposable probe. The exact live "
            "probe script is SHA-256 bound; generated thesis outputs are expected to differ from the committed base."
        ),
    }


def ok(response: Any, label: str) -> Any:
    if response.status_code != 200:
        raise RuntimeError(f"{label}: HTTP {response.status_code}: {response.text[:300]}")
    return response.json()


def compact_results(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "rank": row.get("rank"),
            "paper_id": row.get("paper_id"),
            "chunk_id": row.get("chunk_id"),
            "page_start": row.get("page_start"),
            "page_end": row.get("page_end"),
            "section": row.get("section"),
            "combined_score": (row.get("scores") or {}).get("combined"),
        }
        for row in payload.get("results", [])[:3]
    ]


def main() -> None:
    if not SOURCE_DB.is_file():
        raise FileNotFoundError("data/papers.db is required for the disposable runtime probe")
    with tempfile.TemporaryDirectory(prefix="advisor-thesis-probe-") as directory:
        copied_db = Path(directory) / "papers.db"
        shutil.copy2(SOURCE_DB, copied_db)
        os.environ["TTLAB_DATABASE_URL"] = f"sqlite:///{copied_db}"
        os.environ["TTLAB_DEFAULT_LLM_PROVIDER"] = "offline_extractive"
        os.environ["TTLAB_ALLOW_INSECURE_LOCAL_DEMO"] = "false"
        os.environ["TTLAB_AUTH_ACTORS_JSON"] = "[]"

        from fastapi.testclient import TestClient
        from sqlalchemy import text

        from app.db import engine
        from app.main import app

        def count(table: str) -> int:
            with engine.connect() as connection:
                return int(connection.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar_one())

        before = {name: count(name) for name in ("raganswer", "thesisrecommendation", "reviewevent")}
        with TestClient(app) as client:
            root = ok(client.get("/"), "root")
            health = ok(client.get("/health"), "health")
            ready_response = client.get("/ready")
            readiness = ok(ready_response, "readiness")
            stats = ok(client.get("/api/stats"), "stats")
            diagnostics = ok(client.get("/api/search/diagnostics"), "search diagnostics")
            evaluation = ok(client.get("/api/evaluation/dashboard"), "evaluation dashboard")
            explorer = ok(client.get("/api/explorer/overview"), "explorer overview")

            searches: dict[str, Any] = {}
            # Learned-dense execution is covered by the frozen retrieval and
            # performance runs.  Keep this diagnostic probe memory-bounded so
            # it can execute alongside document builds on a 4 GiB WSL guest.
            for mode in ("keyword", "feature_hashing"):
                result = ok(
                    client.get("/api/search", params={"q": "retrieval augmented generation", "mode": mode, "limit": 5}),
                    f"search {mode}",
                )
                searches[mode] = {
                    "result_count": result.get("result_count"),
                    "warnings": result.get("warnings"),
                    "results": compact_results(result),
                }

            answer = ok(
                client.post(
                    "/api/ask",
                    json={
                        "question": "Which indexed papers discuss retrieval-augmented generation?",
                        "mode": "keyword",
                        "top_k": 5,
                        "audience": "student",
                        "max_words": 180,
                        "provider": "offline_extractive",
                    },
                ),
                "transient answer",
            )
            recommendation = ok(
                client.post(
                    "/api/recommendations/extensions",
                    json={
                        "interests": "RAG, web applications, research discovery",
                        "skills": ["Python", "React", "FastAPI"],
                        "available_time": "semester",
                        "project_type": "software prototype",
                        "data_constraints": "public data preferred",
                        "preferred_difficulty": "medium",
                        "preferred_topics": ["rag", "research discovery"],
                        "avoid_topics": [],
                        "top_k": 3,
                        "retrieval_mode": "keyword",
                        "provider": "offline_deterministic",
                    },
                ),
                "transient recommendation",
            )
            anonymous_admin = client.get("/api/admin/overview")
            anonymous_history = client.get("/api/ask/history")

        after = {name: count(name) for name in ("raganswer", "thesisrecommendation", "reviewevent")}
        if before != after:
            raise RuntimeError(f"Transient public requests mutated history: before={before} after={after}")
        if anonymous_admin.status_code != 401 or anonymous_history.status_code != 401:
            raise RuntimeError("Protected history/admin routes did not fail closed for an anonymous user")

        payload = {
            "schema_version": 2,
            "probe_version": "thesis-runtime-probe-v2",
            "generation_provenance": generation_provenance(),
            "database_source": "data/papers.db",
            "database_mode": "disposable copy",
            "public_requests_persist": False,
            "history_counts_before": before,
            "history_counts_after": after,
            "root": root,
            "health": health,
            "readiness": readiness,
            "stats": {
                key: stats.get(key)
                for key in (
                    "papers", "searchable_papers", "eligible_chunks", "raw_chunks",
                    "keyword_indexed_chunks", "feature_hashing_indexed_chunks", "dense_indexed_chunks",
                    "author_count", "topic_count", "review_event_count", "latest_evaluation_at",
                )
            },
            "search_diagnostics": diagnostics,
            "searches": searches,
            "answer": {
                "grounding_status": answer.get("grounding_status"),
                "provider": answer.get("provider"),
                "model": answer.get("model"),
                "citation_count": len(answer.get("citations", [])),
                "retrieved_chunk_count": len(answer.get("retrieved_chunks", [])),
                "warnings": answer.get("warnings"),
            },
            "recommendation": {
                "grounding_status": recommendation.get("grounding_status"),
                "provider": recommendation.get("provider"),
                "recommendation_count": len(recommendation.get("recommendations", [])),
                "warnings": recommendation.get("warnings"),
            },
            "evaluation_status": {
                key: (evaluation.get(key) or {}).get("status")
                for key in ("retrieval", "qa", "extension", "artifact")
            },
            "explorer": {
                key: explorer.get(key)
                for key in ("topic_count", "author_count", "paper_count", "linked_paper_topics", "linked_author_topics")
            },
            "anonymous_protection": {
                "admin_overview_status": anonymous_admin.status_code,
                "ask_history_status": anonymous_history.status_code,
            },
        }
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote={OUTPUT}")
        print(f"readiness={payload['readiness']['status']} protected=401 transient_persistence=false")


if __name__ == "__main__":
    main()
