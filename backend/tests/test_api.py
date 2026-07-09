from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.db import get_session
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


def test_api_papers_returns_imported_records() -> None:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            Paper(
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
                review_status="needs_review",
            )
        )
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
            )
        )
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
