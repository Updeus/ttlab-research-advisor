from __future__ import annotations

import hashlib
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

from app.indexing.keyword_search import rebuild_keyword_index, search_keyword
from app.models import Chunk, Paper


def sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_repeated_keyword_search_does_not_mutate_sqlite_file(tmp_path: Path) -> None:
    database = tmp_path / "keyword.db"
    engine = create_engine(f"sqlite:///{database}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            Paper(
                paper_id="read-only-paper",
                title="Read-only retrieval",
                authors=["Test Author"],
                corpus_eligibility_status="eligible",
            )
        )
        session.add(
            Chunk(
                chunk_id="read-only-chunk",
                paper_id="read-only-paper",
                chunk_index=0,
                text="Keyword retrieval must not mutate the persisted corpus database.",
                word_count=9,
                source_hash="read-only-source",
            )
        )
        session.commit()
        rebuild_keyword_index(session)

    before = sha256_path(database)
    with Session(engine) as session:
        for _ in range(3):
            results = search_keyword(session, "keyword retrieval", top_k=3)
            assert results[0]["chunk_id"] == "read-only-chunk"
    assert sha256_path(database) == before
