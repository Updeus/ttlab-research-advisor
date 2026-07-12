from pathlib import Path
from typing import Generator

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.db import get_session
from app.evaluation.retrieval_eval import calculate_metrics, evaluate_retrieval
from app.indexing.embedder import HashingEmbeddingProvider, index_chunks
from app.indexing.keyword_search import make_snippet, rebuild_keyword_index, search_keyword
from app.indexing.retriever import diversify_ranked_entries, expand_query, has_rag_signal, retrieve
from app.indexing.vector_store import search_vector_store
from app.main import app
from app.models import Chunk, Paper


def build_test_session() -> tuple[Session, object]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    session = Session(engine)
    session.add(Paper(paper_id="rag-paper", title="RAG Paper", authors=["Asha Singh"], year=2025, pdf_url="https://example.test/rag.pdf"))
    session.add(Paper(paper_id="traffic-paper", title="Traffic Paper", authors=["Ben Lee"], year=2024))
    session.add(
        Chunk(
            chunk_id="rag-chunk",
            paper_id="rag-paper",
            chunk_index=0,
            page_start=1,
            page_end=2,
            section="Introduction",
            text="Retrieval augmented generation combines search with grounded academic research systems.",
            word_count=10,
            source_hash="rag-hash",
        )
    )
    session.add(
        Chunk(
            chunk_id="traffic-chunk",
            paper_id="traffic-paper",
            chunk_index=0,
            page_start=3,
            page_end=4,
            section="Results",
            text="Highway congestion and carpool lane measurements describe empirical traffic behavior.",
            word_count=9,
            source_hash="traffic-hash",
        )
    )
    session.commit()
    return session, engine


def test_keyword_search_returns_matching_chunks() -> None:
    session, _engine = build_test_session()
    try:
        rebuild_keyword_index(session)
        results = search_keyword(session, "retrieval academic", top_k=3)
    finally:
        session.close()

    assert results
    assert results[0]["chunk_id"] == "rag-chunk"
    assert "[[Retrieval]]" in results[0]["snippet"]


def test_keyword_search_handles_no_results() -> None:
    session, _engine = build_test_session()
    try:
        results = search_keyword(session, "plankton", top_k=3)
    finally:
        session.close()

    assert results == []


def test_hashing_embeddings_are_deterministic() -> None:
    provider = HashingEmbeddingProvider(dimensions=32)

    assert provider.embed("RAG academic research") == provider.embed("RAG academic research")


def test_vector_search_ranks_relevant_chunk_above_unrelated(tmp_path: Path) -> None:
    session, _engine = build_test_session()
    index_path = tmp_path / "embeddings.json"
    try:
        index_chunks(session, output_path=index_path)
        results, warnings = search_vector_store(session, "retrieval augmented search", top_k=2, index_path=index_path)
    finally:
        session.close()

    assert warnings == []
    assert results[0]["chunk_id"] == "rag-chunk"


def test_hybrid_retrieval_combines_scores_and_returns_pages(tmp_path: Path) -> None:
    session, _engine = build_test_session()
    index_path = tmp_path / "embeddings.json"
    try:
        rebuild_keyword_index(session)
        index_chunks(session, output_path=index_path)
        response = retrieve(session, "retrieval academic", mode="hybrid", top_k=2, index_path=index_path)
    finally:
        session.close()

    assert response["results"][0]["paper_id"] == "rag-paper"
    assert response["results"][0]["page_start"] == 1
    assert response["results"][0]["scores"]["combined"] > 0


def test_query_expansion_adds_rag_ai_and_optimization_synonyms() -> None:
    expanded, additions = expand_query("RAG and AI optimization")

    assert "retrieval augmented generation" in expanded
    assert "artificial intelligence" in expanded
    assert "optimisation" in additions


def test_query_expansion_adds_agriculture_terms() -> None:
    expanded, additions = expand_query("agriculture and AI")

    assert "cocoa" in expanded
    assert "biomass" in additions
    assert "artificial intelligence" in expanded


def test_snippet_highlighting_uses_word_boundaries() -> None:
    snippet = make_snippet("Contact hotmail support before reviewing AI crop research.", ["ai", "crop"])

    assert "hotm[[ai]]l" not in snippet
    assert "[[AI]]" in snippet
    assert "[[crop]]" in snippet


def test_rag_signal_does_not_match_average() -> None:
    assert not has_rag_signal({"paper_title": "Average Model Performance", "snippet": "The average score improved.", "text": ""})
    assert has_rag_signal({"paper_title": "RAG Model Performance", "snippet": "Retrieval-augmented generation improved.", "text": ""})


def test_retrieval_respects_paper_filter(tmp_path: Path) -> None:
    session, _engine = build_test_session()
    index_path = tmp_path / "embeddings.json"
    try:
        rebuild_keyword_index(session)
        index_chunks(session, output_path=index_path)
        response = retrieve(session, "retrieval traffic academic", mode="hybrid", top_k=3, paper_id="traffic-paper", index_path=index_path)
    finally:
        session.close()

    assert response["results"]
    assert {result["paper_id"] for result in response["results"]} == {"traffic-paper"}


def test_diversity_prefers_a_second_paper_when_scores_are_close() -> None:
    entries = [
        {"base": {"paper_id": "rag-paper", "chunk_index": 0}, "base_combined": 0.99},
        {"base": {"paper_id": "rag-paper", "chunk_index": 1}, "base_combined": 0.98},
        {"base": {"paper_id": "traffic-paper", "chunk_index": 0}, "base_combined": 0.95},
    ]

    selected = diversify_ranked_entries(entries, top_k=2)

    assert [entry["base"]["paper_id"] for entry in selected] == ["rag-paper", "traffic-paper"]


def test_api_search_and_diagnostics_work() -> None:
    session, engine = build_test_session()
    rebuild_keyword_index(session)
    session.close()

    def override_session() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    try:
        client = TestClient(app)
        keyword = client.get("/api/search", params={"q": "retrieval", "mode": "keyword", "limit": 5})
        semantic = client.get("/api/search", params={"q": "retrieval", "mode": "semantic", "limit": 5})
        diagnostics = client.get("/api/search/diagnostics")
        stats = client.get("/api/stats")
    finally:
        app.dependency_overrides.clear()

    assert keyword.status_code == 200
    assert keyword.json()["results"][0]["paper_id"] == "rag-paper"
    assert semantic.status_code == 200
    assert "warnings" in semantic.json()
    assert diagnostics.status_code == 200
    assert diagnostics.json()["searchable_chunks"] == 2
    assert stats.status_code == 200
    assert "keyword_indexed_chunks" in stats.json()


def test_retrieval_eval_metrics() -> None:
    evaluated = [
        {"hit_at_3": True, "hit_at_5": True, "reciprocal_rank": 1.0},
        {"hit_at_3": False, "hit_at_5": True, "reciprocal_rank": 0.25},
    ]

    metrics = calculate_metrics(evaluated)

    assert metrics["recall_at_3"] == 0.5
    assert metrics["recall_at_5"] == 1.0
    assert metrics["mrr"] == 0.625


def test_retrieval_eval_runs_on_fixture_questions(tmp_path: Path) -> None:
    session, _engine = build_test_session()
    index_path = tmp_path / "embeddings.json"
    try:
        rebuild_keyword_index(session)
        index_chunks(session, output_path=index_path)
        questions = [{"question": "retrieval augmented generation", "gold_paper_ids": ["rag-paper"]}]
        result = evaluate_retrieval(session, questions, mode="keyword", top_k=5)
    finally:
        session.close()

    assert result["metrics"]["question_count"] == 1
    assert result["metrics"]["recall_at_5"] == 1.0
