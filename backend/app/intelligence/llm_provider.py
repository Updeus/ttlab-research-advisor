from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from app.config import Settings, get_settings

PROMPT_TEMPLATE_VERSION = "ask-ttlab-grounded-v2"


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

    def __init__(
        self,
        *,
        requested_provider: str = "offline_extractive",
        configured_provider: str = "offline_extractive",
        requested_model: str | None = None,
        configured_model: str | None = None,
        fallback_reason: str | None = None,
        fallback_exception_class: str | None = None,
        upstream_metadata: dict[str, Any] | None = None,
    ) -> None:
        self.requested_provider = requested_provider
        self.configured_provider = configured_provider
        self.requested_model = requested_model
        self.configured_model = configured_model or self.model
        self.fallback_reason = fallback_reason
        self.fallback_exception_class = fallback_exception_class
        self.upstream_metadata = dict(upstream_metadata or {})

    def resolution_metadata(self) -> dict[str, Any]:
        return {
            "requested_provider": self.requested_provider,
            "configured_provider": self.configured_provider,
            "effective_provider": self.provider,
            "requested_model": self.requested_model,
            "configured_model": self.configured_model,
            "effective_model": self.model,
            "fallback_used": self.fallback_reason is not None,
            "fallback_reason": self.fallback_reason,
            "fallback_exception_class": self.fallback_exception_class,
        }

    def generate_answer(
        self,
        question: str,
        context_chunks: list[dict[str, Any]],
        audience: str = "general",
        max_words: int = 250,
    ) -> LLMAnswerDraft:
        prompt_input = {
            "template": "offline-extractive-v1",
            "question": question,
            "audience": audience,
            "max_words": max_words,
            "chunk_ids": [str(chunk.get("chunk_id") or "") for chunk in context_chunks],
        }
        prompt_hash = hashlib.sha256(
            json.dumps(prompt_input, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        configuration_hash = hashlib.sha256(
            json.dumps(
                {"model": self.model, "algorithm": "sentence-overlap-v1"},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        metadata = {
            "audience": audience,
            "context_chunk_count": len(context_chunks),
            "max_words": max_words,
            "provider_resolution": self.resolution_metadata(),
            "prompt_template_version": "offline-extractive-v1",
            "prompt_sha256": prompt_hash,
            "generation_config_sha256": configuration_hash,
            **self.upstream_metadata,
        }
        if not context_chunks:
            return LLMAnswerDraft(
                answer_text="I could not answer this from the indexed TTLAB paper chunks.",
                provider=self.provider,
                model=self.model,
                prompt_metadata=metadata,
                warnings=["No retrieved chunks were supplied to the offline extractive provider."],
            )
        answer = build_extractive_answer(question, context_chunks, max_words=max_words)
        return LLMAnswerDraft(
            answer_text=answer,
            provider=self.provider,
            model=self.model,
            prompt_metadata=metadata,
            warnings=[],
        )


class OllamaProvider:
    provider = "ollama"

    def __init__(
        self,
        model_name: str | None = None,
        *,
        requested_provider: str = "ollama",
        configured_provider: str = "ollama",
        settings: Settings | None = None,
    ) -> None:
        settings = settings or get_settings()
        self.base_url = settings.ollama_base_url.rstrip("/")
        self.model = model_name or settings.ollama_default_model
        self.timeout = settings.ollama_timeout_seconds
        self.num_ctx = settings.ollama_num_ctx
        self.keep_alive = settings.ollama_keep_alive
        self.requested_provider = requested_provider
        self.configured_provider = configured_provider
        self.requested_model = model_name
        allowed = {
            name: digest.removeprefix("sha256:").lower()
            for name, digest in settings.ollama_allowed_model_digests.items()
        }
        if self.model not in allowed:
            raise ValueError(
                f"Ollama model '{self.model}' is not pinned in TTLAB_OLLAMA_ALLOWED_MODEL_DIGESTS"
            )
        self.expected_digest = allowed[self.model]
        self.immutable_model = f"{self.model}@sha256:{self.expected_digest}"

    def resolution_metadata(
        self,
        *,
        effective_provider: str = "ollama",
        effective_model: str | None = None,
        fallback_reason: str | None = None,
        generation_time_digest_verified: bool = False,
        tag_stable_across_generation: bool = False,
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "requested_provider": self.requested_provider,
            "configured_provider": self.configured_provider,
            "effective_provider": effective_provider,
            "requested_model": self.requested_model,
            "configured_model": self.model,
            "configured_model_digest": f"sha256:{self.expected_digest}",
            "effective_model": effective_model or self.model,
            "generation_time_digest_verified": generation_time_digest_verified,
            "tag_stable_across_generation": tag_stable_across_generation,
            "fallback_used": fallback_reason is not None,
            "fallback_reason": fallback_reason,
        }
        if generation_time_digest_verified:
            metadata["model_digest"] = f"sha256:{self.expected_digest}"
        return metadata

    def generate_answer(
        self,
        question: str,
        context_chunks: list[dict[str, Any]],
        audience: str = "general",
        max_words: int = 250,
    ) -> LLMAnswerDraft:
        if not context_chunks:
            return OfflineExtractiveProvider(
                requested_provider=self.requested_provider,
                configured_provider=self.configured_provider,
                requested_model=self.requested_model,
                configured_model=self.immutable_model,
                fallback_reason="no_context_chunks",
                upstream_metadata={
                    "attempted_provider": "ollama",
                    "attempted_model": self.immutable_model,
                    "configured_model_digest": f"sha256:{self.expected_digest}",
                    "generation_time_digest_verified": False,
                },
            ).generate_answer(question, context_chunks, audience, max_words)
        prompt = build_ollama_prompt(question, context_chunks, audience=audience, max_words=max_words)
        payload = {
            # Ollama's documented generate API accepts model names/tags, not a
            # digest-suffixed reference. A response-reported digest can bind an
            # output to immutable bytes. Otherwise pre/post tag checks narrow
            # (but do not eliminate) the tag-mutation race and the output stays
            # attributed to the mutable tag.
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
        prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        generation_config_hash = hashlib.sha256(
            json.dumps(payload["options"], sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        preflight_digest: str | None = None
        postflight_digest: str | None = None
        try:
            preflight_digest = verify_ollama_model_digest(
                self.base_url,
                self.model,
                self.expected_digest,
                timeout=min(self.timeout, 5.0),
            )
            response = httpx.post(f"{self.base_url}/api/generate", json=payload, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()
            response_identity = verify_ollama_generation_identity(
                data,
                configured_model=self.model,
                expected_digest=self.expected_digest,
            )
            postflight_digest = verify_ollama_model_digest(
                self.base_url,
                self.model,
                self.expected_digest,
                timeout=min(self.timeout, 5.0),
            )
            answer = clean_markup(str(data.get("response") or "")).strip()
            if not answer:
                raise ValueError("Ollama returned an empty response.")
            digest_attested = bool(response_identity["generation_time_digest_verified"])
            effective_model = self.immutable_model if digest_attested else self.model
            warnings: list[str] = []
            if not digest_attested:
                warnings.append(
                    "The configured Ollama tag matched its pinned digest before and after generation, but the "
                    "generation response did not report a digest. This output is attributed to the mutable tag; "
                    "the two checks narrow but do not eliminate the tag-mutation race or establish reproducible "
                    "generation-time model identity."
                )
            return LLMAnswerDraft(
                answer_text=answer,
                provider=self.provider,
                model=effective_model,
                prompt_metadata={
                    "audience": audience,
                    "context_chunk_count": len(context_chunks),
                    "max_words": max_words,
                    "ollama_metrics": extract_ollama_metrics(data),
                    "provider_resolution": self.resolution_metadata(
                        effective_model=effective_model,
                        generation_time_digest_verified=digest_attested,
                        tag_stable_across_generation=True,
                    ),
                    "configured_model_digest": f"sha256:{self.expected_digest}",
                    **(
                        {"model_digest": f"sha256:{self.expected_digest}"}
                        if digest_attested
                        else {}
                    ),
                    "preflight_model_digest": f"sha256:{preflight_digest}",
                    "postflight_model_digest": f"sha256:{postflight_digest}",
                    "generation_time_digest_verified": digest_attested,
                    "tag_stable_across_generation": True,
                    "ollama_response_identity": response_identity,
                    "prompt_template_version": PROMPT_TEMPLATE_VERSION,
                    "prompt_sha256": prompt_hash,
                    "generation_config_sha256": generation_config_hash,
                },
                warnings=warnings,
            )
        except Exception as exc:
            if isinstance(exc, httpx.HTTPError):
                reason = "ollama_transport_or_http_failure"
            elif isinstance(exc, ValueError) and ("digest" in str(exc).lower() or "not installed" in str(exc).lower()):
                reason = "ollama_model_identity_verification_failed"
            elif isinstance(exc, ValueError):
                reason = "ollama_invalid_response"
            else:
                reason = "ollama_generation_failed"
            fallback = OfflineExtractiveProvider(
                requested_provider=self.requested_provider,
                configured_provider=self.configured_provider,
                requested_model=self.requested_model,
                configured_model=self.immutable_model,
                fallback_reason=reason,
                fallback_exception_class=type(exc).__name__,
                upstream_metadata={
                    "attempted_provider": "ollama",
                    "attempted_model": self.immutable_model,
                    "configured_model_digest": f"sha256:{self.expected_digest}",
                    "preflight_model_digest": (
                        f"sha256:{preflight_digest}" if preflight_digest is not None else None
                    ),
                    "postflight_model_digest": (
                        f"sha256:{postflight_digest}" if postflight_digest is not None else None
                    ),
                    "generation_time_digest_verified": False,
                    "attempted_prompt_template_version": PROMPT_TEMPLATE_VERSION,
                    "attempted_prompt_sha256": prompt_hash,
                    "attempted_generation_config_sha256": generation_config_hash,
                },
            ).generate_answer(question, context_chunks, audience, max_words)
            fallback.warnings.append(
                f"Ollama model {self.model} was unavailable, failed, or changed identity during generation; "
                f"used offline extractive fallback. Reason: {type(exc).__name__}."
            )
            return fallback


def get_provider(
    provider_name: str = "auto",
    model_name: str | None = None,
    *,
    settings: Settings | None = None,
) -> LLMProvider:
    requested = (provider_name or "auto").strip().lower()
    normalized = requested
    settings = settings or get_settings()
    allowed = {provider.strip().lower() for provider in settings.allowed_llm_providers}
    if normalized == "extractive_mock":
        normalized = "offline_extractive"
    if normalized == "auto":
        normalized = settings.default_llm_provider
    if normalized not in allowed:
        raise ValueError(f"LLM provider '{normalized}' is not in TTLAB_ALLOWED_LLM_PROVIDERS")
    if normalized == "offline_extractive":
        if model_name:
            raise ValueError("A model override is supported only for the pinned Ollama provider")
        return OfflineExtractiveProvider(
            requested_provider=requested,
            configured_provider=normalized,
            requested_model=model_name,
        )
    if normalized == "ollama":
        return OllamaProvider(
            model_name=model_name,
            requested_provider=requested,
            configured_provider=normalized,
            settings=settings,
        )
    raise ValueError(f"Unknown LLM provider: {provider_name}")


def external_provider_available(settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    return bool(
        "ollama" in {provider.strip().lower() for provider in settings.allowed_llm_providers}
        and settings.ollama_allowed_model_digests
    )


def verify_ollama_model_digest(
    base_url: str,
    model_name: str,
    expected_digest: str,
    *,
    timeout: float,
) -> str:
    response = httpx.get(f"{base_url.rstrip('/')}/api/tags", timeout=timeout)
    response.raise_for_status()
    models = response.json().get("models", [])
    for record in models:
        name = str(record.get("name") or record.get("model") or "").strip()
        if name != model_name:
            continue
        actual = str(record.get("digest") or "").removeprefix("sha256:").lower()
        if actual != expected_digest:
            raise ValueError(
                f"Ollama digest mismatch for '{model_name}'; expected sha256:{expected_digest}"
            )
        return actual
    raise ValueError(f"Pinned Ollama model '{model_name}' is not installed")


def verify_ollama_generation_identity(
    payload: dict[str, Any],
    *,
    configured_model: str,
    expected_digest: str,
) -> dict[str, Any]:
    """Validate response identity without inventing a digest Ollama did not report."""

    response_model = str(payload.get("model") or "").strip()
    response_digest = str(payload.get("model_digest") or payload.get("digest") or "")
    if response_model != configured_model:
        raise ValueError("Ollama generation response reported a different model tag")
    normalized_digest = response_digest.removeprefix("sha256:").lower()
    if response_digest and normalized_digest != expected_digest:
        raise ValueError("Ollama generation response reported a different model digest")
    if normalized_digest:
        return {
            "requested_model": configured_model,
            "response_model": response_model,
            "response_digest": f"sha256:{normalized_digest}",
            "identity_basis": "generation_response_reported_digest",
            "generation_time_digest_verified": True,
        }
    return {
        "requested_model": configured_model,
        "response_model": response_model,
        "identity_basis": "response_tag_plus_pre_and_post_tag_digest_checks",
        "generation_time_digest_verified": False,
    }


def build_ollama_prompt(
    question: str,
    context_chunks: list[dict[str, Any]],
    *,
    audience: str,
    max_words: int,
) -> str:
    compact_chunks = []
    # Citation verification resolves [S1], [S2], ... against the candidate
    # citation list in retrieval order. Preserve that exact order here so a
    # prompt-local alias can never point at a different chunk.
    for index, chunk in enumerate(context_chunks[:8], start=1):
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
        "You are Ask TTLAB, a source-cited research assistant.\n"
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
