from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

from app.evaluation import performance_benchmark as benchmark_module
from app.evaluation.performance_benchmark import (
    _sanitize_command,
    available_loopback_port,
    atomic_write_json,
    benchmark,
    execution_source_manifest,
    percentile,
    summarize_samples,
)


def test_available_loopback_port_returns_a_bindable_dynamic_port() -> None:
    try:
        port = available_loopback_port()
    except PermissionError:
        pytest.skip("current sandbox forbids AF_INET socket creation; production startup probe remains unchanged")
    assert 0 < port < 65536
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as handle:
        handle.bind(("127.0.0.1", port))


def test_percentile_uses_linear_interpolation() -> None:
    assert percentile([1.0, 2.0, 3.0], 0.95) == 2.9
    assert percentile([4.0], 0.95) == 4.0
    assert percentile([], 0.95) is None


def test_summary_keeps_failures_in_failure_rate_and_omits_failed_latency() -> None:
    result = summarize_samples(
        [
            {"status": "ok", "elapsed_seconds": 1.0, "seconds_per_unit": 0.5, "max_rss_kib": 100},
            {"status": "failed", "elapsed_seconds": 99.0},
            {"status": "ok", "elapsed_seconds": 3.0, "seconds_per_unit": 1.5, "max_rss_kib": 120},
        ]
    )
    assert result["repetitions_attempted"] == 3
    assert result["repetitions_succeeded"] == 2
    assert result["failure_rate"] == pytest.approx(1 / 3, abs=1e-6)
    assert result["elapsed_seconds"]["median"] == 2.0
    assert result["max_rss_kib"] == 120


def test_execution_source_manifest_records_commit_status_and_source_hash() -> None:
    result = execution_source_manifest()
    assert len(result["commit"]) == 40
    assert isinstance(result["dirty"], bool)
    assert isinstance(result["dirty_paths"], list)
    assert len(result["dirty_state_sha256"]) == 64
    assert result["benchmark_source_path"] == "backend/app/evaluation/performance_benchmark.py"
    assert len(result["benchmark_source_sha256"]) == 64


def test_atomic_write_json_replaces_complete_document(tmp_path: Path) -> None:
    output = tmp_path / "checkpoint.json"
    atomic_write_json(output, {"status": "in_progress", "completed": 1})
    atomic_write_json(output, {"status": "complete", "completed": 2})

    assert json.loads(output.read_text()) == {"status": "complete", "completed": 2}
    assert list(tmp_path.glob(".checkpoint.json.*.tmp")) == []


def test_artifact_command_redacts_external_python_and_runtime_paths(tmp_path: Path) -> None:
    database = tmp_path / "runtime/data/papers.db"
    command = f"{benchmark_module.sys.executable} -m probe --database {database}"
    result = _sanitize_command(command, database=database, runtime_root=tmp_path / "runtime")
    assert str(Path(benchmark_module.sys.executable).resolve()) not in result
    assert str(tmp_path) not in result
    assert result.startswith("<python> -m probe")


def _fixed_source(source_hash: str = "a" * 64) -> dict[str, object]:
    return {
        "commit": "b" * 40,
        "dirty": False,
        "dirty_paths": [],
        "benchmark_source_sha256": source_hash,
        "benchmark_source_path": "backend/app/evaluation/performance_benchmark.py",
    }


def _fixed_corpus(database_hash: str = "c" * 64) -> dict[str, object]:
    return {
        "database_sha256": database_hash,
        "database_bytes": 100,
        "paper_rows": 2,
        "eligible_papers": 2,
        "eligible_papers_with_pdf": 1,
        "raw_chunks": 3,
        "eligible_chunks": 3,
        "ocr_completed_papers": 0,
        "ocr_pages": 0,
    }


def _fixed_hardware() -> dict[str, object]:
    return {"device": "CPU", "python": "3.12", "process_concurrency": 1}


def test_benchmark_checkpoints_each_stage_and_resumes_prefix(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    checkpoint = tmp_path / "performance.json"
    calls: list[str] = []

    monkeypatch.setattr(benchmark_module, "execution_source_manifest", lambda **_kwargs: _fixed_source())
    monkeypatch.setattr(benchmark_module, "corpus_manifest", lambda _database: _fixed_corpus())
    monkeypatch.setattr(benchmark_module, "hardware_manifest", _fixed_hardware)

    def interrupted_probe(stage: str, *_args: object, **_kwargs: object):
        calls.append(stage)
        if stage == "chunking":
            raise RuntimeError("simulated controller interruption")
        return (
            {"samples": [{"status": "ok", "elapsed_seconds": 1.0, "seconds_per_unit": 1.0}]},
            123,
            f"python -m benchmark --probe {stage}",
        )

    monkeypatch.setattr(benchmark_module, "invoke_probe", interrupted_probe)
    with pytest.raises(RuntimeError, match="simulated controller interruption"):
        benchmark(
            tmp_path / "papers.db",
            profile="full",
            repetitions=1,
            document_limit=None,
            stages=["import", "chunking"],
            runtime_root=tmp_path,
            checkpoint_path=checkpoint,
        )

    partial = json.loads(checkpoint.read_text())
    assert partial["status"] == "in_progress"
    assert partial["progress"]["completed_stages"] == ["import"]
    assert list(partial["results"]) == ["import"]

    def resumed_probe(stage: str, *_args: object, **_kwargs: object):
        calls.append(stage)
        return (
            {"samples": [{"status": "ok", "elapsed_seconds": 2.0, "seconds_per_unit": 2.0}]},
            456,
            f"python -m benchmark --probe {stage}",
        )

    monkeypatch.setattr(benchmark_module, "invoke_probe", resumed_probe)
    final = benchmark(
        tmp_path / "papers.db",
        profile="full",
        repetitions=1,
        document_limit=None,
        stages=["import", "chunking"],
        runtime_root=tmp_path,
        checkpoint_path=checkpoint,
        resume=True,
    )

    assert calls.count("import") == 2
    assert calls.count("chunking") == 3
    assert final["status"] == "complete"
    assert final["progress"]["completed_stages"] == ["import", "chunking"]
    assert final["execution_source"]["end"] == _fixed_source()
    assert json.loads(checkpoint.read_text())["status"] == "complete"


def test_resume_refuses_changed_source_provenance(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    checkpoint = tmp_path / "performance.json"
    source = _fixed_source()
    monkeypatch.setattr(benchmark_module, "execution_source_manifest", lambda **_kwargs: source)
    monkeypatch.setattr(benchmark_module, "corpus_manifest", lambda _database: _fixed_corpus())
    monkeypatch.setattr(benchmark_module, "hardware_manifest", _fixed_hardware)

    def interrupted_probe(*_args: object, **_kwargs: object):
        raise RuntimeError("stop after initial checkpoint")

    monkeypatch.setattr(benchmark_module, "invoke_probe", interrupted_probe)
    with pytest.raises(RuntimeError, match="stop after initial checkpoint"):
        benchmark(
            tmp_path / "papers.db",
            profile="full",
            repetitions=1,
            document_limit=None,
            stages=["import"],
            runtime_root=tmp_path,
            checkpoint_path=checkpoint,
        )

    source = _fixed_source("d" * 64)
    with pytest.raises(ValueError, match="provenance changed"):
        benchmark(
            tmp_path / "papers.db",
            profile="full",
            repetitions=1,
            document_limit=None,
            stages=["import"],
            runtime_root=tmp_path,
            checkpoint_path=checkpoint,
            resume=True,
        )
