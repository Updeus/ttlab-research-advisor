from __future__ import annotations

import argparse
import json
import math
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB = ROOT / "data/papers.db"
DEFAULT_OUTPUT = ROOT / "artifacts/phase6/performance/performance_results.json"
QUERY_WORKLOAD = (
    "retrieval augmented generation",
    "machine learning agriculture crops",
    "telecommunications network optimization",
    "open data platform",
    "customer recommendation system",
    "limitations future work",
)
ANSWER_WORKLOAD = (
    "Which TTLAB papers discuss retrieval-augmented generation?",
    "What research relates to agriculture and machine learning?",
    "Which indexed work discusses open data platforms?",
)


def percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def summarize_samples(samples: list[dict[str, Any]]) -> dict[str, Any]:
    successes = [row for row in samples if row.get("status") == "ok"]
    elapsed = [float(row["elapsed_seconds"]) for row in successes]
    per_unit = [float(row["seconds_per_unit"]) for row in successes if row.get("seconds_per_unit") is not None]
    memory = [int(row["max_rss_kib"]) for row in successes if row.get("max_rss_kib") is not None]
    return {
        "repetitions_attempted": len(samples),
        "repetitions_succeeded": len(successes),
        "failures": len(samples) - len(successes),
        "failure_rate": round((len(samples) - len(successes)) / max(len(samples), 1), 6),
        "elapsed_seconds": {
            "median": round(median(elapsed), 6) if elapsed else None,
            "p95": round(float(percentile(elapsed, 0.95)), 6) if elapsed else None,
            "minimum": round(min(elapsed), 6) if elapsed else None,
            "maximum": round(max(elapsed), 6) if elapsed else None,
        },
        "seconds_per_unit": {
            "median": round(median(per_unit), 9) if per_unit else None,
            "p95": round(float(percentile(per_unit, 0.95)), 9) if per_unit else None,
        },
        "max_rss_kib": max(memory) if memory else None,
    }


def sha256_path(path: Path) -> str | None:
    if not path.is_file():
        return None
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git_value(*args: str) -> str:
    result = subprocess.run(["git", *args], cwd=ROOT, text=True, capture_output=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else ""


def hardware_manifest() -> dict[str, Any]:
    cpu_model = platform.processor()
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.is_file():
        match = re.search(r"^model name\s*:\s*(.+)$", cpuinfo.read_text(errors="replace"), re.MULTILINE)
        if match:
            cpu_model = match.group(1).strip()
    memory_kib = None
    meminfo = Path("/proc/meminfo")
    if meminfo.is_file():
        match = re.search(r"^MemTotal:\s+(\d+)\s+kB", meminfo.read_text(errors="replace"), re.MULTILINE)
        memory_kib = int(match.group(1)) if match else None
    return {
        "platform": platform.platform(),
        "kernel_release": platform.release(),
        "machine": platform.machine(),
        "cpu_model": cpu_model or "unavailable",
        "logical_cpu_count": os.cpu_count(),
        "memory_total_kib": memory_kib,
        "python": platform.python_version(),
        "node": command_version(["node", "--version"]),
        "npm": command_version(["npm", "--version"]),
        "concurrency": 1,
        "device": "CPU",
    }


def command_version(command: list[str]) -> str | None:
    if shutil.which(command[0]) is None:
        return None
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    value = (result.stdout or result.stderr).splitlines()
    return value[0].strip() if value else None


def corpus_manifest(database: Path) -> dict[str, Any]:
    import sqlite3

    if not database.is_file():
        raise FileNotFoundError(database)
    connection = sqlite3.connect(database)
    try:
        scalar = lambda query: connection.execute(query).fetchone()[0]
        return {
            "database_sha256": sha256_path(database),
            "database_bytes": database.stat().st_size,
            "paper_rows": scalar("SELECT COUNT(*) FROM paper"),
            "eligible_papers": scalar("SELECT COUNT(*) FROM paper WHERE corpus_eligibility_status='eligible'"),
            "eligible_papers_with_pdf": scalar(
                "SELECT COUNT(*) FROM paper WHERE corpus_eligibility_status='eligible' AND local_pdf_path IS NOT NULL"
            ),
            "raw_chunks": scalar("SELECT COUNT(*) FROM chunk"),
            "eligible_chunks": scalar(
                "SELECT COUNT(*) FROM chunk JOIN paper USING(paper_id) WHERE paper.corpus_eligibility_status='eligible'"
            ),
            "ocr_completed_papers": scalar("SELECT COUNT(*) FROM paper WHERE ocr_status='completed'"),
            "ocr_pages": scalar("SELECT COALESCE(SUM(ocr_pages_count), 0) FROM paper"),
        }
    finally:
        connection.close()


def _engine(database: Path):
    from sqlmodel import create_engine

    return create_engine(f"sqlite:///{database}", connect_args={"check_same_thread": False})


def _limit(values: list[Any], limit: int | None) -> list[Any]:
    return values if limit is None else values[:limit]


def probe_discovery(_database: Path, limit: int | None, temporary: Path) -> tuple[int, str, dict[str, Any]]:
    from app.config import get_settings
    from app.ingestion.ttlab_page import discover_publications, write_seed

    records = discover_publications(
        get_settings().ttlab_publications_url,
        max_pages=1,
        check_content_type=False,
    )
    records = _limit(records, limit)
    write_seed(records, temporary / "discovered.json")
    return len(records), "publication records", {"source": get_settings().ttlab_publications_url, "pages": 1}


def probe_import(_database: Path, limit: int | None, temporary: Path) -> tuple[int, str, dict[str, Any]]:
    from sqlmodel import SQLModel, Session, create_engine

    from app.ingestion.manual_import import load_seed, upsert_papers

    records = _limit(load_seed(ROOT / "data/seed/papers.json"), limit)
    engine = create_engine(f"sqlite:///{temporary / 'import.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        summary = upsert_papers(session, records)
    return len(records), "publication records", summary


def _eligible_papers(database: Path, *, require_pdf: bool = False, require_extracted: bool = False) -> list[Any]:
    from sqlmodel import Session, select

    from app.models import Paper

    statement = select(Paper).where(Paper.corpus_eligibility_status == "eligible").order_by(Paper.paper_id)
    with Session(_engine(database)) as session:
        papers = list(session.exec(statement).all())
    if require_pdf:
        papers = [paper for paper in papers if paper.local_pdf_path and Path(str(paper.local_pdf_path)).is_file()]
    if require_extracted:
        papers = [
            paper
            for paper in papers
            if paper.extracted_json_path and Path(str(paper.extracted_json_path)).is_file()
        ]
    return papers


def probe_extraction(database: Path, limit: int | None, temporary: Path) -> tuple[int, str, dict[str, Any]]:
    from app.ingestion.pdf_parser import extract_pdf_text

    papers = _limit(_eligible_papers(database, require_pdf=True), limit)
    statuses: dict[str, int] = {}
    for paper in papers:
        result = extract_pdf_text(
            paper.paper_id,
            Path(str(paper.local_pdf_path)),
            temporary / "extracted",
            overwrite=True,
            run_ocr=False,
            expected_title=paper.title,
        )
        status = str(result.get("extraction_status") or "unknown")
        statuses[status] = statuses.get(status, 0) + 1
    return len(papers), "PDF documents", {"statuses": statuses, "ocr": False}


def probe_chunking(database: Path, limit: int | None, _temporary: Path) -> tuple[int, str, dict[str, Any]]:
    from app.indexing.chunker import build_chunks_from_extraction

    papers = _limit(_eligible_papers(database, require_extracted=True), limit)
    chunk_count = 0
    for paper in papers:
        payload = json.loads(Path(str(paper.extracted_json_path)).read_text(encoding="utf-8"))
        chunk_count += len(build_chunks_from_extraction(payload))
    return len(papers), "extracted documents", {"chunks_built": chunk_count}


def probe_keyword_index(database: Path, _limit: int | None, temporary: Path) -> tuple[int, str, dict[str, Any]]:
    from sqlmodel import Session

    from app.indexing.keyword_search import rebuild_keyword_index

    copied = temporary / "keyword.db"
    shutil.copy2(database, copied)
    with Session(_engine(copied)) as session:
        result = rebuild_keyword_index(session)
    return int(result["indexed_chunks"]), "eligible chunks", result


def _vector_index(database: Path, limit: int | None, temporary: Path, provider_name: str) -> tuple[int, str, dict[str, Any]]:
    from sqlmodel import Session

    from app.indexing.embedder import index_chunks

    with Session(_engine(database)) as session:
        result = index_chunks(
            session,
            provider_name=provider_name,
            limit=limit,
            output_path=temporary / f"{provider_name}.json",
            allow_partial=limit is not None,
            update_db_status=False,
            index_role="performance_benchmark",
            allow_model_download=False,
            device="cpu",
        )
    return int(result["indexed_chunks"]), "eligible chunks", {
        "provider": provider_name,
        "indexed_chunks": result["indexed_chunks"],
        "dimensions": result["dimensions"],
        "model_name": result["model_name"],
        "model_revision": result["model_revision"],
        "model_artifact_sha256": result["model_artifact_sha256"],
    }


def probe_feature_hashing_index(database: Path, limit: int | None, temporary: Path) -> tuple[int, str, dict[str, Any]]:
    return _vector_index(database, limit, temporary, "feature_hashing")


def probe_dense_index(database: Path, limit: int | None, temporary: Path) -> tuple[int, str, dict[str, Any]]:
    return _vector_index(database, limit, temporary, "dense")


def _retrieval(database: Path, mode: str) -> tuple[int, str, dict[str, Any]]:
    from sqlmodel import Session

    from app.indexing.retriever import retrieve

    counts: list[int] = []
    with Session(_engine(database)) as session:
        for query in QUERY_WORKLOAD:
            response = retrieve(session, query, mode=mode, top_k=10, include_text=False)
            counts.append(int(response["result_count"]))
    return len(QUERY_WORKLOAD), "queries", {"mode": mode, "result_counts": counts}


def probe_retrieval_keyword(database: Path, _limit: int | None, _temporary: Path) -> tuple[int, str, dict[str, Any]]:
    return _retrieval(database, "keyword")


def probe_retrieval_feature_hashing(database: Path, _limit: int | None, _temporary: Path) -> tuple[int, str, dict[str, Any]]:
    return _retrieval(database, "feature_hashing")


def probe_retrieval_dense(database: Path, _limit: int | None, _temporary: Path) -> tuple[int, str, dict[str, Any]]:
    return _retrieval(database, "dense")


def probe_retrieval_hybrid(database: Path, _limit: int | None, _temporary: Path) -> tuple[int, str, dict[str, Any]]:
    return _retrieval(database, "hybrid")


def probe_answer(database: Path, _limit: int | None, _temporary: Path) -> tuple[int, str, dict[str, Any]]:
    from sqlmodel import Session

    from app.intelligence.rag_answerer import ask_question

    statuses: dict[str, int] = {}
    with Session(_engine(database)) as session:
        for question in ANSWER_WORKLOAD:
            response = ask_question(
                session,
                question,
                mode="hybrid",
                top_k=5,
                provider_name="offline_extractive",
                persist=False,
            )
            status = str(response["grounding_status"])
            statuses[status] = statuses.get(status, 0) + 1
    return len(ANSWER_WORKLOAD), "answers", {"provider": "offline_extractive", "statuses": statuses}


def probe_recommendation(database: Path, _limit: int | None, _temporary: Path) -> tuple[int, str, dict[str, Any]]:
    from sqlmodel import Session

    from app.intelligence.extension_recommender import ExtensionFinderRequest, recommend_extensions

    requests = (
        ExtensionFinderRequest(interests="RAG research discovery", skills=["Python", "React"], top_k=3),
        ExtensionFinderRequest(interests="agriculture machine learning", skills=["Python"], top_k=3),
        ExtensionFinderRequest(interests="network optimization", skills=["statistics"], top_k=3),
    )
    counts: list[int] = []
    with Session(_engine(database)) as session:
        for request in requests:
            response = recommend_extensions(session, request, persist=False)
            counts.append(len(response["recommendations"]))
    return len(requests), "student profiles", {"recommendation_counts": counts, "persistence": False}


def probe_api(database: Path, _limit: int | None, temporary: Path) -> tuple[int, str, dict[str, Any]]:
    copied = temporary / "api.db"
    shutil.copy2(database, copied)
    os.environ["TTLAB_DATABASE_URL"] = f"sqlite:///{copied}"
    os.environ["TTLAB_ALLOW_INSECURE_LOCAL_DEMO"] = "false"
    from fastapi.testclient import TestClient

    from app.main import app

    endpoints = (
        ("/health", None),
        ("/ready", None),
        ("/api/stats", None),
        ("/api/search/diagnostics", None),
        ("/api/search", {"q": "retrieval augmented generation", "mode": "hybrid", "limit": 5}),
        ("/api/explorer/overview", None),
        ("/api/evaluation/dashboard", None),
    )
    statuses: list[int] = []
    with TestClient(app) as client:
        for path, params in endpoints:
            response = client.get(path, params=params)
            statuses.append(response.status_code)
            response.raise_for_status()
    return len(endpoints), "ASGI requests", {"status_codes": statuses, "transport": "FastAPI TestClient"}


def probe_frontend_build(_database: Path, _limit: int | None, _temporary: Path) -> tuple[int, str, dict[str, Any]]:
    result = subprocess.run(
        ["npm", "run", "build"],
        cwd=ROOT / "frontend",
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout)[-1000:])
    assets = list((ROOT / "frontend/dist/assets").glob("*"))
    return 1, "production builds", {"assets": len(assets), "dist_bytes": sum(path.stat().st_size for path in assets)}


def probe_frontend_page_load(
    database: Path,
    *,
    repetitions: int,
    temperature: str,
) -> dict[str, Any]:
    """Measure rendered primary routes against an isolated DB-backed API."""

    runtime_root = Path.cwd()
    with tempfile.TemporaryDirectory(prefix="ttlab-perf-browser-") as temporary_name:
        temporary = Path(temporary_name)
        copied = temporary / "browser.db"
        shutil.copy2(database, copied)
        env = os.environ.copy()
        env.update(
            {
                "PYTHONPATH": str(ROOT / "backend"),
                "TTLAB_DATABASE_URL": f"sqlite:///{copied}",
                "TTLAB_CORS_ORIGINS": '["http://127.0.0.1:5173"]',
                "TTLAB_FRONTEND_URL": "http://127.0.0.1:5173",
                "TTLAB_ALLOW_INSECURE_LOCAL_DEMO": "false",
                "VITE_API_BASE": "http://127.0.0.1:8000",
            }
        )
        build = subprocess.run(
            ["npm", "run", "build"],
            cwd=ROOT / "frontend",
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        if build.returncode != 0:
            raise RuntimeError((build.stderr or build.stdout)[-1000:])
        backend = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"],
            cwd=runtime_root,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            import httpx

            for _ in range(100):
                try:
                    if httpx.get("http://127.0.0.1:8000/health", timeout=0.5).status_code == 200:
                        break
                except Exception:
                    pass
                if backend.poll() is not None:
                    error = backend.stderr.read() if backend.stderr else ""
                    raise RuntimeError(f"Benchmark API exited: {error[-1000:]}")
                time.sleep(0.1)
            else:
                raise RuntimeError("Benchmark API did not become healthy")
            result = subprocess.run(
                [
                    "node",
                    "scripts/benchmark-pages.mjs",
                    "--repetitions",
                    str(repetitions),
                    "--temperature",
                    temperature,
                    "--port",
                    "5173",
                ],
                cwd=ROOT / "frontend",
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            if result.returncode != 0:
                raise RuntimeError((result.stderr or result.stdout)[-2000:])
            payload = json.loads(result.stdout)
        finally:
            backend.terminate()
            try:
                backend.wait(timeout=5)
            except subprocess.TimeoutExpired:
                backend.kill()
                backend.wait(timeout=5)

    samples: list[dict[str, Any]] = []
    for repetition in range(1, repetitions + 1):
        rows = [row for row in payload["rows"] if int(row["repetition"]) == repetition]
        failures = [row for row in rows if row["status"] != "ok"]
        elapsed_seconds = sum(float(row["elapsed_ms"]) for row in rows) / 1000.0
        samples.append(
            {
                "repetition": repetition,
                "status": "failed" if failures else "ok",
                "elapsed_seconds": elapsed_seconds,
                "units": len(rows),
                "unit": "rendered routes",
                "seconds_per_unit": elapsed_seconds / len(rows) if rows else None,
                "details": {
                    "temperature": temperature,
                    "route_elapsed_ms": {row["route"]: round(float(row["elapsed_ms"]), 3) for row in rows},
                    "failures": failures,
                    "browser": "Playwright Chromium",
                    "viewport": "1440x900",
                    "wait_condition": "networkidle and visible main landmark",
                },
            }
        )
    return {"stage": "frontend_page_load", "samples": samples}


PROBES: dict[str, Callable[[Path, int | None, Path], tuple[int, str, dict[str, Any]]]] = {
    "discovery": probe_discovery,
    "import": probe_import,
    "pdf_extraction": probe_extraction,
    "chunking": probe_chunking,
    "keyword_index": probe_keyword_index,
    "feature_hashing_index": probe_feature_hashing_index,
    "dense_index": probe_dense_index,
    "retrieval_keyword": probe_retrieval_keyword,
    "retrieval_feature_hashing": probe_retrieval_feature_hashing,
    "retrieval_dense": probe_retrieval_dense,
    "retrieval_hybrid": probe_retrieval_hybrid,
    "answer_offline": probe_answer,
    "recommendation_offline": probe_recommendation,
    "api_asgi": probe_api,
    "frontend_build": probe_frontend_build,
    # Dispatched specially so the warm series can reuse one browser context.
    "frontend_page_load": probe_frontend_build,
}


def run_probe(
    stage: str,
    database: Path,
    *,
    repetitions: int,
    limit: int | None,
    temperature: str = "warm",
) -> dict[str, Any]:
    if stage == "frontend_page_load":
        return probe_frontend_page_load(database, repetitions=repetitions, temperature=temperature)
    probe = PROBES[stage]
    samples: list[dict[str, Any]] = []
    for repetition in range(1, repetitions + 1):
        with tempfile.TemporaryDirectory(prefix=f"ttlab-perf-{stage}-") as temporary_name:
            started = time.perf_counter()
            try:
                units, unit_name, details = probe(database, limit, Path(temporary_name))
                elapsed = time.perf_counter() - started
                samples.append(
                    {
                        "repetition": repetition,
                        "status": "ok",
                        "elapsed_seconds": elapsed,
                        "units": units,
                        "unit": unit_name,
                        "seconds_per_unit": elapsed / units if units else None,
                        "details": details,
                    }
                )
            except Exception as exc:
                samples.append(
                    {
                        "repetition": repetition,
                        "status": "failed",
                        "elapsed_seconds": time.perf_counter() - started,
                        "error_type": type(exc).__name__,
                        "error": str(exc).replace(str(Path.home()), "~")[:1000],
                    }
                )
    return {"stage": stage, "samples": samples}


def invoke_probe(
    stage: str,
    database: Path,
    *,
    repetitions: int,
    limit: int | None,
    temperature: str,
    runtime_root: Path,
) -> tuple[dict[str, Any], int | None, str]:
    command = [
        sys.executable,
        "-m",
        "app.evaluation.performance_benchmark",
        "--probe",
        stage,
        "--database",
        str(database),
        "--repetitions",
        str(repetitions),
        "--temperature",
        temperature,
    ]
    if limit is not None:
        command.extend(["--document-limit", str(limit)])
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "backend")
    time_binary = Path("/usr/bin/time")
    with tempfile.TemporaryDirectory(prefix="ttlab-perf-time-") as temporary:
        rss_path = Path(temporary) / "rss.txt"
        wrapped = command
        if time_binary.is_file():
            wrapped = [str(time_binary), "-f", "%M", "-o", str(rss_path), *command]
        result = subprocess.run(wrapped, cwd=runtime_root, env=env, text=True, capture_output=True, check=False)
        max_rss = None
        if rss_path.is_file() and rss_path.read_text().strip().isdigit():
            max_rss = int(rss_path.read_text().strip())
    if result.returncode != 0:
        return (
            {
                "stage": stage,
                "samples": [
                    {
                        "status": "failed",
                        "elapsed_seconds": 0.0,
                        "error_type": "SubprocessError",
                        "error": (result.stderr or result.stdout)[-1000:],
                    }
                ],
            },
            max_rss,
            " ".join(command),
        )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Benchmark probe {stage} returned invalid JSON: {result.stdout[-1000:]}") from exc
    return payload, max_rss, " ".join(command)


def benchmark(
    database: Path,
    *,
    profile: str,
    repetitions: int,
    document_limit: int | None,
    stages: list[str],
    runtime_root: Path = ROOT,
) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for stage in stages:
        cold_samples: list[dict[str, Any]] = []
        cold_commands: list[str] = []
        for _ in range(repetitions):
            payload, max_rss, command = invoke_probe(
                stage,
                database,
                repetitions=1,
                limit=document_limit,
                temperature="cold",
                runtime_root=runtime_root,
            )
            for sample in payload["samples"]:
                sample["max_rss_kib"] = max_rss
                sample["repetition"] = len(cold_samples) + 1
                cold_samples.append(sample)
            cold_commands.append(command)
        warm_payload, warm_rss, warm_command = invoke_probe(
            stage,
            database,
            repetitions=repetitions,
            limit=document_limit,
            temperature="warm",
            runtime_root=runtime_root,
        )
        warm_samples = warm_payload["samples"]
        for sample in warm_samples:
            sample["max_rss_kib"] = warm_rss
        results[stage] = {
            "cold": {"summary": summarize_samples(cold_samples), "samples": cold_samples},
            "warm": {"summary": summarize_samples(warm_samples), "samples": warm_samples},
            "commands": {"cold": cold_commands, "warm": warm_command},
        }

    corpus = corpus_manifest(database)
    results["ocr"] = {
        "status": "not_applicable",
        "reason": "No eligible corpus paper used OCR in the frozen snapshot; no OCR latency metric is reported.",
        "ocr_completed_papers": corpus["ocr_completed_papers"],
        "ocr_pages": corpus["ocr_pages"],
    }
    return {
        "schema_version": 1,
        "benchmark_id": f"ttlab-performance-{profile}-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "profile": profile,
        "methodology": {
            "cold_definition": (
                "Each repetition uses a fresh Python process. OS page caches are not flushed, so these are process-cold, not machine-cold runs."
            ),
            "warm_definition": "All repetitions run sequentially in one Python process so module/model caches may be reused.",
            "summary": "Linear-interpolation p95 and median over successful repetitions; failures remain in the denominator.",
            "repetitions": repetitions,
            "document_limit": document_limit,
            "concurrency": 1,
            "runtime_root": str(runtime_root),
            "network_discovery": "one TTLAB archive page per repetition; network and remote-server latency are included",
            "memory": "GNU time maximum resident set size (KiB) for the probe process, where available",
        },
        "hardware": hardware_manifest(),
        "corpus": corpus,
        "git": {
            "commit": git_value("rev-parse", "HEAD"),
            "dirty": bool(git_value("status", "--porcelain")),
        },
        "results": results,
        "limitations": [
            "Process-cold runs do not flush the Linux page cache or model files from the operating-system cache.",
            "The benchmark uses one local process and concurrency one; it is not a capacity, saturation, or multi-user load test.",
            "ASGI timings use FastAPI TestClient and exclude network/TLS latency; browser page timings are recorded separately.",
            "Discovery includes uncontrollable network/server latency and should not be compared directly with local stages.",
            "Maximum RSS is process-level and does not isolate transient shared-library or operating-system cache memory.",
        ],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Benchmark the TTLAB pipeline with repeated process-cold and warm runs.")
    parser.add_argument("--profile", choices=["quick", "full"], default="quick")
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--repetitions", type=int, default=None)
    parser.add_argument("--document-limit", type=int, default=None)
    parser.add_argument("--stage", action="append", choices=sorted(PROBES), dest="stages")
    parser.add_argument("--runtime-root", type=Path, default=ROOT)
    parser.add_argument("--probe", choices=sorted(PROBES), help=argparse.SUPPRESS)
    parser.add_argument("--temperature", choices=["cold", "warm"], default="warm", help=argparse.SUPPRESS)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.probe:
        payload = run_probe(
            args.probe,
            args.database.resolve(),
            repetitions=max(args.repetitions or 1, 1),
            limit=args.document_limit,
            temperature=args.temperature,
        )
        print(json.dumps(payload, ensure_ascii=False))
        return
    repetitions = args.repetitions or (3 if args.profile == "quick" else 3)
    document_limit = args.document_limit if args.document_limit is not None else (3 if args.profile == "quick" else None)
    stages = args.stages or list(PROBES)
    result = benchmark(
        args.database.resolve(),
        profile=args.profile,
        repetitions=repetitions,
        document_limit=document_limit,
        stages=stages,
        runtime_root=args.runtime_root.resolve(),
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    failures = sum(
        mode["summary"]["failures"]
        for stage in result["results"].values()
        if isinstance(stage, dict) and "cold" in stage
        for mode in (stage["cold"], stage["warm"])
    )
    print(json.dumps({"status": "complete", "profile": args.profile, "stages": len(stages), "failures": failures, "out": str(args.out)}, indent=2))


if __name__ == "__main__":
    main()
