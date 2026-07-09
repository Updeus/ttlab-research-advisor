from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from app.config import get_settings


@dataclass
class LLMAnswerDraft:
    answer_text: str
    provider: str
    model: str
    prompt_metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


class LLMProvider(Protocol):
    provider: str
    model: str

    def generate_answer(
        self,
        question: str,
        context_chunks: list[dict[str, Any]],
        audience: str = "general",
        max_words: int = 250,
    ) -> LLMAnswerDraft:
        ...


class OfflineExtractiveProvider:
    provider = "offline_extractive"
    model = "sentence-overlap-v1"

    def generate_answer(
        self,
        question: str,
        context_chunks: list[dict[str, Any]],
        audience: str = "general",
        max_words: int = 250,
    ) -> LLMAnswerDraft:
        if not context_chunks:
            return LLMAnswerDraft(
                answer_text="I could not answer this from the indexed TTLAB paper chunks.",
                provider=self.provider,
                model=self.model,
                warnings=["No retrieved chunks were supplied to the offline extractive provider."],
            )
        question_terms = set(tokenize(question))
        selected: list[str] = []
        paper_titles = []
        for chunk in context_chunks:
            title = str(chunk.get("title") or "").strip()
            if title and title not in paper_titles:
                paper_titles.append(title)
            sentences = split_sentences(clean_markup(str(chunk.get("snippet") or chunk.get("text") or "")))
            ranked = sorted(
                sentences,
                key=lambda sentence: lexical_overlap(question_terms, set(tokenize(sentence))),
                reverse=True,
            )
            for sentence in ranked[:2]:
                if sentence and sentence not in selected:
                    selected.append(sentence)
                if len(" ".join(selected).split()) >= max_words:
                    break
            if len(" ".join(selected).split()) >= max_words:
                break
        if not selected:
            selected = [clean_markup(str(context_chunks[0].get("snippet") or "")).strip()]
        answer_body = trim_words(" ".join(selected), max_words=max_words)
        if question.lower().strip().startswith(("which paper", "which ttlab paper", "what paper")) and paper_titles:
            title_list = "; ".join(paper_titles[:4])
            answer = f"Based on the indexed TTLAB paper chunks, the strongest retrieved source papers are: {title_list}. Relevant evidence: {answer_body}"
        else:
            answer = f"Based on the indexed TTLAB paper chunks, {answer_body}"
        return LLMAnswerDraft(
            answer_text=answer,
            provider=self.provider,
            model=self.model,
            prompt_metadata={"audience": audience, "context_chunk_count": len(context_chunks), "max_words": max_words},
            warnings=[],
        )


class OllamaProvider:
    provider = "ollama"

    def __init__(self, model_name: str | None = None) -> None:
        settings = get_settings()
        self.base_url = settings.ollama_base_url.rstrip("/")
        self.model = model_name or settings.ollama_default_model
        self.timeout = settings.ollama_timeout_seconds
        self.num_ctx = settings.ollama_num_ctx
        self.keep_alive = settings.ollama_keep_alive

    def generate_answer(
        self,
        question: str,
        context_chunks: list[dict[str, Any]],
        audience: str = "general",
        max_words: int = 250,
    ) -> LLMAnswerDraft:
        if not context_chunks:
            return OfflineExtractiveProvider().generate_answer(question, context_chunks, audience, max_words)
        prompt = build_ollama_prompt(question, context_chunks, audience=audience, max_words=max_words)
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "keep_alive": self.keep_alive,
            "options": {
                "temperature": 0.1,
                "top_p": 0.9,
                "num_ctx": self.num_ctx,
                "num_predict": max(120, min(max_words * 2, 700)),
            },
        }
        try:
            response = httpx.post(f"{self.base_url}/api/generate", json=payload, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()
            answer = clean_markup(str(data.get("response") or "")).strip()
            if not answer:
                raise ValueError("Ollama returned an empty response.")
            return LLMAnswerDraft(
                answer_text=answer,
                provider=self.provider,
                model=str(data.get("model") or self.model),
                prompt_metadata={
                    "audience": audience,
                    "context_chunk_count": len(context_chunks),
                    "max_words": max_words,
                    "ollama_metrics": extract_ollama_metrics(data),
                },
                warnings=[],
            )
        except Exception as exc:
            fallback = OfflineExtractiveProvider().generate_answer(question, context_chunks, audience, max_words)
            fallback.warnings.append(
                f"Ollama model {self.model} was unavailable or failed; used offline extractive fallback. Reason: {exc}"
            )
            return fallback


class OptionalOpenAIProvider:
    provider = "openai"
    model = "not-configured"

    def __init__(self) -> None:
        self.api_key = os.getenv("OPENAI_API_KEY")
        self.model = os.getenv("TTLAB_OPENAI_MODEL", "gpt-4.1-mini")

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def generate_answer(
        self,
        question: str,
        context_chunks: list[dict[str, Any]],
        audience: str = "general",
        max_words: int = 250,
    ) -> LLMAnswerDraft:
        if not self.available:
            return OfflineExtractiveProvider().generate_answer(question, context_chunks, audience, max_words)
        return LLMAnswerDraft(
            answer_text="External OpenAI answer generation is configured but not enabled in this Phase 4 adapter.",
            provider=self.provider,
            model=self.model,
            warnings=["OpenAI adapter is a non-required stub; offline extractive provider remains the supported default."],
        )


def get_provider(provider_name: str = "auto", model_name: str | None = None) -> LLMProvider:
    if provider_name in {"auto", "offline_extractive", "extractive_mock"}:
        if provider_name == "auto" and os.getenv("TTLAB_DEFAULT_LLM_PROVIDER", "offline_extractive") == "ollama":
            return OllamaProvider(model_name=model_name)
        if provider_name == "auto" and OptionalOpenAIProvider().available:
            return OptionalOpenAIProvider()
        return OfflineExtractiveProvider()
    if provider_name == "ollama":
        return OllamaProvider(model_name=model_name)
    if provider_name == "openai":
        openai = OptionalOpenAIProvider()
        return openai if openai.available else OfflineExtractiveProvider()
    raise ValueError(f"Unknown LLM provider: {provider_name}")


def external_provider_available() -> bool:
    return OptionalOpenAIProvider().available


def build_ollama_prompt(
    question: str,
    context_chunks: list[dict[str, Any]],
    *,
    audience: str,
    max_words: int,
) -> str:
    compact_chunks = []
    for index, chunk in enumerate(context_chunks[:8], start=1):
        chunk_id = str(chunk.get("chunk_id") or f"chunk-{index}")
        title = clean_markup(str(chunk.get("title") or "Untitled paper"))
        section = clean_markup(str(chunk.get("section") or "Unknown section"))
        page_start = chunk.get("page_start") or "?"
        page_end = chunk.get("page_end") or "?"
        snippet = trim_words(clean_markup(str(chunk.get("snippet") or chunk.get("text") or "")), max_words=95)
        compact_chunks.append(
            f"[{chunk_id}] Paper: {title}\nSection: {section}; pages {page_start}-{page_end}\nEvidence: {snippet}"
        )
    context = "\n\n".join(compact_chunks)
    return (
        "You are Ask TTLAB, a source-grounded research assistant.\n"
        "Answer only from the provided TTLAB paper chunks. Do not add outside facts.\n"
        "If the chunks do not support an answer, say that the indexed chunks do not contain enough evidence.\n"
        "Cite chunk IDs inline using square brackets, for example [paper-chunk-0001].\n"
        f"Audience: {audience}. Keep the answer under {max_words} words.\n\n"
        f"Source chunks:\n{context}\n\n"
        f"Question: {question}\n\n"
        "Answer:"
    )


def extract_ollama_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    for key in [
        "total_duration",
        "load_duration",
        "prompt_eval_count",
        "prompt_eval_duration",
        "eval_count",
        "eval_duration",
    ]:
        metrics[key] = payload.get(key)
    eval_count = float(payload.get("eval_count") or 0)
    eval_duration = float(payload.get("eval_duration") or 0)
    if eval_count and eval_duration:
        metrics["tokens_per_second"] = round(eval_count / (eval_duration / 1_000_000_000), 2)
    else:
        metrics["tokens_per_second"] = None
    total_duration = float(payload.get("total_duration") or 0)
    metrics["total_seconds"] = round(total_duration / 1_000_000_000, 3) if total_duration else None
    return metrics


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in re.findall(r"[a-zA-Z0-9]+", text) if len(token) > 2]


def split_sentences(text: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return []
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9(])", normalized) if part.strip()]


def lexical_overlap(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left.intersection(right)) / len(left)


def trim_words(text: str, max_words: int) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]).rstrip(" ,;:") + "."


def clean_markup(text: str) -> str:
    return text.replace("[[", "").replace("]]", "")
