from __future__ import annotations

from pathlib import Path

from app import io_utils
from app.indexing import embedder
from app.ingestion import sync


def test_atomic_renames_fsync_the_parent_directory(monkeypatch, tmp_path: Path) -> None:
    observed: list[tuple[str, Path]] = []
    monkeypatch.setattr(
        io_utils,
        "fsync_directory",
        lambda path: observed.append(("text", Path(path))),
    )
    monkeypatch.setattr(
        embedder,
        "fsync_directory",
        lambda path: observed.append(("index", Path(path))),
    )
    monkeypatch.setattr(
        sync,
        "fsync_directory",
        lambda path: observed.append(("seed", Path(path))),
    )

    io_utils.atomic_write_text(tmp_path / "artifact.txt", "artifact\n")
    embedder.atomic_write_bytes(tmp_path / "index.json", b"{}\n")
    sync.atomic_write_seed([{"paper_id": "paper-1"}], tmp_path / "papers.json")

    assert observed == [
        ("text", tmp_path),
        ("index", tmp_path),
        ("seed", tmp_path),
    ]
