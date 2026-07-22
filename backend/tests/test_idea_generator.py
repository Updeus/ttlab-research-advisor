from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlmodel import select

from app.config import Settings, get_settings
from app.db import get_session
from app.intelligence import idea_generator as idea_generator_module
from app.intelligence.idea_generator import (
    GeneratedIdeaDraft,
    IdeaGenerationFailure,
    IdeaGenerationRequest,
    IdeaModelOutput,
    generate_ideas,
    generate_strict_ollama_output,
)
from app.models import ThesisRecommendation
from app.main import app
from test_extension_recommender import build_extension_session


def model_output(*, source_aliases: list[str] | None = None) -> IdeaModelOutput:
    return IdeaModelOutput(
        reply="Here are two concrete directions. Start with the smaller MVP and validate the topic with a supervisor.",
        ideas=[
            GeneratedIdeaDraft(
                title="Student-focused RAG evaluation assistant",
                research_question="How can source-cited feedback improve student research discovery?",
                summary="Build and study a small assistant that helps students inspect retrieved evidence.",
                why_it_fits="It combines Python, web development, and research discovery.",
                mvp_scope="Implement retrieval, a cited response view, and a small question set.",
                skills=["Python", "FastAPI"],
                evaluation_plan="Measure retrieval recall and conduct a small usefulness review.",
                source_aliases=source_aliases or [],
            )
        ],
    )


def provider_metadata() -> dict[str, object]:
    return {
        "effective_model": "test-model@sha256:" + "a" * 64,
        "prompt_template_version": "idea-generator-v1",
        "prompt_sha256": "b" * 64,
        "generation_config_sha256": "c" * 64,
        "provider_resolution": {
            "requested_provider": "ollama",
            "configured_provider": "ollama",
            "effective_provider": "ollama",
            "effective_model": "test-model@sha256:" + "a" * 64,
            "fallback_used": False,
        },
    }


def test_request_bounds_and_normalizes_page_session_history() -> None:
    request = IdeaGenerationRequest(
        message="  Help me find an agriculture project.  ",
        history=[{"role": "user", "content": "  I know Python.  "}],
    )

    assert request.message == "Help me find an agriculture project."
    assert request.history[0].content == "I know Python."
    with pytest.raises(ValidationError):
        IdeaGenerationRequest(
            message="ideas",
            history=[{"role": "user", "content": "x" * 1_000} for _ in range(7)],
        )


def test_matching_paper_produces_server_validated_paper_informed_idea(monkeypatch) -> None:
    session, _engine = build_extension_session()
    try:
        monkeypatch.setattr(
            idea_generator_module,
            "generate_strict_ollama_output",
            lambda *_args, **_kwargs: (model_output(source_aliases=["S1", "invented"]), provider_metadata(), []),
        )

        before = len(session.exec(select(ThesisRecommendation)).all())
        response = generate_ideas(
            session,
            IdeaGenerationRequest(message="I know Python and want a RAG research discovery web app."),
            settings=Settings(),
        )
        after = len(session.exec(select(ThesisRecommendation)).all())

        assert response["paper_match_status"] == "matched"
        assert response["provider"] == "ollama"
        assert response["ideas"][0]["basis"] == "paper_informed"
        assert response["ideas"][0]["source_chunk_ids"]
        assert response["citations"][0]["paper_id"] == "rag-platform"
        assert any("references" in warning for warning in response["warnings"])
        assert before == after == 0
    finally:
        session.close()


def test_internal_source_aliases_are_resolved_to_paper_titles(monkeypatch) -> None:
    session, _engine = build_extension_session()
    output = model_output()
    output.reply = "S1 is useful background, but do not treat [S99] as evidence.\n* **Source Aliases:** S1"
    output.ideas[0].summary = "Extend the approach in S1 with a smaller student-facing prototype."
    output.ideas[0].why_it_fits = "It combines the evidence in [S1] with web development."

    try:
        monkeypatch.setattr(
            idea_generator_module,
            "generate_strict_ollama_output",
            lambda *_args, **_kwargs: (output, provider_metadata(), []),
        )

        response = generate_ideas(
            session,
            IdeaGenerationRequest(message="I know Python and want a RAG research discovery web app."),
            settings=Settings(),
        )

        paper_title = response["citations"][0]["title"]
        student_text = " ".join(
            [
                response["reply"],
                response["ideas"][0]["summary"],
                response["ideas"][0]["why_it_fits"],
            ]
        )
        assert paper_title in student_text
        assert "S1" not in student_text
        assert "S99" not in student_text
        assert "Source Aliases" not in student_text
        assert "an unverified retrieved source" in student_text
        assert response["ideas"][0]["basis"] == "paper_informed"
        assert any("labels were replaced" in warning for warning in response["warnings"])
    finally:
        session.close()


def test_no_paper_match_still_invokes_ollama_and_returns_general_idea(monkeypatch) -> None:
    session, _engine = build_extension_session()
    captured: dict[str, str] = {}

    def fake_generate(prompt: str, **_kwargs):
        captured["prompt"] = prompt
        return model_output(), provider_metadata(), []

    try:
        monkeypatch.setattr(
            idea_generator_module,
            "retrieve",
            lambda *_args, **_kwargs: {
                "results": [],
                "warnings": [],
                "retrieval_strategy": "test",
                "retriever_config": {},
                "vector_provider": None,
            },
        )
        monkeypatch.setattr(idea_generator_module, "generate_strict_ollama_output", fake_generate)

        response = generate_ideas(
            session,
            IdeaGenerationRequest(
                message="I want to study marine archaeology.",
                history=[{"role": "user", "content": "I have one semester."}],
            ),
            settings=Settings(),
        )

        assert response["paper_match_status"] == "none"
        assert response["ideas"][0]["basis"] == "general_suggestion"
        assert response["citations"] == []
        assert "No close TTLAB paper match was found" in captured["prompt"]
        assert "I have one semester" in captured["prompt"]
        assert any("general model-generated" in warning for warning in response["warnings"])
    finally:
        session.close()


def test_strict_generator_never_falls_back_when_ollama_policy_is_unavailable(monkeypatch) -> None:
    class UnavailableProvider:
        def __init__(self, **_kwargs) -> None:
            raise ValueError("model is not enabled")

    monkeypatch.setattr(idea_generator_module, "OllamaProvider", UnavailableProvider)

    with pytest.raises(IdeaGenerationFailure) as exc_info:
        generate_strict_ollama_output("prompt", settings=Settings())

    assert exc_info.value.code == "ollama_unavailable"
    assert exc_info.value.status_code == 503


def test_prompt_requires_actionable_ideas_even_for_vague_requests(monkeypatch) -> None:
    session, _engine = build_extension_session()
    captured: dict[str, str] = {}

    def fake_generate(prompt: str, **_kwargs):
        captured["prompt"] = prompt
        return model_output(), provider_metadata(), []

    try:
        monkeypatch.setattr(idea_generator_module, "generate_strict_ollama_output", fake_generate)
        generate_ideas(
            session,
            IdeaGenerationRequest(message="I am not sure what to study."),
            settings=Settings(),
        )

        assert "Do not respond with only a question" in captured["prompt"]
        assert "between one and three concrete thesis ideas" in captured["prompt"]
        assert "Never claim novelty" in captured["prompt"]
        assert "machine-readable identifiers only" in captured["prompt"]
    finally:
        session.close()


def test_public_api_returns_stable_retryable_ollama_error(monkeypatch) -> None:
    session, _engine = build_extension_session()

    def override_session() -> Generator:
        yield session

    def fail_generation(*_args, **_kwargs):
        raise IdeaGenerationFailure(
            "ollama_unavailable",
            "Ollama could not generate a response.",
            status_code=503,
        )

    monkeypatch.setattr("app.features.feature_for_path", lambda _path: None)
    monkeypatch.setattr("app.api.recommendations.generate_ideas", fail_generation)
    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_settings] = lambda: Settings(
        allowed_llm_providers=["ollama"],
    )
    try:
        response = TestClient(app).post(
            "/api/recommendations/ideas",
            json={"message": "Help me choose a thesis topic.", "history": []},
        )
    finally:
        app.dependency_overrides.clear()
        session.close()

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "code": "ollama_unavailable",
        "message": "Ollama could not generate a response.",
        "retryable": True,
    }
