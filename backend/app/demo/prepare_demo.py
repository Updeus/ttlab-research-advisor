from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from sqlmodel import Session, func, select

from app.db import create_db_and_tables, engine
from app.indexing.chunker import chunk_from_db
from app.indexing.embedder import DEMO_INDEX_PATH, FEATURE_HASHING_PROVIDER, index_chunks
from app.indexing.keyword_search import rebuild_keyword_index
from app.ingestion.manual_import import load_seed, upsert_papers
from app.ingestion.pdf_downloader import download_pdfs, filter_records, load_records_from_db
from app.ingestion.pdf_parser import extract_from_db
from app.intelligence.paper_artifact_generator import batch_generate_paper_artifacts
from app.intelligence.topic_explorer import rebuild_topic_index
from app.models import Author, Chunk, Paper, PaperArtifact, Topic


def prepare_demo(
    limit: int = 25,
    *,
    skip_downloads: bool = False,
    skip_artifacts: bool = False,
    session: Session | None = None,
) -> dict[str, Any]:
    if session is not None:
        return prepare_demo_with_session(session, limit=limit, skip_downloads=skip_downloads, skip_artifacts=skip_artifacts)
    create_db_and_tables()
    with Session(engine) as live_session:
        return prepare_demo_with_session(live_session, limit=limit, skip_downloads=skip_downloads, skip_artifacts=skip_artifacts)


def prepare_demo_with_session(
    session: Session,
    *,
    limit: int,
    skip_downloads: bool,
    skip_artifacts: bool,
) -> dict[str, Any]:
    summary: dict[str, Any] = {"limit": limit, "warnings": [], "seed": seed_status()}
    if session.exec(select(func.count()).select_from(Paper)).one() == 0:
        seed_path = first_existing_seed()
        if seed_path is None:
            summary["warnings"].append("No seed file found under data/seed; import papers before demo prep.")
        else:
            summary["import"] = upsert_papers(session, load_seed(seed_path))

    if not skip_downloads:
        records = filter_records(load_records_from_db(session), paper_ids=None, only_missing=True, output_dir=Path("data/pdfs"))
        if records:
            summary["download"] = download_pdfs(records, Path("data/pdfs"), limit=limit, download=True, session=session)
            if summary["download"].get("failed") or summary["download"].get("invalid_pdf"):
                summary["warnings"].append(
                    "Some PDFs could not be downloaded or validated; existing local data can still be used for the demo."
                )
        else:
            summary["download"] = {"skipped_existing": "all available direct PDFs already have local paths"}
    else:
        summary["download"] = {"skipped": "skip_downloads requested"}

    summary["extract"] = extract_from_db(session, limit=limit)
    summary["chunk"] = chunk_from_db(session, limit=limit)
    summary["keyword_index"] = rebuild_keyword_index(session)
    # A bounded demo index is deliberately isolated from the authoritative
    # full-corpus index and never updates authoritative DB embedding statuses.
    summary["feature_hashing_demo_index"] = index_chunks(
        session,
        provider_name=FEATURE_HASHING_PROVIDER,
        limit=limit,
        output_path=DEMO_INDEX_PATH,
        allow_partial=True,
        update_db_status=False,
        index_role="bounded_demo",
    )
    summary["semantic_index"] = summary["feature_hashing_demo_index"]  # legacy summary key
    summary["topic_explorer"] = rebuild_topic_index(session)

    chunked_papers = session.exec(select(func.count(func.distinct(Chunk.paper_id))).select_from(Chunk)).one()
    artifact_count = session.exec(select(func.count()).select_from(PaperArtifact)).one()
    if not skip_artifacts and chunked_papers and artifact_count == 0:
        summary["artifacts"] = batch_generate_paper_artifacts(
            session,
            limit=5,
            artifact_types=["paper_intelligence_bundle", "podcast_script"],
            provider="auto",
            max_chunks=12,
            overwrite=False,
        )
    elif skip_artifacts:
        summary["artifacts"] = {"skipped": "skip_artifacts requested"}
    else:
        summary["artifacts"] = {"skipped": "artifacts already exist or no chunks are available"}
    summary["demo_summary"] = demo_summary(session)
    summary["routes"] = {
        "frontend": "http://127.0.0.1:5173",
        "backend": "http://127.0.0.1:8000",
        "dashboard": "http://127.0.0.1:5173",
        "api_docs": "http://127.0.0.1:8000/docs",
    }
    return summary


def seed_status() -> dict[str, Any]:
    seed_path = first_existing_seed()
    return {
        "exists": seed_path is not None,
        "path": str(seed_path) if seed_path else None,
    }


def demo_summary(session: Session) -> dict[str, Any]:
    from app.indexing.embedder import index_diagnostics
    from app.indexing.keyword_search import diagnostics as keyword_diagnostics

    keyword = keyword_diagnostics(session)
    semantic = index_diagnostics(session)
    return {
        "papers_imported": session.exec(select(func.count()).select_from(Paper)).one(),
        "pdfs_downloaded": session.exec(
            select(func.count()).select_from(Paper).where(Paper.local_pdf_path.is_not(None))
        ).one(),
        "extracted_papers": session.exec(
            select(func.count()).select_from(Paper).where(Paper.pdf_text_status == "extracted")
        ).one(),
        "chunks": session.exec(select(func.count()).select_from(Chunk)).one(),
        "keyword_indexed_chunks": keyword["keyword_indexed_chunks"],
        "semantic_indexed_chunks": semantic["semantic_indexed_chunks"],
        "topics": session.exec(select(func.count()).select_from(Topic)).one(),
        "authors": session.exec(select(func.count()).select_from(Author)).one(),
        "artifacts": session.exec(select(func.count()).select_from(PaperArtifact)).one(),
    }


def first_existing_seed() -> Path | None:
    for path in (Path("data/seed/ttlab_publications_discovered.json"), Path("data/seed/papers.json")):
        if path.exists():
            return path
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare a bounded local TTLAB demo dataset.")
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--skip-downloads", action="store_true")
    parser.add_argument("--skip-artifacts", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    summary = prepare_demo(limit=args.limit, skip_downloads=args.skip_downloads, skip_artifacts=args.skip_artifacts)
    for key, value in summary.items():
        print(f"{key}={value}")
    if summary.get("warnings"):
        print("status=completed_with_warnings")
    else:
        print("status=ready")
    print("next_backend=uvicorn app.main:app --reload --app-dir backend")
    print("next_frontend=cd frontend && npm run dev")
    print("topic_show=PYTHONPATH=backend .venv/bin/python -m app.intelligence.topic_explorer show --topic \"RAG\"")
    print("smoke_check=PYTHONPATH=backend .venv/bin/python -m app.demo.smoke_check")


if __name__ == "__main__":
    main()
