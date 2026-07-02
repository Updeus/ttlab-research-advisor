from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from sqlmodel import Session, select

from app.db import create_db_and_tables, engine
from app.models import Chunk

DEFAULT_PROVIDER = "hashing"
DEFAULT_DIMENSIONS = 256
DEFAULT_INDEX_PATH = Path("data/indexes/hashing_embeddings.json")


class EmbeddingProvider(Protocol):
    name: str
    dimensions: int

    def embed(self, text: str) -> list[float]:
        ...


@dataclass
class HashingEmbeddingProvider:
    dimensions: int = DEFAULT_DIMENSIONS
    name: str = DEFAULT_PROVIDER

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        tokens = tokenize(text)
        if not tokens:
            return vector
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign
        return normalize(vector)


def get_provider(provider_name: str = DEFAULT_PROVIDER, dimensions: int = DEFAULT_DIMENSIONS) -> EmbeddingProvider:
    if provider_name == "hashing":
        return HashingEmbeddingProvider(dimensions=dimensions)
    if provider_name == "openai":
        raise RuntimeError("OpenAI embedding provider is not enabled for Phase 3 offline mode.")
    if provider_name == "sentence_transformers":
        raise RuntimeError("sentence_transformers provider is optional and not installed by default.")
    raise ValueError(f"Unknown embedding provider: {provider_name}")


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in re.findall(r"[a-zA-Z0-9]+", text) if len(token) > 1]


def normalize(vector: list[float]) -> list[float]:
    magnitude = math.sqrt(sum(value * value for value in vector))
    if magnitude == 0:
        return vector
    return [value / magnitude for value in vector]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        return 0.0
    return sum(a * b for a, b in zip(left, right))


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def build_embedding_records(
    chunks: list[Chunk],
    provider: EmbeddingProvider,
) -> list[dict[str, Any]]:
    now = utc_now_iso()
    records: list[dict[str, Any]] = []
    for chunk in chunks:
        records.append(
            {
                "chunk_id": chunk.chunk_id,
                "paper_id": chunk.paper_id,
                "provider": provider.name,
                "dimensions": provider.dimensions,
                "source_hash": chunk.source_hash,
                "created_at": now,
                "embedding": provider.embed(chunk.text),
            }
        )
    return records


def write_embedding_index(records: list[dict[str, Any]], output_path: Path, provider: EmbeddingProvider) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "provider": provider.name,
        "dimensions": provider.dimensions,
        "created_at": utc_now_iso(),
        "records": records,
    }
    output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def index_chunks(
    session: Session,
    *,
    provider_name: str = DEFAULT_PROVIDER,
    limit: int | None = None,
    output_path: Path = DEFAULT_INDEX_PATH,
) -> dict[str, Any]:
    provider = get_provider(provider_name)
    statement = select(Chunk).order_by(Chunk.paper_id, Chunk.chunk_index)
    chunks = list(session.exec(statement).all())
    if limit is not None:
        chunks = chunks[:limit]
    records = build_embedding_records(chunks, provider)
    write_embedding_index(records, output_path, provider)
    for chunk in chunks:
        chunk.embedding_status = f"indexed:{provider.name}"
        session.add(chunk)
    session.commit()
    return {
        "provider": provider.name,
        "dimensions": provider.dimensions,
        "indexed_chunks": len(records),
        "index_path": str(output_path),
    }


def load_embedding_index(index_path: Path = DEFAULT_INDEX_PATH) -> dict[str, Any] | None:
    if not index_path.exists():
        return None
    return json.loads(index_path.read_text(encoding="utf-8"))


def index_diagnostics(index_path: Path = DEFAULT_INDEX_PATH) -> dict[str, Any]:
    payload = load_embedding_index(index_path)
    if payload is None:
        return {
            "semantic_indexed_chunks": 0,
            "embedding_provider": DEFAULT_PROVIDER,
            "embedding_dimensions": DEFAULT_DIMENSIONS,
            "index_path": str(index_path),
            "index_status": "missing",
            "last_indexed_at": None,
        }
    records = payload.get("records", [])
    return {
        "semantic_indexed_chunks": len(records),
        "embedding_provider": payload.get("provider", DEFAULT_PROVIDER),
        "embedding_dimensions": payload.get("dimensions", DEFAULT_DIMENSIONS),
        "index_path": str(index_path),
        "index_status": "ready",
        "last_indexed_at": payload.get("created_at"),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build deterministic local embeddings for chunks.")
    subparsers = parser.add_subparsers(dest="command")
    index = subparsers.add_parser("index")
    index.add_argument("--provider", default=DEFAULT_PROVIDER)
    index.add_argument("--limit", type=int, default=None)
    index.add_argument("--out", default=str(DEFAULT_INDEX_PATH))
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command != "index":
        build_parser().print_help()
        return
    create_db_and_tables()
    with Session(engine) as session:
        result = index_chunks(
            session,
            provider_name=args.provider,
            limit=args.limit,
            output_path=Path(args.out),
        )
    print(
        "provider={provider} dimensions={dimensions} indexed_chunks={indexed_chunks} "
        "index_path={index_path}".format(**result)
    )


if __name__ == "__main__":
    main()
