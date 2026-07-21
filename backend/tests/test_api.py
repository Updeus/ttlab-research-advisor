from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.db import get_session
from app.indexing.chunker import canonical_chunks_sha256, db_chunk_payload
from app.main import app
from app.models import Chunk, Paper


def test_health_works() -> None:
    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_root_and_favicon_are_demo_friendly() -> None:
    client = TestClient(app)

    root = client.get("/")
    assert root.status_code == 200
    assert root.json()["api_docs"] == "/docs"
    assert root.json()["frontend"] == "http://127.0.0.1:5173"

    favicon = client.get("/favicon.ico")
    assert favicon.status_code == 204


def test_anonymous_search_warning_never_discloses_local_index_path(monkeypatch) -> None:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    def override_session() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session

    monkeypatch.setattr(
        "app.indexing.retriever.search_vector_store",
        lambda *_args, **_kwargs: (
            [],
            ["feature_hashing index is unavailable at /private/workstation/data/index.json"],
        ),
    )
    app.dependency_overrides[get_session] = override_session
    try:
        response = TestClient(app).get(
            "/api/search",
            params={"q": "retrieval", "mode": "feature_hashing"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    serialized = str(response.json())
    assert "/private/workstation" not in serialized
    assert response.json()["warnings"] == [
        "A retrieval component is unavailable; local configuration details are not exposed."
    ]


def test_api_papers_returns_imported_records() -> None:
    extraction_generation = "a" * 64
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        paper = Paper(
            paper_id="api-paper",
            title="API Paper",
            authors=["Asha Singh"],
            year=2026,
            local_pdf_path="data/pdfs/api-paper.pdf",
            pdf_text_status="missing_pdf",
            page_count=2,
            total_word_count=120,
            pages_with_text=2,
            pages_without_text=0,
            chunk_count=1,
            corpus_eligibility_status="eligible",
            review_status="approved",
            extraction_review_status="approved",
            publication_status="published",
            rights_status="cleared",
            public_access_level="searchable",
            extraction_generation_id=extraction_generation,
            chunk_extraction_generation_id=extraction_generation,
        )
        session.add(paper)
        session.add(
            Chunk(
                chunk_id="api-paper-chunk-0001",
                paper_id="api-paper",
                chunk_index=0,
                page_start=1,
                page_end=2,
                section="Introduction",
                text="This chunk describes the API paper and its extracted source text.",
                char_count=66,
                word_count=11,
                token_count_estimate=14,
                source_hash="abc123",
                extraction_generation_id=extraction_generation,
            )
        )
        session.flush()
        chunks = list(session.exec(select(Chunk).where(Chunk.paper_id == paper.paper_id)).all())
        paper.chunk_generation_id = canonical_chunks_sha256(db_chunk_payload(chunks))
        paper.public_index_generation_id = paper.chunk_generation_id
        session.add(paper)
        session.commit()

    def override_session() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    try:
        client = TestClient(app)
        response = client.get("/api/papers")

        assert response.status_code == 200
        body = response.json()
        assert len(body) == 1
        assert body[0]["paper_id"] == "api-paper"

        extraction = client.get("/api/papers/api-paper/extraction")
        assert extraction.status_code == 200
        assert extraction.json()["page_count"] == 2

        chunks = client.get("/api/papers/api-paper/chunks")
        assert chunks.status_code == 200
        assert chunks.json()[0]["chunk_index"] == 0

        stats = client.get("/api/stats")
        assert stats.status_code == 200
        assert stats.json()["total_chunks"] == 1
    finally:
        app.dependency_overrides.clear()
