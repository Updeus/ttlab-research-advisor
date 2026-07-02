from pathlib import Path
from typing import Generator

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.db import get_session
from app.indexing.keyword_search import rebuild_keyword_index
from app.intelligence.citation_verifier import verify_citations
from app.intelligence.llm_provider import OfflineExtractiveProvider
from app.intelligence.rag_answerer import ask_question
from app.main import app
from app.models import Chunk, Paper, RAGAnswer


def build_ask_session() -> tuple[Session, object]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    session = Session(engine)
    session.add(Paper(paper_id="rag-paper", title="RAG Paper", authors=["Asha Singh"], year=2025, pdf_url="https://example.test/rag.pdf"))
    session.add(
        Chunk(
            chunk_id="rag-chunk",
            paper_id="rag-paper",
            chunk_index=0,
            page_start=1,
            page_end=2,
            section="Introduction",
            text="Retrieval augmented generation uses retrieved paper chunks to ground answers with citations.",
            word_count=11,
            source_hash="rag-hash",
        )
    )
    session.commit()
    rebuild_keyword_index(session)
    return session, engine


def test_offline_provider_returns_answer_from_chunks() -> None:
    provider = OfflineExtractiveProvider()
    draft = provider.generate_answer(
        "Which papers discuss retrieval augmented generation?",
        [{"snippet": "Retrieval augmented generation uses retrieved chunks to ground answers."}],
    )

    assert draft.provider == "offline_extractive"
    assert "indexed TTLAB paper chunks" in draft.answer_text
    assert "Retrieval augmented generation" in draft.answer_text


def test_citation_verifier_marks_grounded_and_missing_citations() -> None:
    retrieved = [{"chunk_id": "c1", "snippet": "Retrieval augmented generation grounds answers with citations."}]
    citations = [{"chunk_id": "c1", "paper_id": "p1", "title": "Paper", "page_start": 1, "page_end": 2, "snippet": retrieved[0]["snippet"]}]

    grounded = verify_citations("Retrieval augmented generation grounds answers with citations.", retrieved, citations)
    unsupported = verify_citations("Retrieval augmented generation grounds answers.", retrieved, [])

    assert grounded["grounding_status"] == "grounded"
    assert unsupported["grounding_status"] == "unsupported"


def test_rag_answerer_returns_citations_and_persists() -> None:
    session, _engine = build_ask_session()
    try:
        response = ask_question(session, "Which papers discuss retrieval augmented generation?", mode="keyword", top_k=3)
        stored = session.get(RAGAnswer, response["answer_id"])
    finally:
        session.close()

    assert response["citations"]
    assert response["citations"][0]["paper_id"] == "rag-paper"
    assert response["grounding_status"] in {"grounded", "partial"}
    assert stored is not None


def test_rag_answerer_returns_unsupported_when_no_chunks() -> None:
    session, _engine = build_ask_session()
    try:
        response = ask_question(session, "volcanic mineral policy", mode="keyword", top_k=3)
    finally:
        session.close()

    assert response["grounding_status"] == "unsupported"
    assert response["citations"] == []


def test_ask_api_endpoints_work() -> None:
    session, engine = build_ask_session()
    session.close()

    def override_session() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    try:
        client = TestClient(app)
        posted = client.post(
            "/api/ask",
            json={"question": "Which papers discuss retrieval augmented generation?", "mode": "keyword", "top_k": 3},
        )
        answer_id = posted.json()["answer_id"]
        fetched = client.get(f"/api/ask/{answer_id}")
        history = client.get("/api/ask/history")
        diagnostics = client.get("/api/ask/diagnostics")
    finally:
        app.dependency_overrides.clear()

    assert posted.status_code == 200
    assert posted.json()["citations"]
    assert fetched.status_code == 200
    assert history.status_code == 200
    assert history.json()[0]["answer_id"] == answer_id
    assert diagnostics.status_code == 200
    assert diagnostics.json()["total_stored_answers"] == 1
