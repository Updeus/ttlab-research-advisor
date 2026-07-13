from __future__ import annotations

import argparse
import hashlib
import json
import re
from importlib import metadata
from pathlib import Path


PIN = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s;]+)$")
ALLOWED_INDEX_DIRECTIVE = re.compile(r"^--extra-index-url\s+https://[^\s]+$")


def normalize_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def locked_packages(path: Path) -> dict[str, str]:
    packages: dict[str, str] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ALLOWED_INDEX_DIRECTIVE.fullmatch(stripped):
            continue
        match = PIN.fullmatch(stripped)
        if not match:
            raise ValueError(
                f"Unsupported or non-exact requirement at {path.name}:{line_number}: {stripped!r}"
            )
        name, version = match.groups()
        normalized = normalize_name(name)
        if normalized in packages:
            raise ValueError(f"Duplicate package in lock: {name}")
        packages[normalized] = version
    if not packages:
        raise ValueError(f"No exact package pins found in {path}")
    return dict(sorted(packages.items()))


def installed_packages() -> dict[str, str]:
    return dict(sorted((normalize_name(distribution.metadata["Name"]), distribution.version) for distribution in metadata.distributions()))


def validate_environment(lock: Path) -> dict[str, object]:
    expected = locked_packages(lock)
    installed = installed_packages()
    missing = sorted(name for name in expected if name not in installed)
    mismatched = {
        name: {"expected": expected[name], "installed": installed[name]}
        for name in expected
        if name in installed and expected[name] != installed[name]
    }
    if missing or mismatched:
        raise ValueError(
            "Resolved Python environment does not match the tracked lock: "
            f"missing={missing}; mismatched={mismatched}"
        )
    extras = sorted(name for name in installed if name not in expected)
    try:
        lock_label = lock.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        lock_label = lock.name
    return {
        "status": "valid",
        "lock_path": lock_label,
        "lock_sha256": sha256_path(lock),
        "locked_package_count": len(expected),
        "installed_package_count": len(installed),
        "extra_package_count": len(extras),
        "extra_packages": extras,
        "claim_boundary": (
            "Every tracked exact pin is installed at the locked version. Extra packages are reported because the "
            "shared development environment may contain document-inspection tools outside the application closure."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate installed Python packages against the reproduction lock.")
    parser.add_argument("--lock", type=Path, default=Path("backend/requirements-lock.txt"))
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    result = validate_environment(args.lock)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
