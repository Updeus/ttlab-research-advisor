from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from app.evaluation.performance_benchmark import PROBES, summarize_samples


FULL_REQUIRED_STAGES = tuple(PROBES)
ABSOLUTE_PATH_PATTERNS = (
    re.compile(r"/(?:home|mnt|Users)/"),
    re.compile(r"^[A-Za-z]:[\\/]"),
)


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def validate_performance_artifact(
    payload: dict[str, Any],
    *,
    expected_profile: str,
    expected_repetitions: int,
    expected_stages: list[str],
) -> dict[str, Any]:
    errors: list[str] = []

    def require(condition: bool, message: str) -> None:
        if not condition:
            errors.append(message)

    require(payload.get("schema_version") == 2, "schema_version must be 2")
    require(payload.get("status") == "complete", "status must be complete")
    require(payload.get("profile") == expected_profile, f"profile must be {expected_profile}")
    require(payload.get("completed_at") is not None, "completed_at is required")

    methodology = payload.get("methodology")
    require(isinstance(methodology, dict), "methodology must be an object")
    if isinstance(methodology, dict):
        require(methodology.get("repetitions") == expected_repetitions, "methodology repetitions mismatch")
        expected_limit = None if expected_profile == "full" else methodology.get("document_limit")
        require(methodology.get("document_limit") == expected_limit, "full profile must not use a document limit")
        require(methodology.get("process_concurrency") == 1, "process_concurrency must be 1")
        require(methodology.get("runtime_root") == ".", "runtime_root must be path-independent '.'")

    progress = payload.get("progress")
    require(isinstance(progress, dict), "progress must be an object")
    if isinstance(progress, dict):
        require(progress.get("completed_stages") == expected_stages, "completed_stages mismatch")
        require(progress.get("completed_stage_count") == len(expected_stages), "completed_stage_count mismatch")
        require(progress.get("total_stage_count") == len(expected_stages), "total_stage_count mismatch")
        require(progress.get("next_stage") is None, "next_stage must be null for a complete artifact")

    provenance = payload.get("run_provenance")
    require(isinstance(provenance, dict), "run_provenance must be an object")
    if isinstance(provenance, dict):
        require(
            payload.get("run_provenance_sha256") == _canonical_sha256(provenance),
            "run_provenance_sha256 mismatch",
        )
        configuration = provenance.get("configuration")
        require(isinstance(configuration, dict), "run provenance configuration missing")
        if isinstance(configuration, dict):
            require(configuration.get("profile") == expected_profile, "provenance profile mismatch")
            require(configuration.get("repetitions") == expected_repetitions, "provenance repetitions mismatch")
            require(configuration.get("stages") == expected_stages, "provenance stages mismatch")
            require(configuration.get("runtime_root") == ".", "provenance runtime_root must be '.'")

    execution = payload.get("execution_source")
    require(isinstance(execution, dict), "execution_source must be an object")
    if isinstance(execution, dict):
        start = execution.get("start")
        end = execution.get("end")
        require(isinstance(start, dict) and start == end, "execution source start/end must match exactly")
        if isinstance(start, dict):
            require(start.get("dirty") is False, "benchmark source worktree must be clean")
            require(start.get("dirty_paths") == [], "benchmark source dirty_paths must be empty")
            require(bool(re.fullmatch(r"[0-9a-f]{40}", str(start.get("commit", "")))), "invalid source commit")
            require(
                bool(re.fullmatch(r"[0-9a-f]{64}", str(start.get("benchmark_source_sha256", "")))),
                "invalid benchmark source SHA-256",
            )

    results = payload.get("results")
    require(isinstance(results, dict), "results must be an object")
    measured_stages: list[str] = []
    total_samples = 0
    max_rss_samples = 0
    if isinstance(results, dict):
        measured_stages = [stage for stage in results if stage != "ocr"]
        require(measured_stages == expected_stages, "result stages mismatch")
        for stage in expected_stages:
            stage_result = results.get(stage)
            if not isinstance(stage_result, dict):
                errors.append(f"{stage}: missing result object")
                continue
            commands = stage_result.get("commands")
            require(isinstance(commands, dict), f"{stage}: commands missing")
            if isinstance(commands, dict):
                require(
                    isinstance(commands.get("cold"), list) and len(commands["cold"]) == expected_repetitions,
                    f"{stage}: cold command count mismatch",
                )
                require(isinstance(commands.get("warm"), str) and bool(commands["warm"]), f"{stage}: warm command missing")
            for temperature in ("cold", "warm"):
                series = stage_result.get(temperature)
                if not isinstance(series, dict):
                    errors.append(f"{stage}/{temperature}: series missing")
                    continue
                samples = series.get("samples")
                summary = series.get("summary")
                if not isinstance(samples, list):
                    errors.append(f"{stage}/{temperature}: samples missing")
                    continue
                require(
                    len(samples) == expected_repetitions,
                    f"{stage}/{temperature}: expected {expected_repetitions} samples, found {len(samples)}",
                )
                total_samples += len(samples)
                failed = [sample for sample in samples if sample.get("status") != "ok"]
                require(not failed, f"{stage}/{temperature}: {len(failed)} failed samples")
                max_rss_samples += sum(sample.get("max_rss_kib") is not None for sample in samples)
                require(summary == summarize_samples(samples), f"{stage}/{temperature}: summary does not match samples")
        ocr = results.get("ocr")
        require(isinstance(ocr, dict), "OCR applicability record missing")

    hardware = payload.get("hardware")
    require(isinstance(hardware, dict), "hardware must be an object")
    if isinstance(hardware, dict):
        require(hardware.get("process_concurrency") == 1, "hardware process_concurrency must be 1")
        require(bool(hardware.get("cpu_model")), "hardware CPU model missing")
        require(bool(hardware.get("python")), "hardware Python version missing")
        locks = hardware.get("dependency_locks")
        require(isinstance(locks, dict), "dependency lock provenance missing")
        if isinstance(locks, dict):
            for lock_name in ("python", "frontend"):
                lock = locks.get(lock_name)
                require(isinstance(lock, dict), f"{lock_name} dependency lock missing")
                if isinstance(lock, dict):
                    require(
                        bool(re.fullmatch(r"[0-9a-f]{64}", str(lock.get("sha256", "")))),
                        f"{lock_name} dependency lock SHA-256 invalid",
                    )
        environments = hardware.get("resolved_environments")
        require(isinstance(environments, dict), "resolved environment provenance missing")
        if isinstance(environments, dict):
            packages = environments.get("python_packages")
            require(isinstance(packages, dict) and len(packages) > 0, "resolved Python package list missing")
            if isinstance(packages, dict):
                require(
                    environments.get("python_package_count") == len(packages),
                    "resolved Python package count mismatch",
                )
                require(
                    environments.get("python_packages_sha256") == _canonical_sha256(packages),
                    "resolved Python package SHA-256 mismatch",
                )
            frontend_packages = environments.get("frontend_top_level_packages")
            require(
                isinstance(frontend_packages, dict) and len(frontend_packages) > 0,
                "resolved frontend package list missing",
            )
            if isinstance(frontend_packages, dict):
                require(
                    environments.get("frontend_top_level_packages_sha256") == _canonical_sha256(frontend_packages),
                    "resolved frontend package SHA-256 mismatch",
                )
        tools = hardware.get("tool_versions")
        require(isinstance(tools, dict), "tool version provenance missing")
        if isinstance(tools, dict):
            for tool_name in ("git", "qpdf", "pdftoppm", "pdftotext", "tectonic", "playwright", "chromium"):
                require(bool(tools.get(tool_name)), f"{tool_name} version missing")
        assets = hardware.get("benchmark_assets")
        require(isinstance(assets, dict), "benchmark asset provenance missing")
        if isinstance(assets, dict):
            page_script = assets.get("frontend_page_script")
            require(isinstance(page_script, dict), "frontend benchmark script provenance missing")
            if isinstance(page_script, dict):
                require(
                    bool(re.fullmatch(r"[0-9a-f]{64}", str(page_script.get("sha256", "")))),
                    "frontend benchmark script SHA-256 invalid",
                )

    corpus = payload.get("corpus")
    require(isinstance(corpus, dict), "corpus must be an object")
    if isinstance(corpus, dict):
        require(int(corpus.get("eligible_papers", 0)) > 0, "eligible_papers must be positive")
        require(int(corpus.get("eligible_chunks", 0)) > 0, "eligible_chunks must be positive")
        require(bool(re.fullmatch(r"[0-9a-f]{64}", str(corpus.get("database_sha256", "")))), "invalid database SHA-256")

    leaked_paths = [
        value
        for value in _strings(payload)
        if any(pattern.search(value) for pattern in ABSOLUTE_PATH_PATTERNS)
    ]
    require(not leaked_paths, f"absolute workspace/home paths leaked: {leaked_paths[:3]}")

    if errors:
        raise ValueError("Invalid performance artifact:\n- " + "\n- ".join(errors))
    return {
        "status": "valid",
        "profile": expected_profile,
        "stages": len(measured_stages),
        "samples": total_samples,
        "rss_samples": max_rss_samples,
        "failures": 0,
        "source_commit": payload["execution_source"]["start"]["commit"],
        "provenance_sha256": payload["run_provenance_sha256"],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fail-loud validation for a completed performance benchmark artifact.")
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--expected-profile", choices=["quick", "full"], default="full")
    parser.add_argument("--expected-repetitions", type=int, default=3)
    parser.add_argument("--stage", action="append", choices=sorted(PROBES), dest="stages")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    payload = json.loads(args.artifact.read_text(encoding="utf-8"))
    stages = args.stages or list(FULL_REQUIRED_STAGES)
    summary = validate_performance_artifact(
        payload,
        expected_profile=args.expected_profile,
        expected_repetitions=args.expected_repetitions,
        expected_stages=stages,
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
