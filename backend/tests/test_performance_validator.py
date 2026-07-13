from __future__ import annotations

import copy

import pytest

from app.evaluation.performance_benchmark import _canonical_sha256, summarize_samples
from app.evaluation.performance_validator import validate_performance_artifact


def _artifact() -> dict:
    stages = ["import"]
    samples = [
        {
            "repetition": repetition,
            "status": "ok",
            "elapsed_seconds": float(repetition),
            "seconds_per_unit": float(repetition),
            "max_rss_kib": 100 + repetition,
        }
        for repetition in range(1, 4)
    ]
    source = {
        "commit": "a" * 40,
        "dirty": False,
        "dirty_paths": [],
        "dirty_state_sha256": "b" * 64,
        "benchmark_source_sha256": "c" * 64,
        "benchmark_source_path": "backend/app/evaluation/performance_benchmark.py",
    }
    corpus = {
        "database_sha256": "d" * 64,
        "eligible_papers": 2,
        "eligible_chunks": 3,
        "ocr_completed_papers": 0,
        "ocr_pages": 0,
    }
    hardware = {
        "cpu_model": "Test CPU",
        "python": "3.12.0",
        "process_concurrency": 1,
        "dependency_locks": {
            "python": {"sha256": "1" * 64},
            "frontend": {"sha256": "2" * 64},
        },
        "resolved_environments": {
            "python_package_count": 1,
            "python_packages": {"fastapi": "1.0"},
            "python_packages_sha256": _canonical_sha256({"fastapi": "1.0"}),
            "frontend_top_level_packages": {"react": "1.0"},
            "frontend_top_level_packages_sha256": _canonical_sha256({"react": "1.0"}),
        },
        "tool_versions": {
            "git": "git 1",
            "qpdf": "qpdf 1",
            "pdftoppm": "pdftoppm 1",
            "pdftotext": "pdftotext 1",
            "tectonic": "tectonic 1",
            "playwright": "playwright 1",
            "chromium": "chromium 1",
        },
        "benchmark_assets": {"frontend_page_script": {"sha256": "3" * 64}},
    }
    configuration = {
        "profile": "full",
        "repetitions": 3,
        "document_limit": None,
        "stages": stages,
        "process_concurrency": 1,
        "runtime_root": ".",
    }
    provenance = {
        "source": source,
        "corpus": corpus,
        "configuration": configuration,
        "hardware": hardware,
    }
    return {
        "schema_version": 2,
        "status": "complete",
        "benchmark_id": "ttlab-performance-full-v1",
        "generated_at": "2026-07-12T00:00:00+00:00",
        "updated_at": "2026-07-12T01:00:00+00:00",
        "completed_at": "2026-07-12T01:00:00+00:00",
        "profile": "full",
        "run_provenance": provenance,
        "run_provenance_sha256": _canonical_sha256(provenance),
        "progress": {
            "completed_stages": stages,
            "completed_stage_count": 1,
            "total_stage_count": 1,
            "next_stage": None,
        },
        "methodology": {
            "repetitions": 3,
            "document_limit": None,
            "process_concurrency": 1,
            "runtime_root": ".",
        },
        "hardware": hardware,
        "corpus": corpus,
        "execution_source": {"start": source, "end": copy.deepcopy(source)},
        "results": {
            "import": {
                "cold": {"summary": summarize_samples(samples), "samples": samples},
                "warm": {"summary": summarize_samples(samples), "samples": samples},
                "commands": {"cold": ["python probe"] * 3, "warm": "python probe"},
            },
            "ocr": {"status": "not_applicable", "ocr_completed_papers": 0, "ocr_pages": 0},
        },
        "limitations": [],
    }


def test_validator_accepts_complete_zero_failure_artifact() -> None:
    result = validate_performance_artifact(
        _artifact(),
        expected_profile="full",
        expected_repetitions=3,
        expected_stages=["import"],
    )
    assert result["status"] == "valid"
    assert result["samples"] == 6
    assert result["failures"] == 0


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: value.update(status="in_progress"), "status must be complete"),
        (
            lambda value: value["results"]["import"]["warm"]["samples"][0].update(status="failed"),
            "failed samples",
        ),
        (lambda value: value["execution_source"]["end"].update(commit="f" * 40), "start/end"),
        (lambda value: value["methodology"].update(runtime_root="/home/user/project"), "runtime_root"),
    ],
)
def test_validator_rejects_incomplete_failed_or_unfrozen_artifacts(mutate, message: str) -> None:
    payload = copy.deepcopy(_artifact())
    mutate(payload)
    with pytest.raises(ValueError, match=message):
        validate_performance_artifact(
            payload,
            expected_profile="full",
            expected_repetitions=3,
            expected_stages=["import"],
        )
