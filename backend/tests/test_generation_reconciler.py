from __future__ import annotations

from pathlib import Path

import fitz
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.indexing.chunker import chunk_from_db, chunk_manifest_path
from app.indexing.embedder import eligible_chunks
from app.ingestion.generation_reconciler import reconcile_generation_links
from app.ingestion.pdf_parser import extract_pdf_text
from app.models import Chunk, Paper


def memory_session() -> Session:
    local_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(local_engine)
    return Session(local_engine)


def create_source_chain(tmp_path: Path) -> tuple[Session, Paper, Path, dict[str, object]]:
    root = tmp_path / "project"
    pdf_dir = root / "data" / "pdfs"
    extraction_dir = root / "data" / "extracted_text"
    chunks_dir = root / "data" / "chunks"
    pdf_dir.mkdir(parents=True)
    pdf_path = pdf_dir / "linked-paper.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text(
        (72, 72),
        "Linked Paper Abstract deterministic retrieval evidence for generation reconciliation.",
    )
    document.save(pdf_path)
    document.close()
    extracted = extract_pdf_text(
        "linked-paper",
        pdf_path,
        extraction_dir,
        expected_title="Linked Paper",
    )
    session = memory_session()
    paper = Paper(
        paper_id="linked-paper",
        title="Linked Paper",
        local_pdf_path=str(pdf_path),
        extracted_json_path=str(extraction_dir / "linked-paper.json"),
        extracted_text_path=str(extraction_dir / "linked-paper.txt"),
        pdf_text_status="extracted",
        corpus_eligibility_status="eligible",
        extraction_generation_id=str(extracted["artifact_generation_id"]),
    )
    session.add(paper)
    session.commit()
    result = chunk_from_db(session, output_dir=chunks_dir, min_chars=0)
    assert result["chunked"] == 1
    session.refresh(paper)
    return session, paper, root, extracted


def test_reconciler_promotes_only_exact_source_and_database_mirrors(tmp_path: Path) -> None:
    session, paper, root, extracted = create_source_chain(tmp_path)
    try:
        chunks = list(session.exec(select(Chunk).where(Chunk.paper_id == paper.paper_id)).all())
        expected_chunk_generation = paper.chunk_generation_id
        paper.extraction_generation_id = None
        paper.extraction_input_pdf_sha256 = None
        paper.extraction_config_sha256 = None
        paper.chunk_extraction_generation_id = None
        paper.chunk_generation_id = None
        paper.public_index_generation_id = "f" * 64
        paper.publication_status = "published"
        paper.public_access_level = "searchable"
        paper.extraction_review_status = "approved"
        for chunk in chunks:
            chunk.extraction_generation_id = None
            session.add(chunk)
        session.add(paper)
        session.commit()

        summary = reconcile_generation_links(session, project_root=root)
        session.refresh(paper)
        reconciled_chunks = list(
            session.exec(select(Chunk).where(Chunk.paper_id == paper.paper_id)).all()
        )

        assert summary == {
            "attempted": 1,
            "reconciled": 1,
            "already_current": 0,
            "quarantined": 0,
            "dry_run": False,
            "reasons": {},
        }
        assert paper.extraction_generation_id == extracted["artifact_generation_id"]
        assert paper.chunk_extraction_generation_id == extracted["artifact_generation_id"]
        assert paper.chunk_generation_id == expected_chunk_generation
        assert all(
            chunk.extraction_generation_id == extracted["artifact_generation_id"]
            for chunk in reconciled_chunks
        )
        assert [chunk.chunk_id for chunk in eligible_chunks(session)] == [
            chunk.chunk_id for chunk in reconciled_chunks
        ]
        assert paper.public_index_generation_id is None
        assert paper.publication_status == "pending_review"
        assert paper.public_access_level == "hidden"
        assert paper.extraction_review_status == "needs_review"

        second = reconcile_generation_links(session, project_root=root)
        assert second["already_current"] == 1
        assert second["reconciled"] == 0
    finally:
        session.close()


def test_reconciler_quarantines_legacy_or_tampered_chunk_artifacts(tmp_path: Path) -> None:
    session, paper, root, _extracted = create_source_chain(tmp_path)
    try:
        chunk_path = root / "data" / "chunks" / "linked-paper.json"
        chunk_manifest_path(chunk_path).unlink()
        paper.public_index_generation_id = paper.chunk_generation_id
        paper.publication_status = "published"
        paper.public_access_level = "searchable"
        session.add(paper)
        session.commit()

        summary = reconcile_generation_links(session, project_root=root)
        session.refresh(paper)
        chunks = list(session.exec(select(Chunk).where(Chunk.paper_id == paper.paper_id)).all())

        assert summary["quarantined"] == 1
        assert summary["reasons"] == {"missing_chunk_manifest": 1}
        assert paper.extraction_generation_id is not None
        assert paper.chunk_extraction_generation_id is None
        assert paper.chunk_generation_id is None
        assert paper.public_index_generation_id is None
        assert paper.public_access_level == "hidden"
        assert paper.corpus_eligibility_status == "needs_review"
        assert paper.corpus_exclusion_reason == "generation_reconciliation:missing_chunk_manifest"
        assert all(chunk.extraction_generation_id is None for chunk in chunks)
        assert eligible_chunks(session) == []
    finally:
        session.close()
