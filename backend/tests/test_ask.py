from pathlib import Path
from typing import Generator

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.db import get_session
from app.config import Settings
from app.indexing.keyword_search import rebuild_keyword_index
from app.indexing.chunker import canonical_chunks_sha256, db_chunk_payload
from app.intelligence.citation_verifier import verify_citations
from app.intelligence.llm_provider import LLMAnswerDraft, OfflineExtractiveProvider, OllamaProvider, build_extractive_answer
from app.intelligence import rag_answerer as rag_answerer_module
from app.intelligence.rag_answerer import ask_diagnostics, ask_question
from app.main import app
from app.models import Chunk, Paper, RAGAnswer

EXTRACTION_GENERATION = "a" * 64
CHUNK_GENERATION = "b" * 64


def build_ask_session() -> tuple[Session, object]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    session = Session(engine)
    session.add(
        Paper(
            paper_id="rag-paper",
            title="RAG Paper",
            authors=["Asha Singh"],
            year=2025,
            pdf_url="https://example.test/rag.pdf",
            corpus_eligibility_status="eligible",
            review_status="approved",
            extraction_review_status="approved",
            publication_status="published",
            rights_status="cleared",
            public_access_level="searchable",
            extraction_generation_id=EXTRACTION_GENERATION,
            chunk_extraction_generation_id=EXTRACTION_GENERATION,
            chunk_generation_id=CHUNK_GENERATION,
            public_index_generation_id=CHUNK_GENERATION,
            chunk_count=1,
        )
    )
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
            extraction_generation_id=EXTRACTION_GENERATION,
        )
    )
    session.flush()
    chunks = list(session.exec(select(Chunk).where(Chunk.paper_id == "rag-paper")).all())
    generation_id = canonical_chunks_sha256(db_chunk_payload(chunks))
    paper = session.get(Paper, "rag-paper")
    assert paper is not None
    paper.chunk_generation_id = generation_id
    paper.public_index_generation_id = generation_id
    session.add(paper)
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


def test_offline_provider_prioritizes_agriculture_evidence() -> None:
    answer = build_extractive_answer(
        "What research relates to agriculture or AI?",
        [
            {
                "chunk_id": "generic-ai",
                "title": "Generic AI Paper",
                "authors": ["A"],
                "year": 2025,
                "snippet": "Generative AI can evaluate workplace scenarios for candidate assessment.",
                "scores": {"combined": 0.9},
            },
            {
                "chunk_id": "crop-ai",
                "title": "Tropical Crops Paper",
                "authors": ["B"],
                "year": 2024,
                "snippet": "Artificial Intelligence can support precision agriculture using labelled crop datasets.",
                "scores": {"combined": 0.7},
            },
        ],
        max_words=120,
    )

    assert answer.index("Tropical Crops Paper") < answer.index("Generic AI Paper")


def test_offline_provider_extracts_explicit_limitations_before_weak_challenges() -> None:
    answer = build_extractive_answer(
        "What are the limitations or future work?",
        [
            {
                "chunk_id": "challenge",
                "title": "Discussion Paper",
                "authors": ["A"],
                "year": 2025,
                "snippet": "This result challenges the bigger is better narrative in model selection.",
                "scores": {"combined": 0.9},
            },
            {
                "chunk_id": "future",
                "title": "Future Work Paper",
                "authors": ["B"],
                "year": 2025,
                "snippet": "LIMITATIONS AND FUTURE WORK This study used a private dataset, so future research should evaluate public datasets.",
                "scores": {"combined": 0.6},
            },
        ],
        max_words=120,
    )

    assert "LIMITATIONS AND FUTURE WORK" in answer
    assert "bigger is better" not in answer


def test_ollama_provider_parses_mocked_response(monkeypatch) -> None:
    digest = "a" * 64

    def fake_get(*_args, **_kwargs):
        import httpx

        return httpx.Response(
            200,
            request=httpx.Request("GET", "http://localhost:11434/api/tags"),
            json={"models": [{"name": "mock-model", "digest": digest}]},
        )

    def fake_post(*_args, **kwargs):
        import httpx

        assert kwargs["json"]["model"] == "mock-model"
        return httpx.Response(
            200,
            request=httpx.Request("POST", "http://localhost:11434/api/generate"),
            json={
                "model": "mock-model",
                "digest": f"sha256:{digest}",
                "response": "The paper discusses retrieval augmented generation [rag-chunk].",
                "total_duration": 2_000_000_000,
                "eval_count": 40,
                "eval_duration": 1_000_000_000,
                "prompt_eval_count": 25,
                "prompt_eval_duration": 500_000_000,
                "load_duration": 100_000_000,
            },
        )

    monkeypatch.setattr("app.intelligence.llm_provider.httpx.post", fake_post)
    monkeypatch.setattr("app.intelligence.llm_provider.httpx.get", fake_get)
    monkeypatch.setattr(
        "app.intelligence.llm_provider.get_settings",
        lambda: Settings(ollama_allowed_model_digests={"mock-model": digest}),
    )
    provider = OllamaProvider(model_name="mock-model")
    draft = provider.generate_answer(
        "Which papers discuss retrieval augmented generation?",
        [{"chunk_id": "rag-chunk", "title": "RAG Paper", "snippet": "Retrieval augmented generation grounds answers."}],
    )

    assert draft.provider == "ollama"
    assert draft.model == f"mock-model@sha256:{digest}"
    assert draft.prompt_metadata["ollama_metrics"]["tokens_per_second"] == 40.0
    assert draft.prompt_metadata["generation_time_digest_verified"] is True


def test_ollama_provider_falls_back_when_unavailable(monkeypatch) -> None:
    def fake_post(*_args, **_kwargs):
        raise RuntimeError("ollama unavailable")

    digest = "b" * 64
    monkeypatch.setattr("app.intelligence.llm_provider.httpx.get", fake_post)
    monkeypatch.setattr(
        "app.intelligence.llm_provider.get_settings",
        lambda: Settings(ollama_allowed_model_digests={"mock-model": digest}),
    )
    provider = OllamaProvider(model_name="mock-model")
    draft = provider.generate_answer(
        "Which papers discuss retrieval augmented generation?",
        [{"chunk_id": "rag-chunk", "title": "RAG Paper", "snippet": "Retrieval augmented generation grounds answers."}],
    )

    assert draft.provider == "offline_extractive"
    assert any("Ollama model mock-model" in warning for warning in draft.warnings)


def test_citation_verifier_marks_grounded_and_missing_citations() -> None:
    retrieved = [{"chunk_id": "c1", "snippet": "Retrieval augmented generation grounds answers with citations."}]
    citations = [{"chunk_id": "c1", "paper_id": "p1", "title": "Paper", "page_start": 1, "page_end": 2, "snippet": retrieved[0]["snippet"]}]

    grounded = verify_citations("Retrieval augmented generation grounds answers with citations [c1].", retrieved, citations)
    unsupported = verify_citations("Retrieval augmented generation grounds answers.", retrieved, [])

    assert grounded["grounding_status"] == "partial"
    assert grounded["support_status"] == "support_unverified"
    assert unsupported["grounding_status"] == "unsupported"


def test_rag_answerer_returns_citations_and_persists() -> None:
    session, _engine = build_ask_session()
    try:
        response = ask_question(
            session,
            "Which papers discuss retrieval augmented generation?",
            mode="keyword",
            top_k=3,
            persist=True,
        )
        stored = session.get(RAGAnswer, response["answer_id"])
    finally:
        session.close()

    assert response["citations"]
    assert response["citations"][0]["paper_id"] == "rag-paper"
    assert response["grounding_status"] in {"grounded", "partial"}
    assert stored is not None


def test_ask_cli_requires_explicit_persistence_even_for_technical_scope(monkeypatch, capsys) -> None:
    defaults = rag_answerer_module.build_parser().parse_args(["ask", "retrieval augmented generation"])
    explicit = rag_answerer_module.build_parser().parse_args(
        ["ask", "retrieval augmented generation", "--scope", "technical", "--persist"]
    )
    assert defaults.scope == "public"
    assert defaults.persist is False
    assert explicit.scope == "technical"
    assert explicit.persist is True

    session, local_engine = build_ask_session()
    session.close()
    monkeypatch.setattr(rag_answerer_module, "engine", local_engine)
    monkeypatch.setattr(rag_answerer_module, "create_db_and_tables", lambda: None)
    monkeypatch.setattr(
        "sys.argv",
        [
            "rag_answerer",
            "ask",
            "Which papers discuss retrieval augmented generation?",
            "--scope",
            "technical",
        ],
    )

    rag_answerer_module.main()
    capsys.readouterr()
    with Session(local_engine) as verification_session:
        stored = list(verification_session.exec(select(RAGAnswer)).all())

    assert stored == []


def test_rag_answerer_supports_paper_specific_scope() -> None:
    session, _engine = build_ask_session()
    try:
        session.add(
            Paper(
                paper_id="other-paper",
                title="Other Paper",
                authors=["Ben Lee"],
                year=2024,
                corpus_eligibility_status="eligible",
            )
        )
        session.add(
            Chunk(
                chunk_id="other-chunk",
                paper_id="other-paper",
                chunk_index=0,
                page_start=4,
                page_end=5,
                section="Results",
                text="Traffic simulations describe congestion but not retrieval augmented generation.",
                word_count=8,
                source_hash="other-hash",
            )
        )
        session.commit()
        rebuild_keyword_index(session)
        response = ask_question(
            session,
            "Which papers discuss retrieval augmented generation?",
            mode="keyword",
            top_k=3,
            provider_name="offline_extractive",
            paper_id="rag-paper",
        )
    finally:
        session.close()

    assert response["paper_id"] == "rag-paper"
    assert {citation["paper_id"] for citation in response["citations"]} == {"rag-paper"}


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
            json={
                "question": "Which papers discuss retrieval augmented generation?",
                "mode": "keyword",
                "top_k": 3,
                "provider": "offline_extractive",
                "paper_id": "rag-paper",
            },
        )
        answer_id = posted.json()["answer_id"]
        fetched = client.get(f"/api/ask/{answer_id}")
        history = client.get("/api/ask/history")
        diagnostics = client.get("/api/ask/diagnostics")
    finally:
        app.dependency_overrides.clear()

    assert posted.status_code == 200
    assert posted.json()["citations"]
    assert fetched.status_code == 401
    assert history.status_code == 401
    assert diagnostics.status_code == 200
    assert diagnostics.json()["total_stored_answers"] is None
    assert diagnostics.json()["history_counts_visibility"] == "protected_reviewer_only"


def test_ask_diagnostics_follow_configured_provider_matrix() -> None:
    session, _engine = build_ask_session()
    settings = Settings(
        default_llm_provider="ollama",
        allowed_llm_providers=["offline_extractive", "ollama"],
        ollama_default_model="pinned:test",
        ollama_allowed_model_digests={"pinned:test": "a" * 64},
    )
    try:
        diagnostics = ask_diagnostics(session, settings)
    finally:
        session.close()

    assert diagnostics["default_provider"] == "ollama"
    assert diagnostics["allowed_providers"] == ["offline_extractive", "ollama"]
    assert diagnostics["provider_matrix"]["offline_extractive"]["enabled"] is True
    assert diagnostics["provider_matrix"]["ollama"]["configured_model_pinned"] is True
    assert diagnostics["provider_matrix"]["ollama"]["pinned_model_count"] == 1
    assert diagnostics["external_provider_availability_scope"] == (
        "configured_pinned_model_not_runtime_reachability"
    )


def test_public_ask_provenance_does_not_disclose_hidden_technical_corpus() -> None:
    local_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(local_engine)
    with Session(local_engine) as session:
        session.add(
            Paper(
                paper_id="hidden-technical",
                title="Hidden Technical Paper",
                corpus_eligibility_status="eligible",
                extraction_generation_id=EXTRACTION_GENERATION,
                chunk_extraction_generation_id=EXTRACTION_GENERATION,
                chunk_generation_id=CHUNK_GENERATION,
                chunk_count=1,
            )
        )
        session.add(
            Chunk(
                chunk_id="hidden-technical-c1",
                paper_id="hidden-technical",
                chunk_index=0,
                text="Retrieval augmented generation grounds answers.",
                source_hash="hidden-hash",
                extraction_generation_id=EXTRACTION_GENERATION,
            )
        )
        session.commit()
        rebuild_keyword_index(session)

    def override_session() -> Generator[Session, None, None]:
        with Session(local_engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    try:
        posted = TestClient(app).post(
            "/api/ask",
            json={
                "question": "Which papers discuss retrieval augmented generation?",
                "mode": "keyword",
                "provider": "offline_extractive",
            },
        )
    finally:
        app.dependency_overrides.clear()

    provenance = posted.json()["runtime_provenance"]
    assert posted.status_code == 200
    assert provenance["corpus_identity"]["scope"] == "public"
    assert provenance["corpus_identity"]["eligible_chunk_count"] == 0
    assert provenance["corpus_identity"]["eligible_paper_count"] == 0
    assert provenance["retrieval_identity"]["scope"] == "public"
    assert all(item["corpus_snapshot_hash"] is None for item in provenance["retrieval_identity"]["indexes"])
    assert all(item.get("index_sha256") is None for item in provenance["retrieval_identity"]["indexes"])


def test_llm_api_lists_local_models(monkeypatch) -> None:
    digest = "c" * 64
    monkeypatch.setattr(
        "app.intelligence.local_llms.list_ollama_models",
        lambda **_kwargs: (
            [
                {
                    "name": "qwen3:4b-instruct-2507-q4_K_M",
                    "installed": True,
                    "source": "ollama",
                    "digest": digest,
                }
            ],
            [],
            True,
        ),
    )
    monkeypatch.setattr(
        "app.intelligence.local_llms.get_settings",
        lambda: Settings(
            ollama_allowed_model_digests={"qwen3:4b-instruct-2507-q4_K_M": digest}
        ),
    )
    client = TestClient(app)
    response = client.get("/api/llms/local")

    assert response.status_code == 200
    assert response.json()["model_count"] == 1
    assert response.json()["models"][0]["color"] == "yellow"
    assert response.json()["models"][0]["quality_tier"] == "not_evaluated"
    warnings = " ".join(response.json()["warnings"])
    assert "no quality or hardware-fit claim" in warnings
    assert "provider is unavailable" not in warnings
    assert response.json()["candidate_pulls"] == response.json()["recommended_pulls"]
