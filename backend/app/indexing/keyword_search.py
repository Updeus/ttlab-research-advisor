from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlmodel import Session, select

from app.db import create_db_and_tables, engine
from app.indexing.embedder import corpus_descriptor, eligible_chunks
from app.models import Chunk, Paper

STOPWORDS = {
    "about",
    "also",
    "and",
    "are",
    "can",
    "could",
    "discuss",
    "does",
    "for",
    "from",
    "have",
    "how",
    "into",
    "main",
    "papers",
    "paper",
    "read",
    "relate",
    "relates",
    "research",
    "show",
    "that",
    "the",
    "this",
    "to",
    "want",
    "what",
    "which",
    "who",
    "with",
}

KEYWORD_PROVIDER = "sqlite_fts5_bm25"
KEYWORD_CONFIG = {
    "provider": KEYWORD_PROVIDER,
    "tokenizer": "sqlite_fts5_default_unicode61",
    "query_operator": "OR",
    "ranker": "bm25",
}


class KeywordIndexIntegrityError(RuntimeError):
    """Raised when persisted FTS rows do not match their corpus snapshot."""


@dataclass
class SearchFilters:
    paper_id: str | None = None
    author: str | None = None
    year: int | None = None
    section: str | None = None


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def tokenize(query: str) -> list[str]:
    return [
        token.lower()
        for token in re.findall(r"[a-zA-Z0-9]+", query)
        if len(token) > 1 and token.lower() not in STOPWORDS
    ]


def supports_fts5(session: Session) -> bool:
    """Detect FTS5 without creating/dropping schema objects on a read path."""

    try:
        enabled = session.execute(text("SELECT sqlite_compileoption_used('ENABLE_FTS5')")).scalar_one()
        return bool(enabled)
    except Exception:
        session.rollback()
        return False


def rebuild_keyword_index(session: Session) -> dict[str, Any]:
    chunks = eligible_chunks(session)
    corpus = corpus_descriptor(chunks)
    fts_available = supports_fts5(session)
    if fts_available:
        session.exec(
            text(
                "CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts "
                "USING fts5(chunk_id UNINDEXED, paper_id UNINDEXED, text)"
            )
        )
        session.exec(text("DELETE FROM chunk_fts"))
        for chunk in chunks:
            session.execute(
                text("INSERT INTO chunk_fts(chunk_id, paper_id, text) VALUES (:chunk_id, :paper_id, :text)"),
                params={"chunk_id": chunk.chunk_id, "paper_id": chunk.paper_id, "text": chunk.text},
            )
        session.exec(
            text(
                "CREATE TABLE IF NOT EXISTS chunk_fts_metadata "
                "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
        )
        session.exec(text("DELETE FROM chunk_fts_metadata"))
        metadata = {
            "provider": KEYWORD_PROVIDER,
            "configuration": KEYWORD_CONFIG,
            "configuration_hash": hashlib.sha256(
                json.dumps(KEYWORD_CONFIG, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
            "corpus": corpus,
            "indexed_chunk_count": len(chunks),
            "completeness_status": "complete",
            "created_at": utc_now_iso(),
        }
        for key, value in metadata.items():
            session.execute(
                text("INSERT INTO chunk_fts_metadata(key, value) VALUES (:key, :value)"),
                params={"key": key, "value": json.dumps(value, sort_keys=True)},
            )
    session.commit()
    return {
        "fts_available": fts_available,
        "indexed_chunks": len(chunks),
        "eligible_chunks": len(chunks),
        "eligible_papers": corpus["eligible_paper_count"],
        "corpus_snapshot_id": corpus["snapshot_id"],
        "corpus_snapshot_hash": corpus["snapshot_hash"],
        "completeness_status": "complete" if fts_available else "fallback_only",
        "last_indexed_at": utc_now_iso(),
    }


def keyword_index_count(session: Session) -> int:
    if not supports_fts5(session):
        return session.exec(select(Chunk)).all().__len__()
    try:
        return int(session.execute(text("SELECT count(*) FROM chunk_fts")).scalar_one())
    except Exception:
        return 0


def keyword_index_metadata(session: Session) -> dict[str, Any] | None:
    try:
        rows = session.execute(text("SELECT key, value FROM chunk_fts_metadata")).all()
    except Exception:
        session.rollback()
        return None
    metadata: dict[str, Any] = {}
    try:
        for key, value in rows:
            metadata[str(key)] = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return None
    return metadata or None


def search_keyword(
    session: Session,
    query: str,
    *,
    top_k: int = 10,
    filters: SearchFilters | None = None,
) -> list[dict[str, Any]]:
    filters = filters or SearchFilters()
    terms = tokenize(query)
    if not terms:
        return []
    if supports_fts5(session):
        metadata = keyword_index_metadata(session)
        health = diagnostics(session)
        if health["status"] == "invalid":
            raise KeywordIndexIntegrityError("; ".join(health["errors"]))
        if metadata is None:
            # No FTS index has been built in this database; use the explicit
            # eligible-corpus fallback rather than treating it as indexed.
            return search_fallback(session, terms, top_k=top_k, filters=filters)
        try:
            results = search_fts(session, terms, top_k=max(top_k * 3, top_k), filters=filters)
            if results:
                return results[:top_k]
        except Exception:
            session.rollback()
    return search_fallback(session, terms, top_k=top_k, filters=filters)


def search_fts(
    session: Session,
    terms: list[str],
    *,
    top_k: int,
    filters: SearchFilters,
) -> list[dict[str, Any]]:
    match_query = " OR ".join(f'"{term}"' for term in terms)
    rows = session.execute(
        text(
            "SELECT chunk_id, bm25(chunk_fts) AS rank_score "
            "FROM chunk_fts WHERE chunk_fts MATCH :query ORDER BY rank_score LIMIT :limit"
        ),
        params={"query": match_query, "limit": top_k},
    ).all()
    chunk_scores = {row[0]: 1.0 / (1.0 + abs(float(row[1] or 0.0))) for row in rows}
    chunks = chunks_by_id(session, list(chunk_scores))
    return [
        build_keyword_result(chunk, chunk_scores[chunk.chunk_id], terms)
        for chunk in chunks
        if matches_filters(chunk, filters)
    ]


def search_fallback(
    session: Session,
    terms: list[str],
    *,
    top_k: int,
    filters: SearchFilters,
) -> list[dict[str, Any]]:
    chunks = eligible_chunks(session)
    scored: list[tuple[float, Chunk]] = []
    for chunk in chunks:
        if not matches_filters(chunk, filters):
            continue
        text_lower = chunk.text.lower()
        hits = sum(text_lower.count(term) for term in terms)
        if hits == 0:
            continue
        coverage = sum(1 for term in terms if term in text_lower) / len(terms)
        score = min(1.0, (hits / max(chunk.word_count, 1)) * 30.0 + coverage * 0.6)
        scored.append((score, chunk))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [build_keyword_result(chunk, score, terms) for score, chunk in scored[:top_k]]


def chunks_by_id(session: Session, chunk_ids: list[str]) -> list[Chunk]:
    if not chunk_ids:
        return []
    chunks = list(session.exec(select(Chunk).where(Chunk.chunk_id.in_(chunk_ids))).all())
    order = {chunk_id: index for index, chunk_id in enumerate(chunk_ids)}
    return sorted(chunks, key=lambda chunk: order.get(chunk.chunk_id, 999999))


def paper_for_chunk(session: Session, chunk: Chunk) -> Paper | None:
    return session.get(Paper, chunk.paper_id)


def matches_filters(chunk: Chunk, filters: SearchFilters) -> bool:
    if filters.paper_id and chunk.paper_id != filters.paper_id:
        return False
    if filters.section and (chunk.section or "").lower() != filters.section.lower():
        return False
    return True


def matches_paper_filters(paper: Paper | None, filters: SearchFilters) -> bool:
    if paper is None:
        return False
    if filters.year is not None and paper.year != filters.year:
        return False
    if filters.author:
        needle = filters.author.lower()
        if not any(needle in author.lower() for author in paper.authors):
            return False
    return True


def build_keyword_result(chunk: Chunk, score: float, terms: list[str]) -> dict[str, Any]:
    return {
        "chunk_id": chunk.chunk_id,
        "paper_id": chunk.paper_id,
        "chunk_index": chunk.chunk_index,
        "section": chunk.section,
        "page_start": chunk.page_start,
        "page_end": chunk.page_end,
        "snippet": make_snippet(chunk.text, terms),
        "text": chunk.text,
        "score": round(float(score), 6),
        "match_type": "keyword",
    }


def enrich_keyword_results(
    session: Session,
    results: list[dict[str, Any]],
    filters: SearchFilters | None = None,
) -> list[dict[str, Any]]:
    filters = filters or SearchFilters()
    enriched: list[dict[str, Any]] = []
    for result in results:
        paper = session.get(Paper, result["paper_id"])
        if not matches_paper_filters(paper, filters):
            continue
        enriched.append(
            {
                **result,
                "paper_title": paper.title if paper else "",
                "authors": paper.authors if paper else [],
                "year": paper.year if paper else None,
                "venue": paper.venue if paper else None,
                "topics": paper.topics if paper else [],
                "source": {
                    "pdf_url": paper.pdf_url if paper else None,
                    "post_url": paper.post_url if paper else None,
                },
            }
        )
    return enriched


def make_snippet(text_value: str, terms: list[str], window: int = 240) -> str:
    lowered = text_value.lower()
    positions: list[int] = []
    for term in terms:
        pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", flags=re.IGNORECASE)
        match = pattern.search(text_value)
        if match:
            positions.append(match.start())
            continue
        found = lowered.find(term)
        if found >= 0 and len(term) > 3:
            positions.append(found)
    start = max(min(positions) - 80, 0) if positions else 0
    snippet = re.sub(r"\s+", " ", text_value[start : start + window]).strip()
    for term in sorted(set(terms), key=len, reverse=True):
        boundary = rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])"
        snippet = re.sub(
            boundary,
            lambda match: f"[[{match.group(0)}]]",
            snippet,
            flags=re.IGNORECASE,
        )
    return snippet


def diagnostics(session: Session) -> dict[str, Any]:
    current_chunks = eligible_chunks(session)
    current_corpus = corpus_descriptor(current_chunks)
    total_chunks = len(current_chunks)
    indexed = keyword_index_count(session)
    metadata = keyword_index_metadata(session)
    errors: list[str] = []
    if metadata is None:
        status = "not_built" if indexed == 0 else "invalid"
        if indexed:
            errors.append("FTS rows exist without authoritative chunk_fts_metadata.")
    else:
        stored_corpus = metadata.get("corpus") or {}
        if metadata.get("provider") != KEYWORD_PROVIDER:
            errors.append("FTS provider metadata is missing or incorrect.")
        if metadata.get("configuration_hash") != hashlib.sha256(
            json.dumps(KEYWORD_CONFIG, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest():
            errors.append("FTS configuration hash does not match runtime configuration.")
        if stored_corpus.get("snapshot_hash") != current_corpus["snapshot_hash"]:
            errors.append("FTS corpus snapshot does not match the current eligible corpus.")
        if int(metadata.get("indexed_chunk_count") or -1) != indexed:
            errors.append("FTS metadata count does not match persisted rows.")
        if indexed != total_chunks:
            errors.append("FTS row count does not equal eligible chunk count.")
        status = "invalid" if errors else "ready"
    return {
        "fts_available": supports_fts5(session),
        "keyword_indexed_chunks": indexed,
        "eligible_chunks": total_chunks,
        "eligible_papers": current_corpus["eligible_paper_count"],
        "coverage_ratio": round(indexed / total_chunks, 6) if total_chunks else 1.0,
        "corpus_snapshot_id": current_corpus["snapshot_id"],
        "corpus_snapshot_hash": current_corpus["snapshot_hash"],
        "stored_corpus_snapshot_hash": (metadata or {}).get("corpus", {}).get("snapshot_hash"),
        "completeness_status": (metadata or {}).get("completeness_status", "missing"),
        "provider": KEYWORD_PROVIDER,
        "errors": errors,
        "total_chunks": total_chunks,
        "status": status,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Keyword search over source chunks.")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("rebuild")
    search = subparsers.add_parser("search")
    search.add_argument("query")
    search.add_argument("--top-k", type=int, default=5)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    create_db_and_tables()
    with Session(engine) as session:
        if args.command == "rebuild":
            result = rebuild_keyword_index(session)
            print(
                "fts_available={fts_available} indexed_chunks={indexed_chunks} "
                "last_indexed_at={last_indexed_at}".format(**result)
            )
            return
        if args.command == "search":
            raw = search_keyword(session, args.query, top_k=args.top_k)
            results = enrich_keyword_results(session, raw)
            for index, result in enumerate(results, start=1):
                print(
                    f"{index}. score={result['score']:.4f} paper={result['paper_title']} "
                    f"pages={result['page_start']}-{result['page_end']} snippet={result['snippet']}"
                )
            return
    build_parser().print_help()


if __name__ == "__main__":
    main()
