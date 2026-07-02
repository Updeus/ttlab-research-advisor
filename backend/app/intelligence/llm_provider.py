from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Protocol


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


def get_provider(provider_name: str = "auto") -> LLMProvider:
    if provider_name in {"auto", "offline_extractive", "extractive_mock"}:
        if provider_name == "auto" and OptionalOpenAIProvider().available:
            return OptionalOpenAIProvider()
        return OfflineExtractiveProvider()
    if provider_name == "openai":
        openai = OptionalOpenAIProvider()
        return openai if openai.available else OfflineExtractiveProvider()
    raise ValueError(f"Unknown LLM provider: {provider_name}")


def external_provider_available() -> bool:
    return OptionalOpenAIProvider().available


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
