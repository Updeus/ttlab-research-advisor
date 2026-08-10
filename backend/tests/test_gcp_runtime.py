from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.ask import AskRequest, ask
from app.api.llms import generation_status
from app.config import Settings
from app.intelligence.idea_generator import IdeaModelOutput, generate_strict_vertex_output
from app.intelligence.llm_provider import (
    OfflineExtractiveProvider,
    VertexGeminiProvider,
    classify_vertex_failure,
    get_provider,
)
from app.storage import publish_gcs_vector_generation


def gcp_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "runtime_profile": "gcp",
        "database_url": "postgresql+pg8000://",
        "cloud_sql_instance": "project:us-east1:advisor",
        "cloud_sql_iam_user": "advisor-api@project.iam",
        "google_cloud_project": "project",
        "storage_backend": "gcs",
        "gcs_bucket": "private-bucket",
        "security_mode": "production",
        "public_base_url": "https://advisor.example",
        "trusted_hosts": ["advisor.example"],
        "cors_origins": ["https://advisor.example"],
        "default_llm_provider": "vertex_gemini",
        "allowed_llm_providers": ["vertex_gemini"],
        "public_provider_selection": False,
        "rate_limit_hash_salt": "a" * 32,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_gcp_profile_is_explicit_and_fail_closed() -> None:
    settings = gcp_settings()
    assert settings.is_gcp
    assert settings.default_llm_provider == "vertex_gemini"
    with pytest.raises(ValueError, match="cannot use SQLite"):
        gcp_settings(database_url="sqlite:///data/papers.db")
    with pytest.raises(ValueError, match="PUBLIC_PROVIDER_SELECTION"):
        gcp_settings(public_provider_selection=True)


def test_provider_resolution_selects_allowlisted_vertex_model() -> None:
    provider = get_provider("auto", settings=gcp_settings())
    assert isinstance(provider, VertexGeminiProvider)
    assert provider.model == "gemini-3.5-flash"
    with pytest.raises(ValueError, match="allowlisted"):
        get_provider("vertex_gemini", "gemini-unapproved", settings=gcp_settings())


def test_generation_status_identifies_local_structured_provider() -> None:
    status = generation_status(Settings(_env_file=None))
    assert status["provider"] == "ollama"
    assert status["display_name"] == "Local Ollama"


def test_vertex_failure_uses_recorded_offline_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = VertexGeminiProvider(settings=gcp_settings())

    class FailingModels:
        @staticmethod
        def generate_content(**_kwargs: object) -> object:
            raise TimeoutError("deadline exceeded")

    client = SimpleNamespace(models=FailingModels(), close=lambda: None)
    types = SimpleNamespace(GenerateContentConfig=lambda **kwargs: kwargs)
    monkeypatch.setattr(provider, "_client", lambda: (client, types))
    draft = provider.generate_answer(
        "What does this paper show?",
        [{"chunk_id": "c1", "title": "Paper", "text": "The paper evaluates retrieval quality."}],
    )
    assert isinstance(draft.provider, str)
    assert draft.provider == OfflineExtractiveProvider.provider
    resolution = draft.prompt_metadata["provider_resolution"]
    assert resolution["fallback_reason"] == "vertex_timeout"
    assert draft.prompt_metadata["attempted_provider"] == "vertex_gemini"


def test_vertex_safety_block_uses_recorded_offline_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = VertexGeminiProvider(settings=gcp_settings())
    response = SimpleNamespace(
        text="",
        response_id="response-1",
        model_version="gemini-version",
        usage_metadata=None,
        prompt_feedback=None,
        candidates=[
            SimpleNamespace(
                finish_reason="SAFETY",
                safety_ratings=[SimpleNamespace(category="HARM", probability="HIGH", blocked=True)],
            )
        ],
    )
    client = SimpleNamespace(
        models=SimpleNamespace(generate_content=lambda **_kwargs: response),
        close=lambda: None,
    )
    types = SimpleNamespace(GenerateContentConfig=lambda **kwargs: kwargs)
    monkeypatch.setattr(provider, "_client", lambda: (client, types))
    draft = provider.generate_answer(
        "What is supported?",
        [{"chunk_id": "c1", "title": "Paper", "text": "The paper reports a result."}],
    )
    assert draft.prompt_metadata["provider_resolution"]["fallback_reason"] == "vertex_safety_block"
    assert draft.prompt_metadata["response_id"] == "response-1"


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (RuntimeError("429 quota exhausted"), "vertex_quota_exhausted"),
        (RuntimeError("upstream unavailable"), "vertex_service_unavailable"),
        (ValueError("malformed response"), "vertex_invalid_response"),
    ],
)
def test_vertex_failure_classification(error: Exception, reason: str) -> None:
    assert classify_vertex_failure(error) == reason


def test_gcp_public_ask_rejects_provider_and_model_overrides() -> None:
    with pytest.raises(HTTPException) as exc_info:
        ask(
            AskRequest(question="Which papers discuss RAG?", provider="vertex_gemini"),
            None,  # type: ignore[arg-type]
            gcp_settings(),
        )
    assert exc_info.value.status_code == 400

    with pytest.raises(HTTPException):
        ask(
            AskRequest(question="Which papers discuss RAG?", provider="auto", model="gemini-3.5-flash"),
            None,  # type: ignore[arg-type]
            gcp_settings(),
        )


def test_vertex_structured_generation_revalidates_application_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = IdeaModelOutput.model_validate(
        {
            "reply": "Here is a bounded candidate direction.",
            "ideas": [
                {
                    "title": "Evaluate a small research assistant",
                    "research_question": "How useful is grounded retrieval for students?",
                    "summary": "Build and evaluate one bounded workflow.",
                    "why_it_fits": "It matches Python and web-development skills.",
                    "mvp_scope": "One corpus, one workflow, and one evaluation set.",
                    "skills": ["Python"],
                    "evaluation_plan": "Measure retrieval and usefulness on held-out questions.",
                    "source_aliases": [],
                }
            ],
        }
    )

    def fake_generate(self: VertexGeminiProvider, prompt: str, schema: type[object]):
        assert "JSON schema:" not in prompt
        assert schema is IdeaModelOutput
        return output, {"effective_model": self.model}

    monkeypatch.setattr(VertexGeminiProvider, "generate_structured", fake_generate)
    validated, provider, metadata, warnings = generate_strict_vertex_output(
        "Prompt body\n\nJSON schema:\n{}",
        settings=gcp_settings(),
    )
    assert validated == output
    assert provider == "vertex_gemini"
    assert metadata["structured_output_schema"] == "idea_model_output_v1"
    assert warnings == []


def test_gcs_vector_publication_advances_pointer_last(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "feature_hashing_embeddings.json"
    generation = tmp_path / "feature_hashing_embeddings.json.generations" / "generation-1"
    generation.mkdir(parents=True)
    index_payload = b'{"records":[]}'
    manifest_payload = b'{"corpus":{"snapshot_hash":"abc"}}'
    (generation / "index.json").write_bytes(index_payload)
    (generation / "manifest.json").write_bytes(manifest_payload)
    pointer = {
        "pointer_type": "ttlab_vector_index_current_generation",
        "build_id": "build-1",
        "index_path": "feature_hashing_embeddings.json.generations/generation-1/index.json",
        "manifest_path": "feature_hashing_embeddings.json.generations/generation-1/manifest.json",
        "index_sha256": hashlib.sha256(index_payload).hexdigest(),
        "manifest_sha256": hashlib.sha256(manifest_payload).hexdigest(),
    }
    (tmp_path / "feature_hashing_embeddings.json.current.json").write_text(
        json.dumps(pointer), encoding="utf-8"
    )

    writes: list[str] = []

    class Store:
        def write_bytes(self, uri: str, _payload: bytes, *, content_type: str | None = None) -> None:
            assert content_type == "application/json"
            writes.append(uri)

    monkeypatch.setattr("app.storage.object_store", lambda _settings: Store())
    result = publish_gcs_vector_generation(
        index_path,
        Settings(_env_file=None, storage_backend="gcs", gcs_bucket="bucket"),
    )
    assert writes[-1].endswith("feature_hashing_embeddings.json.current.json")
    assert result["build_id"] == "build-1"
