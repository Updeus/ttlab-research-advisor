from __future__ import annotations

from pathlib import Path

import pytest

from app.reproducibility import environment


ROOT = Path(__file__).resolve().parents[2]


def test_tracked_reproduction_lock_covers_app_dense_ocr_and_audit_paths() -> None:
    packages = environment.locked_packages(ROOT / "backend/requirements-lock.txt")
    assert len(packages) >= 80
    assert packages["fastapi"] == "0.139.0"
    assert packages["sentence-transformers"] == "5.6.0"
    assert packages["torch"] == "2.13.0+cpu"
    assert packages["pytesseract"] == "0.3.13"
    assert packages["pip-audit"] == "2.10.1"


@pytest.mark.parametrize(
    "requirement",
    [
        "package>=1.0",
        "package~=1.0",
        "package @ https://example.invalid/package.whl",
        "-r other-requirements.txt",
        "git+https://example.invalid/repository.git",
        "--find-links ./wheels",
    ],
)
def test_lock_parser_rejects_every_unapproved_non_exact_requirement(
    tmp_path: Path,
    requirement: str,
) -> None:
    lock = tmp_path / "requirements-lock.txt"
    lock.write_text(f"safe==1.0\n{requirement}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported or non-exact"):
        environment.locked_packages(lock)


def test_lock_parser_allows_only_the_tracked_https_extra_index_directive(tmp_path: Path) -> None:
    lock = tmp_path / "requirements-lock.txt"
    lock.write_text(
        "# resolved lock\n--extra-index-url https://download.pytorch.org/whl/cpu\nsafe==1.0\n",
        encoding="utf-8",
    )
    assert environment.locked_packages(lock) == {"safe": "1.0"}


def test_validate_environment_requires_every_exact_pin(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    lock = tmp_path / "requirements-lock.txt"
    lock.write_text("Alpha_Pkg==1.2.3\nbeta.pkg==4.5.6\n", encoding="utf-8")
    monkeypatch.setattr(
        environment,
        "installed_packages",
        lambda: {"alpha-pkg": "1.2.3", "beta-pkg": "4.5.6", "extra": "9.0"},
    )

    result = environment.validate_environment(lock)
    assert result["status"] == "valid"
    assert result["locked_package_count"] == 2
    assert result["extra_packages"] == ["extra"]


def test_validate_environment_rejects_missing_or_mismatched_pin(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    lock = tmp_path / "requirements-lock.txt"
    lock.write_text("alpha==1.0\nbeta==2.0\n", encoding="utf-8")
    monkeypatch.setattr(environment, "installed_packages", lambda: {"alpha": "0.9"})

    with pytest.raises(ValueError, match="missing=.*beta.*mismatched=.*alpha"):
        environment.validate_environment(lock)
