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
        answer = build_extractive_answer(question, context_chunks, max_words=max_words)
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
    ordered_chunks = order_context_chunks_for_question(question, context_chunks)
    for index, chunk in enumerate(ordered_chunks[:8], start=1):
        source_id = f"S{index}"
        chunk_id = str(chunk.get("chunk_id") or f"chunk-{index}")
        title = clean_markup(str(chunk.get("title") or "Untitled paper"))
        authors = ", ".join(str(author) for author in chunk.get("authors", []) if str(author).strip())
        year = chunk.get("year") or "unknown year"
        section = clean_markup(str(chunk.get("section") or "Unknown section"))
        page_start = chunk.get("page_start") or "?"
        page_end = chunk.get("page_end") or "?"
        snippet = trim_words(clean_evidence_text(str(chunk.get("text") or chunk.get("snippet") or "")), max_words=115)
        compact_chunks.append(
            f"[{source_id}] chunk_id: {chunk_id}\nPaper: {title} ({year})\nAuthors: {authors or 'not listed'}\n"
            f"Section: {section}; pages {page_start}-{page_end}\nEvidence: {snippet}"
        )
    context = "\n\n".join(compact_chunks)
    return (
        "You are Ask TTLAB, a source-grounded research assistant.\n"
        "Answer only from the provided TTLAB paper chunks. Do not add outside facts.\n"
        "If the chunks only answer part of the question, answer that supported part and state what is not supported.\n"
        "Do not say there is no evidence if any source chunk directly supports part of the question.\n"
        "Prefer concise bullets when naming papers, authors, limitations, or future work.\n"
        "Cite source IDs inline using square brackets, for example [S1].\n"
        f"Audience: {audience}. Keep the answer under {max_words} words.\n\n"
        f"Source chunks:\n{context}\n\n"
        f"Question: {question}\n\n"
        "Answer:"
    )


def build_extractive_answer(question: str, context_chunks: list[dict[str, Any]], *, max_words: int) -> str:
    intent = classify_question(question)
    evidence_rows = build_evidence_rows(question, order_context_chunks_for_question(question, context_chunks))
    if not evidence_rows:
        return "I could not find enough readable evidence in the retrieved TTLAB paper chunks to answer this clearly."

    if intent == "paper_list":
        return trim_words(build_paper_list_answer(evidence_rows), max_words=max_words)
    if intent == "who":
        return trim_words(build_author_answer(evidence_rows), max_words=max_words)
    if intent == "limitations":
        return trim_words(build_limitations_answer(evidence_rows), max_words=max_words)

    intro = "Based on the indexed TTLAB paper chunks, the most relevant sources are:"
    bullets = []
    seen_titles: set[str] = set()
    for row in evidence_rows:
        if row["title"] in seen_titles:
            continue
        seen_titles.add(row["title"])
        year = f" ({row['year']})" if row.get("year") else ""
        authors = f" - {', '.join(row['authors'][:3])}" if row["authors"] else ""
        bullets.append(f"- {row['title']}{year}{authors}: {row['evidence']} [{row['chunk_id']}]")
        if len(bullets) >= 4:
            break
    return trim_words("\n".join([intro, *bullets]), max_words=max_words)


def classify_question(question: str) -> str:
    lowered = question.lower().strip()
    if lowered.startswith("who") or "which researcher" in lowered or "which author" in lowered:
        return "who"
    if lowered.startswith(("which paper", "which ttlab paper", "what paper", "what papers")) or "papers could i read" in lowered:
        return "paper_list"
    if any(term in lowered for term in ("limitation", "future work", "challenge", "extend", "extension")):
        return "limitations"
    return "sources"


def build_evidence_rows(question: str, context_chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    question_terms = set(tokenize(question))
    rows: list[dict[str, Any]] = []
    for chunk in context_chunks[:8]:
        source_text = clean_evidence_text(str(chunk.get("text") or chunk.get("snippet") or ""))
        sentences = split_sentences(source_text)
        if not sentences and source_text:
            sentences = [source_text]
        ranked = sorted(
            sentences,
            key=lambda sentence: lexical_overlap(question_terms, set(tokenize(sentence))),
            reverse=True,
        )
        evidence = first_readable_sentence(ranked) or trim_words(source_text, max_words=34)
        if not evidence:
            continue
        rows.append(
            {
                "chunk_id": str(chunk.get("chunk_id") or ""),
                "title": clean_markup(str(chunk.get("title") or "Untitled paper")),
                "authors": [str(author) for author in chunk.get("authors", []) if str(author).strip() and str(author).lower() != "click to view"],
                "year": chunk.get("year"),
                "section": chunk.get("section"),
                "evidence": trim_words(evidence, max_words=38),
                "all_sentences": sentences,
            }
        )
    return rows


def order_context_chunks_for_question(question: str, context_chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    lowered_question = question.lower()
    intent = classify_question(question)
    if "agriculture" in lowered_question or "agricultural" in lowered_question:
        agriculture_terms = ("agriculture", "agricultural", "crop", "crops", "cocoa", "plantation", "biomass", "deforestation", "drone", "weed", "water stress", "farming")

        def agriculture_score(chunk: dict[str, Any]) -> tuple[int, float]:
            text = source_text_for_chunk(chunk).lower()
            matched_terms = sum(1 for term in agriculture_terms if term in text)
            combined = float((chunk.get("scores") or {}).get("combined") or 0.0)
            return matched_terms, combined

        return sorted(context_chunks, key=agriculture_score, reverse=True)

    if intent != "limitations":
        return context_chunks

    def limitation_score(chunk: dict[str, Any]) -> tuple[int, float]:
        text = source_text_for_chunk(chunk).lower()
        section = str(chunk.get("section") or "").lower()
        explicit = 0
        if "limitations and future work" in text:
            explicit += 8
        if re.search(r"\bfuture work\b|\bfuture research\b|\blimitations?\b", text):
            explicit += 5
        if any(term in section for term in ("future", "limitation", "discussion", "conclusion")):
            explicit += 2
        if "rag" in text or "retrieval-augmented" in text or "retrieval augmented" in text:
            explicit += 1
        combined = float((chunk.get("scores") or {}).get("combined") or 0.0)
        return explicit, combined

    return sorted(context_chunks, key=limitation_score, reverse=True)


def source_text_for_chunk(chunk: dict[str, Any]) -> str:
    return clean_evidence_text(str(chunk.get("text") or chunk.get("snippet") or ""))


def first_readable_sentence(sentences: list[str]) -> str:
    for sentence in sentences:
        cleaned = clean_evidence_text(sentence)
        lowered = cleaned.lower()
        if len(cleaned.split()) < 8:
            continue
        if is_noisy_evidence_sentence(cleaned):
            continue
        return cleaned
    for sentence in sentences:
        cleaned = clean_evidence_text(sentence)
        if len(cleaned.split()) >= 6:
            return cleaned
    return ""


def build_author_answer(rows: list[dict[str, Any]]) -> str:
    authors: dict[str, dict[str, Any]] = {}
    for row in rows:
        for author in row["authors"]:
            entry = authors.setdefault(author, {"papers": [], "chunks": []})
            if row["title"] not in entry["papers"]:
                entry["papers"].append(row["title"])
            entry["chunks"].append(row["chunk_id"])
    if not authors:
        return build_limitations_answer(rows)
    ranked = sorted(authors.items(), key=lambda item: len(item[1]["papers"]), reverse=True)
    bullets = ["Based on authorship in the retrieved chunks, these researchers appear most relevant:"]
    for author, data in ranked[:5]:
        papers = "; ".join(data["papers"][:3])
        chunk_id = data["chunks"][0] if data["chunks"] else ""
        bullets.append(f"- {author}: appears on {papers}. [{chunk_id}]")
    bullets.append("This is an authorship-based signal, not a verified supervisor recommendation.")
    return "\n".join(bullets)


def is_noisy_evidence_sentence(sentence: str) -> bool:
    lowered = sentence.lower()
    if "@" in sentence:
        return True
    if any(marker in lowered for marker in ("department of", "university of", "proceedings of", "annual conference", " et al", " arxiv")):
        return True
    if len(re.findall(r"\[[0-9]+\]", sentence)) >= 2:
        return True
    return False


def build_paper_list_answer(rows: list[dict[str, Any]]) -> str:
    bullets = ["Based on the indexed TTLAB paper chunks, the strongest matching papers are:"]
    seen_titles: set[str] = set()
    for row in rows:
        if row["title"] in seen_titles:
            continue
        seen_titles.add(row["title"])
        year = f" ({row['year']})" if row.get("year") else ""
        authors = f" - {', '.join(row['authors'][:3])}" if row["authors"] else ""
        evidence = row["evidence"]
        bullets.append(f"- {row['title']}{year}{authors}: {evidence} [{row['chunk_id']}]")
        if len(bullets) >= 5:
            break
    return "\n".join(bullets)


def build_limitations_answer(rows: list[dict[str, Any]]) -> str:
    strong_pattern = re.compile(r"\bfuture work\b|\bfuture research\b|\blimitations?\b|\bnot one-size\b", flags=re.IGNORECASE)
    weak_pattern = re.compile(r"\bextend\b|\bfurther\b|\bconditional\b", flags=re.IGNORECASE)
    explicit: list[str] = []
    related: list[str] = []
    for row in rows:
        matching = sorted(
            [
                clean_evidence_text(sentence)
                for sentence in row["all_sentences"]
                if strong_pattern.search(sentence) or weak_pattern.search(sentence)
            ],
            key=lambda sentence: (bool(strong_pattern.search(sentence)), len(sentence)),
            reverse=True,
        )
        if matching:
            explicit.append(f"- {row['title']}: {trim_words(matching[0], max_words=42)} [{row['chunk_id']}]")
        elif row["evidence"]:
            related.append(f"- {row['title']}: {row['evidence']} [{row['chunk_id']}]")
    if explicit:
        return "\n".join(["The retrieved chunks include these limitation/future-work signals:", *explicit[:4]])
    return "\n".join(
        [
            "I did not find explicit limitation or future-work wording in the top retrieved chunks. Related evidence that may help frame limitations is:",
            *related[:4],
        ]
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


def clean_evidence_text(text: str) -> str:
    cleaned = clean_markup(text)
    cleaned = re.sub(r"[\w.+-]+@[\w.-]+\.\w+", "", cleaned)
    cleaned = re.sub(r"https?://\S+", "", cleaned)
    cleaned = re.sub(r"\bdoi:\S+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = cleaned.replace("Abstract—", "").replace("Abstract-", "")
    cleaned = re.sub(r"\s+([,.;:!?])", r"\1", cleaned)
    return cleaned.strip(" ,;:-")
