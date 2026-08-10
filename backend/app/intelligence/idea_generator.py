from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlmodel import Session

from app.config import Settings
from app.indexing.retriever import RetrievalScope, retrieve
from app.intelligence.llm_provider import (
    OllamaProvider,
    VertexGeminiProvider,
    classify_vertex_failure,
    clean_evidence_text,
    extract_ollama_metrics,
    get_ollama_model_digest,
    trim_words,
    verify_ollama_generation_identity,
    verify_ollama_model_digest,
)
from app.intelligence.rag_answerer import assess_answerability, build_citations
from app.runtime_provenance import build_runtime_provenance

IDEA_PROMPT_TEMPLATE_VERSION = "idea-generator-v1"
MAX_HISTORY_MESSAGES = 12
MAX_HISTORY_CHARS = 6_000
MAX_SOURCES = 6
SOURCE_ALIAS_PATTERN = re.compile(r"(?<![A-Za-z0-9])\[?(S\d+)\]?(?![A-Za-z0-9])", re.IGNORECASE)
SOURCE_ALIAS_LINE_PATTERN = re.compile(
    r"^\s*(?:[-*]\s*)?(?:\*{0,2})source aliases?(?:\*{0,2})\s*:.*$",
    re.IGNORECASE | re.MULTILINE,
)


class IdeaChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2_000)

    @field_validator("content")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("chat message content must not be blank")
        return normalized


class IdeaGenerationRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2_000)
    history: list[IdeaChatMessage] = Field(default_factory=list, max_length=MAX_HISTORY_MESSAGES)

    @field_validator("message")
    @classmethod
    def normalize_message(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("message must not be blank")
        return normalized

    @model_validator(mode="after")
    def bound_history(self) -> "IdeaGenerationRequest":
        if sum(len(item.content) for item in self.history) > MAX_HISTORY_CHARS:
            raise ValueError(f"chat history may not exceed {MAX_HISTORY_CHARS} characters")
        return self


class GeneratedIdeaDraft(BaseModel):
    title: str = Field(min_length=1, max_length=180)
    research_question: str = Field(min_length=1, max_length=500)
    summary: str = Field(min_length=1, max_length=1_000)
    why_it_fits: str = Field(min_length=1, max_length=700)
    mvp_scope: str = Field(min_length=1, max_length=1_000)
    skills: list[str] = Field(min_length=1, max_length=10)
    evaluation_plan: str = Field(min_length=1, max_length=1_000)
    source_aliases: list[str] = Field(default_factory=list, max_length=MAX_SOURCES)

    @field_validator("skills", "source_aliases")
    @classmethod
    def normalize_list(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip() for value in values if value.strip()))


class IdeaModelOutput(BaseModel):
    reply: str = Field(min_length=1, max_length=2_000)
    ideas: list[GeneratedIdeaDraft] = Field(min_length=1, max_length=3)


class IdeaGenerationFailure(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.retryable = True


def utc_now() -> datetime:
    return datetime.now(UTC)


def generate_ideas(
    session: Session,
    request: IdeaGenerationRequest,
    *,
    settings: Settings,
    retrieval_scope: RetrievalScope = "public",
) -> dict[str, Any]:
    created_at = utc_now()
    retrieval_query = build_retrieval_query(request)
    retrieval = retrieve(
        session,
        retrieval_query,
        mode="keyword",
        top_k=12,
        include_text=True,
        scope=retrieval_scope,
    )
    results = list(retrieval.get("results") or [])
    answerability = assess_answerability(retrieval_query, results, paper_id=None)
    relevant_ids = set(answerability.get("relevant_chunk_ids") or [])
    matched_results = (
        [result for result in results if str(result.get("chunk_id") or "") in relevant_ids]
        if answerability.get("answerable")
        else []
    )
    source_rows, alias_to_result = build_source_rows(matched_results)
    matched_results = list(alias_to_result.values())
    prompt = build_idea_prompt(request, source_rows)
    model_output, provider_name, provider_metadata, provider_warnings = generate_strict_output(
        prompt,
        settings=settings,
    )

    response_warnings = list(retrieval.get("warnings") or []) + provider_warnings
    ideas: list[dict[str, Any]] = []
    used_aliases: list[str] = []
    reply, reply_aliases, invalid_reply_aliases = resolve_source_aliases(
        SOURCE_ALIAS_LINE_PATTERN.sub("", model_output.reply).strip(),
        alias_to_result,
    )
    used_aliases.extend(reply_aliases)
    if invalid_reply_aliases:
        response_warnings.append(
            "The model mentioned source references that were not in the retrieved evidence; those labels were replaced."
        )
    for draft in model_output.ideas:
        valid_aliases: list[str] = []
        invalid_aliases: list[str] = []
        for raw_alias in draft.source_aliases:
            alias = raw_alias.strip().upper().removeprefix("[").removesuffix("]")
            if alias in alias_to_result:
                valid_aliases.append(alias)
            else:
                invalid_aliases.append(raw_alias)

        draft_payload = draft.model_dump(exclude={"source_aliases"})
        for field in (
            "title",
            "research_question",
            "summary",
            "why_it_fits",
            "mvp_scope",
            "evaluation_plan",
        ):
            resolved, inline_aliases, invalid_inline_aliases = resolve_source_aliases(
                str(draft_payload[field]),
                alias_to_result,
            )
            draft_payload[field] = resolved
            valid_aliases.extend(inline_aliases)
            invalid_aliases.extend(invalid_inline_aliases)
        resolved_skills: list[str] = []
        for skill in draft_payload["skills"]:
            resolved, inline_aliases, invalid_inline_aliases = resolve_source_aliases(
                str(skill),
                alias_to_result,
            )
            resolved_skills.append(resolved)
            valid_aliases.extend(inline_aliases)
            invalid_aliases.extend(invalid_inline_aliases)
        draft_payload["skills"] = resolved_skills

        if invalid_aliases:
            response_warnings.append(
                "The model returned source references that were not in the retrieved evidence; those labels were replaced."
            )
        valid_aliases = list(dict.fromkeys(valid_aliases))
        used_aliases.extend(valid_aliases)
        ideas.append(
            {
                **draft_payload,
                "basis": "paper_informed" if valid_aliases else "general_suggestion",
                "source_chunk_ids": [
                    str(alias_to_result[alias].get("chunk_id") or "") for alias in valid_aliases
                ],
            }
        )

    used_aliases = list(dict.fromkeys(used_aliases))
    citation_results = [alias_to_result[alias] for alias in used_aliases]
    citations = [bounded_citation(item) for item in build_citations(citation_results)]
    if matched_results and not citations:
        response_warnings.append(
            "Relevant TTLAB papers were retrieved, but the generated ideas did not retain a valid paper reference."
        )
    if not matched_results:
        response_warnings.append(
            "No close TTLAB paper match was established; the ideas are general model-generated suggestions."
        )

    generation_metadata = {
        **provider_metadata,
        "paper_match_status": "matched" if matched_results else "none",
        "retrieved_source_count": len(matched_results),
    }
    response = {
        "message_id": str(uuid.uuid4()),
        "reply": reply,
        "paper_match_status": "matched" if matched_results else "none",
        "ideas": ideas,
        "citations": citations,
        "provider": provider_name,
        "model": str(provider_metadata["effective_model"]),
        "generation_metadata": generation_metadata,
        "warnings": dedupe(response_warnings),
        "created_at": created_at.isoformat(),
    }
    response["runtime_provenance"] = build_runtime_provenance(
        session,
        record_type="idea_generation_message",
        generation_config={
            "prompt_template_version": IDEA_PROMPT_TEMPLATE_VERSION,
            "history_message_limit": MAX_HISTORY_MESSAGES,
            "history_character_limit": MAX_HISTORY_CHARS,
            "source_limit": MAX_SOURCES,
            "output_schema": "idea_model_output_v1",
            "provider_policy": "strict_structured_generation_no_fallback",
        },
        provider=provider_name,
        model=response["model"],
        generated_at=created_at,
        retrieval_mode="keyword",
        source_chunk_ids=[str(item.get("chunk_id") or "") for item in matched_results],
        generation_metadata=generation_metadata,
        retrieval_metadata={
            "retrieval_scope": retrieval_scope,
            "retrieval_strategy": retrieval.get("retrieval_strategy"),
            "retriever_config": retrieval.get("retriever_config", {}),
            "vector_provider": retrieval.get("vector_provider"),
            "answerability_reason": answerability.get("reason"),
        },
        corpus_scope=retrieval_scope,
    )
    return response


def build_retrieval_query(request: IdeaGenerationRequest) -> str:
    recent_user_turns = [
        item.content for item in request.history if item.role == "user"
    ][-3:]
    parts = [*recent_user_turns, request.message]
    return " ".join(dict.fromkeys(part for part in parts if part)).strip()


def build_source_rows(
    results: list[dict[str, Any]],
) -> tuple[list[dict[str, str]], dict[str, dict[str, Any]]]:
    rows: list[dict[str, str]] = []
    aliases: dict[str, dict[str, Any]] = {}
    seen_papers: set[str] = set()
    for result in results:
        paper_key = str(
            result.get("paper_id") or result.get("paper_title") or result.get("chunk_id") or ""
        ).strip()
        if paper_key in seen_papers:
            continue
        seen_papers.add(paper_key)
        index = len(rows) + 1
        alias = f"S{index}"
        aliases[alias] = result
        rows.append(
            {
                "alias": alias,
                "paper": clean_evidence_text(str(result.get("paper_title") or "Untitled paper")),
                "authors": ", ".join(str(value) for value in result.get("authors", []) if str(value).strip()),
                "year": str(result.get("year") or "unknown"),
                "section": clean_evidence_text(str(result.get("section") or "Unknown section")),
                "pages": f"{result.get('page_start') or '?'}-{result.get('page_end') or '?'}",
                "evidence": trim_words(
                    clean_evidence_text(str(result.get("text") or result.get("snippet") or "")),
                    max_words=90,
                ),
            }
        )
        if len(rows) >= MAX_SOURCES:
            break
    return rows, aliases


def resolve_source_aliases(
    text: str,
    alias_to_result: dict[str, dict[str, Any]],
) -> tuple[str, list[str], list[str]]:
    valid_aliases: list[str] = []
    invalid_aliases: list[str] = []

    def replace(match: re.Match[str]) -> str:
        alias = match.group(1).upper()
        result = alias_to_result.get(alias)
        if result is None:
            invalid_aliases.append(alias)
            return "an unverified retrieved source"
        valid_aliases.append(alias)
        title = clean_evidence_text(str(result.get("paper_title") or "Untitled paper"))
        return f"“{title}”"

    resolved = SOURCE_ALIAS_PATTERN.sub(replace, text)
    return resolved, list(dict.fromkeys(valid_aliases)), list(dict.fromkeys(invalid_aliases))


def build_idea_prompt(request: IdeaGenerationRequest, sources: list[dict[str, str]]) -> str:
    conversation = "\n".join(
        f"{item.role.upper()}: {item.content}" for item in request.history[-MAX_HISTORY_MESSAGES:]
    )
    source_text = "\n\n".join(
        (
            f"[{item['alias']}] Paper: {item['paper']} ({item['year']})\n"
            f"Authors: {item['authors'] or 'not listed'}\n"
            f"Section/pages: {item['section']}; {item['pages']}\n"
            f"Evidence: {item['evidence']}"
        )
        for item in sources
    )
    source_instruction = (
        "Relevant TTLAB sources are supplied below. Use them only as background or inspiration. "
        "At least one idea should reference an applicable source alias in source_aliases."
        if sources
        else "No close TTLAB paper match was found. Generate useful general thesis directions and leave every source_aliases list empty."
    )
    schema = json.dumps(IdeaModelOutput.model_json_schema(), separators=(",", ":"))
    return (
        "You are the TTLAB Thesis Idea Generator, a supportive research-idea coach for students.\n"
        "Always provide between one and three concrete thesis ideas in this response. Do not respond with only a question.\n"
        "Keep reply to one to three conversational sentences and do not repeat the structured idea fields there; the ideas array contains the detail.\n"
        "If the student's request is vague, give useful starter ideas first and include at most one focused follow-up question in reply.\n"
        "Treat every proposed topic as a candidate direction requiring literature review and supervisor approval. Never claim novelty, guaranteed feasibility, or supervisor endorsement.\n"
        "Clearly separate what a supplied paper studied from what you are newly suggesting. Never invent a source alias.\n"
        "Source aliases such as S1 are machine-readable identifiers only. Put them only in source_aliases; never show S1-style labels in reply or any student-facing idea text. Refer to papers by title in prose.\n"
        "Each idea must contain an actionable MVP, useful skills, and a realistic evaluation method.\n"
        f"{source_instruction}\n"
        "Return only JSON matching the supplied schema.\n\n"
        f"Conversation so far:\n{conversation or '(first turn)'}\n\n"
        f"Current student message:\n{request.message}\n\n"
        f"TTLAB source context:\n{source_text or '(none)'}\n\n"
        f"JSON schema:\n{schema}"
    )


def generate_strict_output(
    prompt: str,
    *,
    settings: Settings,
) -> tuple[IdeaModelOutput, str, dict[str, Any], list[str]]:
    provider_name = settings.default_llm_provider.strip().lower()
    if provider_name == "vertex_gemini":
        return generate_strict_vertex_output(prompt, settings=settings)
    if "ollama" in {value.strip().lower() for value in settings.allowed_llm_providers}:
        provider_name = "ollama"
    if provider_name != "ollama":
        raise IdeaGenerationFailure(
            "generation_provider_unavailable",
            "Conversational idea generation requires an enabled structured-generation provider.",
            status_code=503,
        )
    output, metadata, warnings = generate_strict_ollama_output(prompt, settings=settings)
    return output, "ollama", metadata, warnings


def generate_strict_vertex_output(
    prompt: str,
    *,
    settings: Settings,
) -> tuple[IdeaModelOutput, str, dict[str, Any], list[str]]:
    # Vertex receives the Pydantic class via response_schema; duplicating the
    # JSON schema in prompt text can reduce structured-output quality.
    prompt = prompt.rsplit("\n\nJSON schema:\n", 1)[0]
    try:
        provider = VertexGeminiProvider(
            requested_provider="vertex_gemini",
            configured_provider="vertex_gemini",
            settings=settings,
        )
    except (ValueError, RuntimeError, OSError) as exc:
        raise IdeaGenerationFailure(
            "generation_provider_unavailable",
            "Google Gemini on Vertex AI is not configured or available.",
            status_code=503,
        ) from exc
    for attempt in range(2):
        active_prompt = prompt
        if attempt:
            active_prompt += (
                "\n\nThe previous output was invalid. Return a fresh complete response matching the configured schema."
            )
        try:
            output, metadata = provider.generate_structured(active_prompt, IdeaModelOutput)
            # Deliberately validate a second time at the application boundary.
            validated = IdeaModelOutput.model_validate(output.model_dump())
            metadata["structured_output_schema"] = "idea_model_output_v1"
            metadata["structured_output_repair_attempted"] = bool(attempt)
            return validated, "vertex_gemini", metadata, []
        except ValueError:
            continue
        except Exception as exc:
            reason = classify_vertex_failure(exc)
            if reason == "vertex_invalid_response":
                continue
            raise IdeaGenerationFailure(
                "generation_provider_unavailable",
                "Google Gemini on Vertex AI could not generate ideas. Retry after the managed provider recovers.",
                status_code=503,
            ) from exc
    raise IdeaGenerationFailure(
        "generation_invalid_output",
        "The generation provider returned an invalid idea format twice. Retry the request.",
        status_code=502,
    )


def generate_strict_ollama_output(
    prompt: str,
    *,
    settings: Settings,
) -> tuple[IdeaModelOutput, dict[str, Any], list[str]]:
    try:
        provider = OllamaProvider(
            requested_provider="ollama",
            configured_provider="ollama",
            settings=settings,
        )
    except (ValueError, OSError) as exc:
        raise IdeaGenerationFailure(
            "generation_provider_unavailable",
            "The approved local generation provider is not available. Start it or enable and pin an installed model, then retry.",
            status_code=503,
        ) from exc

    schema = IdeaModelOutput.model_json_schema()
    repair_attempted = False
    for attempt in range(2):
        active_prompt = prompt
        if attempt:
            repair_attempted = True
            active_prompt = (
                prompt
                + "\n\nYour previous response did not validate. Generate a fresh response that exactly matches the JSON schema, with one to three complete ideas and no surrounding prose."
            )
        try:
            raw, metadata, warnings = call_strict_ollama(provider, active_prompt, schema)
        except httpx.HTTPError as exc:
            raise IdeaGenerationFailure(
                "generation_provider_unavailable",
                "The local generation provider could not generate a response. Check the service and retry.",
                status_code=503,
            ) from exc
        except ValueError as exc:
            if "identity" in str(exc).lower() or "digest" in str(exc).lower() or "installed" in str(exc).lower():
                raise IdeaGenerationFailure(
                    "generation_provider_unavailable",
                    "The local model identity could not be verified. Recheck the pinned model and retry.",
                    status_code=503,
                ) from exc
            raw = ""
            metadata = {}
            warnings = []
        try:
            output = IdeaModelOutput.model_validate_json(raw)
            metadata["structured_output_schema"] = "idea_model_output_v1"
            metadata["structured_output_repair_attempted"] = repair_attempted
            return output, metadata, warnings
        except (ValueError, json.JSONDecodeError):
            continue
    raise IdeaGenerationFailure(
        "generation_invalid_output",
        "The generation provider returned an invalid idea format twice. Retry the request.",
        status_code=502,
    )


def call_strict_ollama(
    provider: OllamaProvider,
    prompt: str,
    schema: dict[str, Any],
) -> tuple[str, dict[str, Any], list[str]]:
    preflight_digest = (
        verify_ollama_model_digest(
            provider.base_url,
            provider.model,
            provider.expected_digest,
            timeout=min(provider.timeout, 5.0),
        )
        if provider.expected_digest
        else get_ollama_model_digest(
            provider.base_url,
            provider.model,
            timeout=min(provider.timeout, 5.0),
        )
    )
    options = {
        "temperature": 0.3,
        "top_p": 0.9,
        "num_ctx": provider.num_ctx,
        "num_predict": 1_200,
    }
    payload = {
        "model": provider.model,
        "prompt": prompt,
        "format": schema,
        "stream": False,
        "keep_alive": provider.keep_alive,
        "options": options,
    }
    response = httpx.post(
        f"{provider.base_url}/api/generate",
        json=payload,
        timeout=provider.timeout,
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("Ollama returned a non-object idea response")
    identity = verify_ollama_generation_identity(
        data,
        configured_model=provider.model,
        expected_digest=preflight_digest,
    )
    postflight_digest = (
        verify_ollama_model_digest(
            provider.base_url,
            provider.model,
            provider.expected_digest,
            timeout=min(provider.timeout, 5.0),
        )
        if provider.expected_digest
        else get_ollama_model_digest(
            provider.base_url,
            provider.model,
            timeout=min(provider.timeout, 5.0),
        )
    )
    if postflight_digest != preflight_digest:
        raise ValueError("Ollama model identity changed during idea generation")
    output = str(data.get("response") or "").strip()
    if not output:
        raise ValueError("Ollama returned an empty idea response")
    digest_attested = bool(identity["generation_time_digest_verified"])
    effective_model = (
        f"{provider.model}@sha256:{preflight_digest}" if digest_attested else provider.model
    )
    warnings: list[str] = []
    if not digest_attested:
        warnings.append(
            "The Ollama tag was stable before and after generation, but the response did not report a digest; generation-time model identity is not fully attested."
        )
    prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    config_hash = hashlib.sha256(
        json.dumps(options, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return output, {
        "effective_model": effective_model,
        "configured_model_digest": (
            f"sha256:{provider.expected_digest}" if provider.expected_digest else None
        ),
        "observed_model_digest": f"sha256:{preflight_digest}",
        "preflight_model_digest": f"sha256:{preflight_digest}",
        "postflight_model_digest": f"sha256:{postflight_digest}",
        "generation_time_digest_verified": digest_attested,
        "tag_stable_across_generation": True,
        "ollama_response_identity": identity,
        "ollama_metrics": extract_ollama_metrics(data),
        "prompt_template_version": IDEA_PROMPT_TEMPLATE_VERSION,
        "prompt_sha256": prompt_hash,
        "generation_config_sha256": config_hash,
        "provider_resolution": provider.resolution_metadata(
            effective_model=effective_model,
            generation_time_digest_verified=digest_attested,
            tag_stable_across_generation=True,
            observed_digest=preflight_digest,
        ),
    }, warnings


def bounded_citation(citation: dict[str, Any]) -> dict[str, Any]:
    value = dict(citation)
    snippet = " ".join(str(value.get("snippet") or "").split())
    value["snippet"] = snippet if len(snippet) <= 700 else snippet[:699].rstrip() + "…"
    return value


def dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
