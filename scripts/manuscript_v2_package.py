#!/usr/bin/env python3
"""Load validated remediation-v2 evidence for downstream manuscript assets.

The canonical v2 macro file is itself covered by the v2 manifest and validation
attestation. This module adds manifest/attestation identity only downstream, so
the canonical package never needs to contain the hash of an attestation that is
created after it.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from types import ModuleType
from typing import Any


V2_RELATIVE_DIR = Path("artifacts/peer_review_remediation/v2")
V2_RECEIPT_NAME = "freeze_receipt_v2.json"
V2_MANIFEST_NAME = "manifest_v2.json"
V2_ATTESTATION_NAME = "validation_attestation_v2.json"
V2_MACRO_NAME = "manuscript_macros_v2.tex"
DOWNSTREAM_MACRO_NAMES = (
    "VTwoPackageStatus",
    "VTwoManifestShaPrefix",
    "VTwoValidationAttestationShaPrefix",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_runner(root: Path) -> ModuleType:
    path = root / "data" / "evaluation" / "run_peer_review_remediation_v2.py"
    spec = importlib.util.spec_from_file_location("manuscript_v2_runner_contract", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load v2 macro contract from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _macro(name: str, value: str) -> str:
    return f"\\newcommand{{\\{name}}}{{{value}}}"


def _fallback_macro_text(root: Path, status: str) -> str:
    runner = _load_runner(root)
    names = tuple(runner.MANUSCRIPT_MACRO_NAMES)
    values = {name: "not run" for name in names}
    values.update(
        {
            "VTwoEvidenceTier": "not available (v2 not run)",
            "VTwoRunStatus": status.replace("_", r"\_"),
            "VTwoEvaluationId": "peer-review-remediation-v2",
            "VTwoEvaluationScope": "not evaluated",
            "VTwoPublicProjectionExercised": "no",
            "VTwoExternalProviderInvoked": "no",
        }
    )
    downstream = {
        "VTwoPackageStatus": "not completed or validated",
        "VTwoManifestShaPrefix": "not available",
        "VTwoValidationAttestationShaPrefix": "not available",
    }
    lines = [
        "% Explicit layout-only fallback; remediation-v2 has not produced a validated package.",
        "% These values are placeholders, not experimental evidence and not submission-ready.",
        *(_macro(name, values[name]) for name in names),
        *(_macro(name, downstream[name]) for name in DOWNSTREAM_MACRO_NAMES),
    ]
    return "\n".join(lines) + "\n"


def _run_versionable_validator(root: Path, package: Path) -> dict[str, Any]:
    validator = root / "data" / "evaluation" / "validate_peer_review_remediation_v2.py"
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(root / "backend")
    environment["TTLAB_V2_ARTIFACT_DIR"] = str(package)
    completed = subprocess.run(
        [sys.executable, str(validator), "--versionable-only"],
        cwd=root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "no validator output"
        raise RuntimeError(f"remediation-v2 versionable-package validation failed: {detail}")
    try:
        report = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("remediation-v2 validator returned invalid JSON") from exc
    if report.get("status") != "pass":
        raise RuntimeError("remediation-v2 validator did not report a pass")
    return report


def load_manuscript_v2_package(
    root: Path,
    *,
    allow_not_run: bool = False,
    validate_completed: bool = True,
) -> dict[str, Any]:
    """Return macro text and provenance for a completed package or explicit layout fallback.

    The fallback is allowed only when the package is absent/empty or contains a
    freeze receipt and no execution outputs. A partial or invalid execution is
    never hidden behind the fallback.
    """

    root = root.resolve()
    package = root / V2_RELATIVE_DIR
    existing = sorted(path.name for path in package.iterdir() if path.is_file()) if package.is_dir() else []
    completed_names = {
        V2_RECEIPT_NAME,
        V2_MANIFEST_NAME,
        V2_ATTESTATION_NAME,
        V2_MACRO_NAME,
    }
    has_completed_shape = completed_names.issubset(existing)
    fallback_shape = set(existing).issubset({V2_RECEIPT_NAME})
    if not has_completed_shape:
        if not allow_not_run:
            missing = sorted(completed_names - set(existing))
            raise FileNotFoundError(
                "completed remediation-v2 package is required; missing " + ", ".join(missing)
            )
        if not fallback_shape:
            raise RuntimeError(
                "refusing layout fallback over a partial remediation-v2 execution: "
                + ", ".join(existing)
            )
        status = "frozen_not_executed" if existing else "not_run"
        sources = {
            f"v2_{path.stem}": {
                "path": path.relative_to(root).as_posix(),
                "sha256": sha256(path),
                "bytes": path.stat().st_size,
            }
            for path in sorted(package.glob("*"))
            if path.is_file()
        }
        return {
            "status": status,
            "completed": False,
            "layout_only": True,
            "macro_text": _fallback_macro_text(root, status),
            "sources": sources,
            "validation_report": None,
            "manifest_sha256": None,
            "validation_attestation_sha256": None,
        }

    report = _run_versionable_validator(root, package) if validate_completed else None
    manifest_path = package / V2_MANIFEST_NAME
    attestation_path = package / V2_ATTESTATION_NAME
    macro_path = package / V2_MACRO_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    attestation = json.loads(attestation_path.read_text(encoding="utf-8"))
    if (
        manifest.get("status") != "completed"
        or manifest.get("technical_scope_only") is not True
        or manifest.get("public_projection_exercised") is not False
        or manifest.get("human_validation_claimed") is not False
        or manifest.get("entailment_claimed") is not False
        or attestation.get("status") != "completed_package_validated"
    ):
        raise RuntimeError("remediation-v2 completed-package boundary or status drift")
    manifest_sha = sha256(manifest_path)
    attestation_sha = sha256(attestation_path)
    downstream = "\n".join(
        (
            _macro("VTwoPackageStatus", "completed and validated"),
            _macro("VTwoManifestShaPrefix", manifest_sha[:12]),
            _macro("VTwoValidationAttestationShaPrefix", attestation_sha[:12]),
        )
    )
    macro_text = macro_path.read_text(encoding="utf-8").rstrip() + "\n" + downstream + "\n"
    sources = {
        f"v2_{path.stem}": {
            "path": path.relative_to(root).as_posix(),
            "sha256": sha256(path),
            "bytes": path.stat().st_size,
        }
        for path in sorted(package.iterdir())
        if path.is_file()
    }
    return {
        "status": "completed_package_validated",
        "completed": True,
        "layout_only": False,
        "macro_text": macro_text,
        "sources": sources,
        "validation_report": report,
        "manifest_sha256": manifest_sha,
        "validation_attestation_sha256": attestation_sha,
    }
