from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "finalize_peer_review_remediation_v2.py"


def load_finalizer():
    spec = importlib.util.spec_from_file_location(
        "finalize_peer_review_remediation_v2_test", SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def descriptor(hashes: dict[str, str]) -> str:
    payload = json.dumps(hashes, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def locator(chunk_id: str, source_hash: str) -> dict[str, str]:
    return {"chunk_id": chunk_id, "effective_source_sha256": source_hash}


def provenance(source_hashes: dict[str, str]) -> dict[str, object]:
    return {
        "corpus_identity": {
            "scope": "technical",
            "snapshot_id": "corpus-test",
            "snapshot_hash": "c" * 64,
            "eligible_chunk_count": 2,
            "eligible_paper_count": 1,
        },
        "source_identity": {
            "chunk_ids": sorted(source_hashes),
            "chunk_descriptor_sha256": descriptor(source_hashes),
        },
    }


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )


def exact_runtime_files(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    first_hash = "a" * 64
    second_hash = "b" * 64
    complete = {"chunk-a": first_hash, "chunk-b": second_hash}
    cited = {"chunk-a": first_hash}
    qa_public = tmp_path / "qa_raw_outputs_v2.jsonl"
    qa_restricted = tmp_path / "qa_full_raw_v2.jsonl"
    finder_public = tmp_path / "finder_raw_outputs_v2.jsonl"
    finder_restricted = tmp_path / "finder_full_raw_v2.jsonl"
    qa_locators = [locator(chunk_id, source_hash) for chunk_id, source_hash in complete.items()]
    finder_locators = [locator(chunk_id, source_hash) for chunk_id, source_hash in complete.items()]
    write_jsonl(
        qa_public,
        [
            {
                "case_id": "qa-v2-a01",
                "retrieved_chunks": qa_locators,
                "runtime_provenance": provenance(complete),
            }
        ],
    )
    write_jsonl(
        qa_restricted,
        [
            {
                "case_id": "qa-v2-a01",
                "response": {
                    # Rights-sensitive full rows intentionally omit the public
                    # projection's effective source hashes.
                    "retrieved_chunks": [{"chunk_id": item["chunk_id"]} for item in qa_locators],
                    "runtime_provenance": provenance(complete),
                },
            }
        ],
    )
    write_jsonl(
        finder_public,
        [
            {
                "profile_id": "finder-v2-d01",
                "paired_retrieval": {"result_locators": finder_locators},
                "full_finder": {"runtime_provenance": provenance(cited)},
            }
        ],
    )
    write_jsonl(
        finder_restricted,
        [
            {
                "profile_id": "finder-v2-d01",
                "full_finder": {"runtime_provenance": provenance(cited)},
            }
        ],
    )
    return qa_public, qa_restricted, finder_public, finder_restricted


def decode_jsonl(payload: bytes) -> list[dict[str, object]]:
    return [json.loads(line) for line in payload.decode("utf-8").splitlines() if line]


def test_known_mismatch_normalization_is_representation_only_and_paired_complete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    finalizer = load_finalizer()
    monkeypatch.setattr(finalizer, "EXPECTED_QA_ROWS", 1)
    monkeypatch.setattr(finalizer, "EXPECTED_FINDER_ROWS", 1)
    paths = exact_runtime_files(tmp_path)

    payloads, reports = finalizer.prepare_normalized_payloads(*paths)

    assert len(payloads) == 4
    assert all(report["original_sha256"] != report["normalized_sha256"] for report in reports)
    for path, payload in payloads.items():
        row = decode_jsonl(payload)[0]
        if path.name.startswith("qa_raw"):
            provenance_value = row["runtime_provenance"]
        elif path.name.startswith("qa_full"):
            provenance_value = row["response"]["runtime_provenance"]
        else:
            provenance_value = row["full_finder"]["runtime_provenance"]
        assert "scope" not in provenance_value["corpus_identity"]
        if path.name.startswith("finder_"):
            assert provenance_value["source_identity"]["chunk_ids"] == ["chunk-a", "chunk-b"]
            assert provenance_value["source_identity"]["chunk_descriptor_sha256"] == descriptor(
                {"chunk-a": "a" * 64, "chunk-b": "b" * 64}
            )

    # Preparing bytes does not touch the original files; archiving precedes all writes.
    assert json.loads(paths[0].read_text(encoding="utf-8"))["runtime_provenance"][
        "corpus_identity"
    ]["scope"] == "technical"


def test_normalization_rejects_any_shape_other_than_the_known_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    finalizer = load_finalizer()
    monkeypatch.setattr(finalizer, "EXPECTED_QA_ROWS", 1)
    monkeypatch.setattr(finalizer, "EXPECTED_FINDER_ROWS", 1)
    paths = exact_runtime_files(tmp_path)
    row = json.loads(paths[0].read_text(encoding="utf-8"))
    row["runtime_provenance"]["corpus_identity"]["unexpected"] = True
    write_jsonl(paths[0], [row])

    with pytest.raises(RuntimeError, match="exact known redundant shape"):
        finalizer.prepare_normalized_payloads(*paths)


def test_recovery_requires_an_incomplete_finder_identity_not_a_valid_completed_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    finalizer = load_finalizer()
    monkeypatch.setattr(finalizer, "EXPECTED_QA_ROWS", 1)
    monkeypatch.setattr(finalizer, "EXPECTED_FINDER_ROWS", 1)
    paths = exact_runtime_files(tmp_path)
    for path in paths[2:]:
        row = json.loads(path.read_text(encoding="utf-8"))
        row["full_finder"]["runtime_provenance"] = provenance(
            {"chunk-a": "a" * 64, "chunk-b": "b" * 64}
        )
        write_jsonl(path, [row])

    with pytest.raises(RuntimeError, match="exact known incomplete-source mismatch"):
        finalizer.prepare_normalized_payloads(*paths)


def test_recovery_log_signature_is_exact_and_requires_all_completed_stages() -> None:
    finalizer = load_finalizer()
    valid = "\n".join(
        [
            *finalizer.KNOWN_FAILURE_COMPLETION_MARKERS,
            "Traceback (most recent call last):",
            "  execute_evaluation",
            "  build_manifest(receipt, temp_db, keyword_index, corpus_identity)",
            (
                "  runtime_provenance = "
                "validate_runtime_provenance_outputs(corpus_identity, keyword_index)"
            ),
            '  raise RuntimeError(f"{record_id}: runtime corpus identity drift")',
            finalizer.KNOWN_FAILURE_FINAL_LINE,
        ]
    )
    finalizer.validate_known_failure_log(valid)

    with pytest.raises(RuntimeError, match="exact known provenance mismatch"):
        finalizer.validate_known_failure_log(valid.replace("qa-v2-a01", "qa-v2-a02"))
    with pytest.raises(RuntimeError, match="completed-stage marker"):
        finalizer.validate_known_failure_log(
            valid.replace(finalizer.KNOWN_FAILURE_COMPLETION_MARKERS[2], "")
        )


def test_exact_inventory_and_reproduction_integration_are_fail_closed(tmp_path: Path) -> None:
    finalizer = load_finalizer()
    output = tmp_path / "output"
    output.mkdir()
    for name in ("one", "two"):
        (output / name).write_text(name, encoding="utf-8")
    finalizer.exact_directory_inventory(output, {"one", "two"}, "test")
    (output / "extra").write_text("extra", encoding="utf-8")
    with pytest.raises(RuntimeError, match="inventory drift"):
        finalizer.exact_directory_inventory(output, {"one", "two"}, "test")

    reproduce = (ROOT / "scripts" / "reproduce_all.sh").read_text(encoding="utf-8")
    evaluate = '"$RUN_ROOT/data/evaluation/run_peer_review_remediation_v2.py" evaluate'
    recovery = '"$RUN_ROOT/scripts/finalize_peer_review_remediation_v2.py"'
    assert reproduce.count(evaluate) == 1
    assert reproduce.count(recovery) == 1
    assert reproduce.index(evaluate) < reproduce.index(recovery)
    assert "The one prospective evaluation must never be repeated" in reproduce
    assert "--root \"$RUN_ROOT\" --work-dir \"$WORK\"" in reproduce
