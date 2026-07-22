#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

import httpx
from sqlmodel import Session, func, select

from app.config import get_settings
from app.db import engine
from app.evaluation.qa_faithfulness_eval import (
    canonical_json_sha256,
    extract_inline_source_ids,
    load_jsonl,
    segment_atomic_claims,
    sha256_path,
    source_overlap_suggestion,
    write_jsonl,
)
from app.indexing.embedder import (
    DEFAULT_INDEX_PATH,
    DENSE_INDEX_PATH,
    DENSE_PROVIDER,
    FEATURE_HASHING_PROVIDER,
    validate_index_manifest,
)
from app.indexing.keyword_search import diagnostics as keyword_diagnostics
from app.indexing.retriever import RetrievalScope
from app.intelligence.llm_provider import build_ollama_prompt, order_context_chunks_for_question
from app.intelligence.rag_answerer import ask_question
from app.models import Chunk, Paper, RAGAnswer


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RETRIEVAL_SET = PROJECT_ROOT / "data/evaluation/retrieval_silver_v1.jsonl"
RETRIEVAL_MANIFEST = PROJECT_ROOT / "data/evaluation/retrieval_silver_v1.manifest.json"
QA_CASES = PROJECT_ROOT / "data/evaluation/qa_faithfulness_cases_v1.jsonl"
QA_CASE_SCHEMA = PROJECT_ROOT / "data/evaluation/qa_faithfulness_cases_v1.schema.json"
PHASE3_ROOT = PROJECT_ROOT / "artifacts/phase3/qa"
PRIVATE_ROOT = PROJECT_ROOT / "artifacts/phase3/private/qa"
OLLAMA_AVAILABILITY = PHASE3_ROOT / "ollama_availability_v1.json"
REVIEWER_ID = "codex-ai-review"
REVIEWER_TYPE = "ai"
EVALUATION_RETRIEVAL_SCOPE: RetrievalScope = "technical"

HEURISTIC_RETRIEVER_CONFIGURATION = {
    "configuration_status": "current_untuned_heuristic_baseline",
    "keyword_weight": 0.42,
    "vector_weight": 0.48,
    "metadata_score_max": 0.16,
    "section_boost_max": 0.08,
    "topical_alignment_range": [-0.22, 0.10],
    "evidence_quality_range": [-0.22, 0.08],
    "diversity_penalty_max": 0.16,
    "candidate_pool_multiplier": 3,
    "warning": "Values are hand-authored heuristics from the exact retriever source hash, not development-set tuning results.",
}


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def build_cases() -> list[dict[str, Any]]:
    retrieval_rows = sorted(load_jsonl(RETRIEVAL_SET), key=lambda row: str(row["case_id"]))
    cases: list[dict[str, Any]] = []
    with Session(engine) as session:
        for position, source in enumerate(retrieval_rows, start=1):
            qa_case_id = f"qa-silver-{position:03d}"
            supporting_sources: list[dict[str, Any]] = []
            for evidence in source.get("supporting_evidence", []):
                chunk = session.get(Chunk, str(evidence["chunk_id"]))
                if chunk is None:
                    raise ValueError(f"Missing linked source chunk {evidence['chunk_id']} for {source['case_id']}")
                if chunk.paper_id != evidence["paper_id"] or chunk.source_hash != evidence["source_hash"]:
                    raise ValueError(f"Source snapshot mismatch for {evidence['chunk_id']}")
                paper = session.get(Paper, chunk.paper_id)
                if paper is None:
                    raise ValueError(f"Missing paper {chunk.paper_id}")
                supporting_sources.append(
                    {
                        **evidence,
                        "paper_title": paper.title,
                        "pdf_sha256": _optional_sha256(_project_path(paper.local_pdf_path)),
                        "extracted_json_sha256": _optional_sha256(_project_path(paper.extracted_json_path)),
                    }
                )

            answer_points = _answer_points(qa_case_id, source)
            cases.append(
                {
                    "qa_case_id": qa_case_id,
                    "retrieval_case_id": source["case_id"],
                    "question": source["question"],
                    "category": source["category"],
                    "answerability": source["answerability"],
                    "split": source["split"],
                    "answer_points": answer_points,
                    "supporting_sources": supporting_sources,
                    "relevant_paper_ids": source["relevant_paper_ids"],
                    "distractor_paper_ids": source.get("distractor_paper_ids", []),
                    "corpus_absence_check": source.get("corpus_absence_check"),
                    "label_source": {
                        "dataset": str(RETRIEVAL_SET.relative_to(PROJECT_ROOT)),
                        "dataset_sha256": sha256_path(RETRIEVAL_SET),
                        "source_case_id": source["case_id"],
                        "label_quality": "ai_reviewed_silver",
                        "reviewer_type": source["reviewer_type"],
                        "creation_pass": source["creation_annotation"],
                        "verification_pass": {
                            "verifier_id": source["verifier_id"],
                            "reviewer_type": source["reviewer_type"],
                            "pass": source["pass"],
                            "timestamp": source["timestamp"],
                            "decision": source["decision"],
                        },
                    },
                    "created_at": utc_now(),
                }
            )
    write_jsonl(cases, QA_CASES)
    return cases


def _answer_points(case_id: str, source: Mapping[str, Any]) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    metadata = list(source.get("metadata_assertions", []))
    if metadata:
        for assertion in metadata:
            authors = [str(value) for value in assertion.get("authors", [])]
            points.extend(
                [
                    {
                        "answer_point_id": f"{case_id}-point-{len(points) + 1:02d}",
                        "point_type": "metadata_authorship",
                        "text": f"The authors are {', '.join(authors)}.",
                        "paper_ids": [assertion["paper_id"]],
                        "source_chunk_ids": [
                            evidence["chunk_id"]
                            for evidence in source.get("supporting_evidence", [])
                            if evidence["paper_id"] == assertion["paper_id"]
                        ],
                    },
                    {
                        "answer_point_id": f"{case_id}-point-{len(points) + 2:02d}",
                        "point_type": "metadata_venue",
                        "text": f"The recorded venue is {assertion.get('venue') or 'not verified'}.",
                        "paper_ids": [assertion["paper_id"]],
                        "source_chunk_ids": [
                            evidence["chunk_id"]
                            for evidence in source.get("supporting_evidence", [])
                            if evidence["paper_id"] == assertion["paper_id"]
                        ],
                    },
                ]
            )
        return points

    for evidence in source.get("supporting_evidence", []):
        points.append(
            {
                "answer_point_id": f"{case_id}-point-{len(points) + 1:02d}",
                "point_type": "source_supported_content",
                "text": evidence["evidence_summary"],
                "paper_ids": [evidence["paper_id"]],
                "source_chunk_ids": [evidence["chunk_id"]],
            }
        )
    return points


def generate_evaluation_answer(
    session: Session,
    case: Mapping[str, Any],
    *,
    mode: str,
    provider: str,
    model: str | None,
    top_k: int,
    retrieval_scope: RetrievalScope,
) -> dict[str, Any]:
    """Run one offline case against the declared technical evaluation corpus."""

    return ask_question(
        session,
        str(case["question"]),
        mode=mode,
        top_k=top_k,
        provider_name=provider,
        model_name=model,
        persist=False,
        retrieval_scope=retrieval_scope,
    )


def run_answers(
    *,
    mode: str,
    provider: str,
    model: str | None,
    top_k: int,
    output_stem: str,
    retrieval_scope: RetrievalScope,
) -> dict[str, Any]:
    cases = load_jsonl(QA_CASES)
    output_path = PHASE3_ROOT / f"{output_stem}_answers_v1.jsonl"
    private_path = PRIVATE_ROOT / f"{output_stem}_raw_inputs_outputs_v1.jsonl"
    manifest_path = PHASE3_ROOT / f"{output_stem}_run_manifest_v1.json"
    PHASE3_ROOT.mkdir(parents=True, exist_ok=True)
    PRIVATE_ROOT.mkdir(parents=True, exist_ok=True)

    code_paths = _evaluation_code_paths()
    before_hashes = {str(path.relative_to(PROJECT_ROOT)): sha256_path(path) for path in code_paths}
    started_at = utc_now()
    public_rows: list[dict[str, Any]] = []
    private_rows: list[dict[str, Any]] = []
    with Session(engine) as session:
        index_health = _index_health(session)
        stored_before = session.exec(select(func.count()).select_from(RAGAnswer)).one()
        for position, case in enumerate(cases, start=1):
            start = time.perf_counter()
            response = generate_evaluation_answer(
                session,
                case,
                mode=mode,
                top_k=top_k,
                provider=provider,
                model=model,
                retrieval_scope=retrieval_scope,
            )
            elapsed = time.perf_counter() - start
            source_map = _source_map_for_response(case["question"], response)
            segmentation = segment_atomic_claims(
                response["answer"],
                case_id=case["qa_case_id"],
                source_map=source_map,
            )
            retrieved_by_id = {str(chunk["chunk_id"]): chunk for chunk in response["retrieved_chunks"]}
            for claim in segmentation["claims"]:
                source_texts = [
                    str(retrieved_by_id[source_id].get("text") or retrieved_by_id[source_id].get("snippet") or "")
                    for source_id in claim["inline_source_ids"]
                    if source_id in retrieved_by_id
                ]
                claim["lexical_reviewer_aid"] = source_overlap_suggestion(claim, source_texts)

            source_records = _source_records(session, response)
            raw_request = {
                "question": case["question"],
                "mode": mode,
                "top_k": top_k,
                "provider": provider,
                "model": model,
                "retrieval_scope": retrieval_scope,
                "audience": "general",
                "max_words": 250,
                "retrieved_chunks": response["retrieved_chunks"],
            }
            if response["provider"] == "ollama":
                raw_request["raw_prompt"] = build_ollama_prompt(
                    str(case["question"]), response["retrieved_chunks"], audience="general", max_words=250
                )
            else:
                raw_request["raw_prompt"] = None
                raw_request["prompt_applicability"] = (
                    "The offline extractive algorithm accepts structured question/context arguments and has no free-text prompt."
                )

            private_record = {
                "qa_case_id": case["qa_case_id"],
                "captured_at": utc_now(),
                "request": raw_request,
                "response": response,
                "source_records": source_records,
            }
            private_rows.append(private_record)
            public_rows.append(
                {
                    "qa_case_id": case["qa_case_id"],
                    "retrieval_case_id": case["retrieval_case_id"],
                    "question": case["question"],
                    "category": case["category"],
                    "answerability": case["answerability"],
                    "split": case["split"],
                    "answer_points": case["answer_points"],
                    "answer": response["answer"],
                    "answer_sha256": hashlib.sha256(response["answer"].encode("utf-8")).hexdigest(),
                    "answer_id": response["answer_id"],
                    "provider": response["provider"],
                    "model": response["model"],
                    "requested_provider": provider,
                    "requested_model": model,
                    "retrieval_mode": response["retrieval_mode"],
                    "top_k": response["top_k"],
                    "runtime_grounding_status_legacy": response["grounding_status"],
                    "runtime_grounding_limitation": (
                        "Legacy runtime status checks citation structure and lexical overlap only; it is not factual correctness."
                    ),
                    "citations": [_public_citation(citation) for citation in response["citations"]],
                    "returned_citation_ids": [citation["chunk_id"] for citation in response["citations"]],
                    "retrieved_sources": [_public_retrieved(chunk) for chunk in response["retrieved_chunks"]],
                    "retrieval_metadata": response["retrieval_metadata"],
                    "generation_metadata": response["generation_metadata"],
                    "warnings": response["warnings"],
                    "runtime_unsupported_claim_warnings": response["unsupported_claims"],
                    "source_map": source_map,
                    "segmentation": segmentation,
                    "did_abstain": segmentation["did_abstain"],
                    "wall_seconds": round(elapsed, 6),
                    "captured_at": utc_now(),
                    "private_raw_record_sha256": canonical_json_sha256(private_record),
                    "private_raw_record_path": str(private_path.relative_to(PROJECT_ROOT)),
                }
            )
            print(
                f"case={position}/{len(cases)} id={case['qa_case_id']} provider={response['provider']} "
                f"claims={len(segmentation['claims'])} abstain={segmentation['did_abstain']} seconds={elapsed:.3f}",
                flush=True,
            )
        stored_after = session.exec(select(func.count()).select_from(RAGAnswer)).one()
    if stored_before != stored_after:
        raise RuntimeError(f"Evaluation mutated RAG answer history: before={stored_before} after={stored_after}")

    write_jsonl(private_rows, private_path)
    write_jsonl(public_rows, output_path)
    after_hashes = {str(path.relative_to(PROJECT_ROOT)): sha256_path(path) for path in code_paths}
    if before_hashes != after_hashes:
        raise RuntimeError("Evaluation code changed while answers were being generated")

    manifest = {
        "experiment_id": f"ttlab-qa-faithfulness-{output_stem}-v1",
        "status": "executed",
        "started_at": started_at,
        "completed_at": utc_now(),
        "case_count": len(public_rows),
        "category_counts": dict(sorted(Counter(row["category"] for row in public_rows).items())),
        "answerability_counts": dict(sorted(Counter(row["answerability"] for row in public_rows).items())),
        "requested_configuration": {
            "retrieval_mode": mode,
            "top_k": top_k,
            "provider": provider,
            "model": model,
            "retrieval_scope": retrieval_scope,
            "audience": "general",
            "max_words": 250,
            "persist": False,
            "retriever": HEURISTIC_RETRIEVER_CONFIGURATION,
        },
        "observed_providers": dict(sorted(Counter(row["provider"] for row in public_rows).items())),
        "observed_models": dict(sorted(Counter(row["model"] for row in public_rows).items())),
        "fallback_case_ids": [
            row["qa_case_id"] for row in public_rows if row["provider"] != provider and provider != "offline_extractive"
        ],
        "latency": _latency_summary([float(row["wall_seconds"]) for row in public_rows]),
        "input": {
            "qa_cases_path": str(QA_CASES.relative_to(PROJECT_ROOT)),
            "qa_cases_sha256": sha256_path(QA_CASES),
            "retrieval_set_path": str(RETRIEVAL_SET.relative_to(PROJECT_ROOT)),
            "retrieval_set_sha256": sha256_path(RETRIEVAL_SET),
            "retrieval_manifest_sha256": sha256_path(RETRIEVAL_MANIFEST),
        },
        "output": {
            "public_answers_path": str(output_path.relative_to(PROJECT_ROOT)),
            "public_answers_sha256": sha256_path(output_path),
            "private_raw_path": str(private_path.relative_to(PROJECT_ROOT)),
            "private_raw_sha256": sha256_path(private_path),
            "private_raw_policy": (
                "Untracked local evidence contains full extracted page/chunk text; the public artifact retains identifiers, "
                "hashes, bounded snippets, answers, judgments, and prompts/configuration without redistributing full PDFs."
            ),
        },
        "index_health": index_health,
        "code": {
            "git_commit": _git_commit(),
            "working_tree_dirty": _working_tree_dirty(),
            "file_sha256": before_hashes,
        },
        "environment": environment_snapshot(),
        "database_nonmutation_check": {
            "stored_rag_answers_before": stored_before,
            "stored_rag_answers_after": stored_after,
            "passed": stored_before == stored_after,
        },
        "methodological_status": (
            "Executed deterministic offline answer baseline over the frozen AI-reviewed silver QA set. "
            "Quality judgments are performed separately in two AI review passes."
        ),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest


def check_ollama() -> dict[str, Any]:
    settings = get_settings()
    cli = shutil.which("ollama")
    payload: dict[str, Any] = {
        "check_id": "ttlab-qa-ollama-availability-v1",
        "checked_at": utc_now(),
        "base_url": settings.ollama_base_url,
        "configured_default_model": settings.ollama_default_model,
        "configured_num_ctx": settings.ollama_num_ctx,
        "configured_temperature": 0.1,
        "configured_top_p": 0.9,
        "configured_keep_alive": settings.ollama_keep_alive,
        "cli": {
            "found": bool(cli),
            "path": cli,
            "binary_sha256": sha256_path(Path(cli)) if cli and Path(cli).is_file() else None,
        },
        "requests": [],
        "installed_models": [],
        "status": "unavailable",
        "comparison_status": "not_run",
        "environment": environment_snapshot(),
    }
    if cli:
        payload["cli"]["version_probe"] = _subprocess_probe([cli, "--version"], timeout=5)
        payload["cli"]["list_probe"] = _subprocess_probe([cli, "list"], timeout=5)
    for endpoint in ("/api/version", "/api/tags", "/api/ps"):
        url = f"{settings.ollama_base_url.rstrip('/')}{endpoint}"
        try:
            started = time.perf_counter()
            response = httpx.get(url, timeout=5.0)
            elapsed = time.perf_counter() - started
            record = {
                "endpoint": endpoint,
                "status_code": response.status_code,
                "wall_seconds": round(elapsed, 6),
                "response": response.json(),
            }
            payload["requests"].append(record)
            if endpoint == "/api/tags" and response.status_code == 200:
                for model in record["response"].get("models", []):
                    installed = {
                        "name": model.get("name"),
                        "model": model.get("model"),
                        "digest": model.get("digest"),
                        "size": model.get("size"),
                        "modified_at": model.get("modified_at"),
                        "details": model.get("details", {}),
                    }
                    payload["installed_models"].append(installed)
        except Exception as exc:
            payload["requests"].append(
                {
                    "endpoint": endpoint,
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "error": _bounded_error(exc),
                }
            )
    if any(record.get("endpoint") == "/api/tags" and record.get("status_code") == 200 for record in payload["requests"]):
        payload["status"] = "available"
        payload["comparison_status"] = "eligible_to_run" if payload["installed_models"] else "not_run_no_models"
    else:
        payload["unavailable_reason"] = (
            "The Ollama CLI binary exists, but the configured localhost service did not answer the executed version, "
            "tags, or process probes. No model tag, digest, quantization, latency, or quality result is claimed."
        )
    OLLAMA_AVAILABILITY.parent.mkdir(parents=True, exist_ok=True)
    OLLAMA_AVAILABILITY.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return payload


def _source_map_for_response(question: str, response: Mapping[str, Any]) -> dict[str, str]:
    ordered = order_context_chunks_for_question(question, list(response.get("retrieved_chunks", [])))
    result = {str(chunk["chunk_id"]): str(chunk["chunk_id"]) for chunk in ordered}
    for index, chunk in enumerate(ordered[:8], start=1):
        result[f"S{index}"] = str(chunk["chunk_id"])
    return result


def _source_records(session: Session, response: Mapping[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in response.get("retrieved_chunks", []):
        chunk_id = str(source["chunk_id"])
        if chunk_id in seen:
            continue
        seen.add(chunk_id)
        chunk = session.get(Chunk, chunk_id)
        paper = session.get(Paper, chunk.paper_id) if chunk else None
        page_records = _load_page_records(paper, chunk.page_start, chunk.page_end) if paper and chunk else []
        records.append(
            {
                "chunk_id": chunk_id,
                "paper_id": source["paper_id"],
                "paper_title": source["title"],
                "page_start": source.get("page_start"),
                "page_end": source.get("page_end"),
                "section": source.get("section"),
                "chunk_source_hash": chunk.source_hash if chunk else None,
                "chunk_text": source.get("text") or source.get("snippet") or "",
                "pages": page_records,
                "local_pdf_sha256": _optional_sha256(_project_path(paper.local_pdf_path)) if paper else None,
                "extracted_json_sha256": _optional_sha256(_project_path(paper.extracted_json_path)) if paper else None,
            }
        )
    return records


def _load_page_records(paper: Paper, page_start: int | None, page_end: int | None) -> list[dict[str, Any]]:
    path = _project_path(paper.extracted_json_path)
    if path is None or not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    start = page_start or 1
    end = page_end or start
    rows: list[dict[str, Any]] = []
    for page in data.get("pages", []):
        page_number = int(page.get("page_number") or 0)
        if start <= page_number <= end:
            rows.append(
                {
                    "page_number": page_number,
                    "text": page.get("text", ""),
                    "text_sha256": hashlib.sha256(str(page.get("text", "")).encode("utf-8")).hexdigest(),
                    "extraction_method": page.get("extraction_method"),
                    "ocr_status": page.get("ocr_status"),
                    "review_required": page.get("review_required"),
                    "provenance": page.get("provenance", {}),
                }
            )
    return rows


def _public_citation(citation: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: citation.get(key)
        for key in (
            "paper_id",
            "title",
            "authors",
            "year",
            "chunk_id",
            "section",
            "page_start",
            "page_end",
            "snippet",
            "score",
            "source_url",
            "pdf_url",
        )
    }


def _public_retrieved(chunk: Mapping[str, Any]) -> dict[str, Any]:
    text = str(chunk.get("text") or chunk.get("snippet") or "")
    return {
        key: chunk.get(key)
        for key in (
            "chunk_id",
            "paper_id",
            "title",
            "authors",
            "year",
            "page_start",
            "page_end",
            "section",
            "snippet",
            "scores",
            "source",
        )
    } | {"full_text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}


def _index_health(session: Session) -> dict[str, Any]:
    return {
        "keyword": keyword_diagnostics(session),
        "feature_hashing": validate_index_manifest(
            session, index_path=DEFAULT_INDEX_PATH, provider_name=FEATURE_HASHING_PROVIDER
        ),
        "dense": validate_index_manifest(session, index_path=DENSE_INDEX_PATH, provider_name=DENSE_PROVIDER),
    }


def environment_snapshot() -> dict[str, Any]:
    cpu_model = None
    cpu_path = Path("/proc/cpuinfo")
    if cpu_path.exists():
        for line in cpu_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.lower().startswith("model name"):
                cpu_model = line.split(":", 1)[-1].strip()
                break
    total_memory_kib = None
    mem_path = Path("/proc/meminfo")
    if mem_path.exists():
        for line in mem_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("MemTotal:"):
                total_memory_kib = int(line.split()[1])
                break
    return {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "cpu_model": cpu_model,
        "logical_cpu_count": os.cpu_count(),
        "memory_total_kib": total_memory_kib,
        "gpu_probe": _subprocess_probe(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"], 5),
    }


def _evaluation_code_paths() -> list[Path]:
    paths = [
        PROJECT_ROOT / "backend/app/evaluation/qa_faithfulness_eval.py",
        PROJECT_ROOT / "backend/app/indexing/retriever.py",
        PROJECT_ROOT / "backend/app/indexing/keyword_search.py",
        PROJECT_ROOT / "backend/app/indexing/vector_store.py",
        PROJECT_ROOT / "backend/app/intelligence/rag_answerer.py",
        PROJECT_ROOT / "backend/app/intelligence/llm_provider.py",
        PROJECT_ROOT / "backend/app/intelligence/citation_verifier.py",
        Path(__file__).resolve(),
    ]
    return [path for path in paths if path.exists()]


def _latency_summary(values: list[float]) -> dict[str, Any]:
    ordered = sorted(values)
    return {
        "case_count": len(values),
        "cold_or_first_seconds": values[0] if values else None,
        "warm_mean_seconds_excluding_first": round(sum(values[1:]) / len(values[1:]), 6) if len(values) > 1 else None,
        "median_seconds": _quantile(ordered, 0.5),
        "p95_seconds": _quantile(ordered, 0.95),
        "minimum_seconds": min(values) if values else None,
        "maximum_seconds": max(values) if values else None,
        "scope": "End-to-end retrieval plus deterministic answer composition wall time on this machine.",
    }


def _quantile(ordered: list[float], probability: float) -> float | None:
    if not ordered:
        return None
    index = (len(ordered) - 1) * probability
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    weight = index - lower
    return round(ordered[lower] * (1 - weight) + ordered[upper] * weight, 6)


def _project_path(value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _optional_sha256(path: Path | None) -> str | None:
    return sha256_path(path) if path and path.exists() and path.is_file() else None


def _git_commit() -> str | None:
    probe = _subprocess_probe(["git", "rev-parse", "HEAD"], 5, cwd=PROJECT_ROOT)
    return probe.get("stdout", "").strip() or None if probe.get("returncode") == 0 else None


def _working_tree_dirty() -> bool:
    probe = _subprocess_probe(["git", "status", "--porcelain"], 5, cwd=PROJECT_ROOT)
    return bool(probe.get("stdout", "").strip())


def _subprocess_probe(command: list[str], timeout: int, cwd: Path | None = None) -> dict[str, Any]:
    try:
        result = subprocess.run(command, cwd=cwd, text=True, capture_output=True, timeout=timeout, check=False)
        return {
            "command": command,
            "returncode": result.returncode,
            "stdout": result.stdout[:4000],
            "stderr": result.stderr[:4000],
        }
    except Exception as exc:
        return {"command": command, "error_type": type(exc).__name__, "error": _bounded_error(exc)}


def _bounded_error(exc: Exception) -> str:
    return str(exc).replace(str(Path.home()), "~")[:1000]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build and execute the source-backed TTLAB Phase 3 QA evaluation.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("build-cases")
    run = subparsers.add_parser("run-answers")
    run.add_argument("--mode", choices=["keyword", "feature_hashing", "dense", "hybrid"], default="hybrid")
    run.add_argument("--provider", choices=["offline_extractive", "ollama"], default="offline_extractive")
    run.add_argument("--model", default=None)
    run.add_argument("--top-k", type=int, default=5)
    run.add_argument(
        "--retrieval-scope",
        choices=["technical"],
        default=EVALUATION_RETRIEVAL_SCOPE,
        help="Offline silver evaluation is restricted to the frozen technical corpus; public projection is not evaluated.",
    )
    run.add_argument("--output-stem", required=True)
    subparsers.add_parser("check-ollama")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "build-cases":
        cases = build_cases()
        print(f"case_count={len(cases)} out={QA_CASES.relative_to(PROJECT_ROOT)}")
    elif args.command == "run-answers":
        result = run_answers(
            mode=args.mode,
            provider=args.provider,
            model=args.model,
            top_k=args.top_k,
            output_stem=args.output_stem,
            retrieval_scope=args.retrieval_scope,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        result = check_ollama()
        print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
