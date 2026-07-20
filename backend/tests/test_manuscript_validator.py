from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "validate_manuscripts",
    ROOT / "scripts" / "validate_manuscripts.py",
)
assert SPEC is not None and SPEC.loader is not None
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


def test_paper_page_and_reference_boundaries() -> None:
    assert VALIDATOR.manuscript_constraint_errors(
        "paper", 6, cited_references=18
    ) == []
    assert VALIDATOR.manuscript_constraint_errors(
        "paper", 6, cited_references=22
    ) == []

    assert "page count 7" in VALIDATOR.manuscript_constraint_errors(
        "paper", 7, cited_references=20
    )[0]
    assert "reference count 17" in VALIDATOR.manuscript_constraint_errors(
        "paper", 6, cited_references=17
    )[0]
    assert "reference count 23" in VALIDATOR.manuscript_constraint_errors(
        "paper", 6, cited_references=23
    )[0]


def test_thesis_minimum_page_boundary() -> None:
    assert VALIDATOR.manuscript_constraint_errors("thesis", 75) == []
    assert "below the hard 75-page minimum" in VALIDATOR.manuscript_constraint_errors(
        "thesis", 74
    )[0]


def test_citation_key_parser_deduplicates_at_policy_boundary() -> None:
    keys = VALIDATOR.citation_keys(r"\\cite{alpha,beta} and \\cite{alpha}")
    assert keys == ["alpha", "beta", "alpha"]
