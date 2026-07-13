from __future__ import annotations

from pathlib import Path

import pytest

from app.reproducibility import environment


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
