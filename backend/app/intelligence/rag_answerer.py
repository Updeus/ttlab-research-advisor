from __future__ import annotations

import argparse
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlmodel import Session, select

from app.config import Settings, get_settings
from app.db import create_db_and_tables, engine
from app.indexing.retriever import RetrievalScope, retrieve
from app.intelligence.citation_verifier import verify_citations
from app.intelligence.llm_provider import external_provider_available, get_provider
from app.models import Paper, RAGAnswer
from app.runtime_provenance import build_runtime_provenance

GENERIC_PAPER_SCOPE_TERMS = {
    "about",
    "contribution",
    "contributions",
    "describe",
    "findings",
    "main",
    "paper",
    "say",
    "says",
    "summary",
    "summarize",
}


def utc_now() -> datetime:
    return datetime.now(UTC)


def ask_question(
    session: Session,
    question: str,
    *,
    mode: str = "keyword",
    top_k: int = 5,
    audience: str = "general",
    max_words: int = 250,
    provider_name: str = "auto",
    model_name: str | None = None,
    paper_id: str | None = None,
    persist: bool = False,
    retrieval_scope: RetrievalScope = "public",
    provider_settings: Settings | None = None,
) -> dict[str, Any]:
    retrieval_question = question
    scoped_paper = session.get(Paper, paper_id) if paper_id else None
    generic_paper_scope = False
    if scoped_paper is not None:
        scoped_terms = source_query_terms(question)
        if not scoped_terms or scoped_terms.issubset(GENERIC_PAPER_SCOPE_TERMS):
            generic_paper_scope = True
            retrieval_question = (
                f"{scoped_paper.title} abstract conclusion discussion results performance contribution"
            )
        else:
            retrieval_question = f"{question} {scoped_paper.title}"
    retrieval = retrieve(
        session,
        retrieval_question,
        mode=mode,
        top_k=top_k,
        paper_id=paper_id,
        include_text=True,
        scope=retrieval_scope,
    )
    retrieved_chunks = [format_retrieved_chunk(result) for result in retrieval["results"]]
    warnings = list(retrieval.get("warnings", []))
    answerability = assess_answerability(
        "" if generic_paper_scope else question,
        retrieval["results"],
        paper_id=paper_id,
    )
    response_retrieval_metadata = {
        "expanded_query": retrieval.get("expanded_query"),
        "query_expansions": retrieval.get("query_expansions", []),
        "retrieval_strategy": retrieval.get("retrieval_strategy", "explicit_config_v1"),
        "retrieval_scope": retrieval_scope,
        **(
            {
                "paper_scope_query_augmented": True,
                "generic_paper_scope": generic_paper_scope,
            }
            if scoped_paper is not None
            else {}
        ),
    }
    if not retrieved_chunks or not answerability["answerable"]:
        answer = build_unsupported_answer(
            question,
            mode,
            top_k,
            provider_name,
            warnings + list(answerability["warnings"]),
            model_name=model_name,
            paper_id=paper_id,
            retrieved_chunks=retrieved_chunks,
            answerability=answerability,
            retrieval_metadata=response_retrieval_metadata,
            provider_settings=provider_settings,
        )
        answer["runtime_provenance"] = build_runtime_provenance(
            session,
            record_type="rag_answer",
            generation_config={
                "mode": mode,
                "top_k": top_k,
                "audience": audience,
                "max_words": max_words,
                "paper_scoped": paper_id is not None,
                "answerability_reason": answerability.get("reason"),
            },
            provider=answer["provider"],
            model=answer["model"],
            generated_at=answer["created_at"],
            retrieval_mode=mode,
            source_chunk_ids=[chunk["chunk_id"] for chunk in retrieved_chunks],
            generation_metadata=answer.get("generation_metadata", {}),
            retrieval_metadata=response_retrieval_metadata
            | {
                "retriever_config": retrieval.get("retriever_config", {}),
                "vector_provider": retrieval.get("vector_provider"),
            },
            corpus_scope=retrieval_scope,
        )
        if persist:
            store_answer(session, answer)
        return answer

    relevant_ids = set(answerability["relevant_chunk_ids"])
    relevant_results = [result for result in retrieval["results"] if result["chunk_id"] in relevant_ids]
    retrieved_chunks = [format_retrieved_chunk(result) for result in relevant_results]
    provider = get_provider(provider_name, model_name=model_name, settings=provider_settings)
    draft = provider.generate_answer(question, retrieved_chunks, audience=audience, max_words=max_words)
    candidate_citations = build_citations(relevant_results[: min(len(relevant_results), top_k)])
    verification = verify_citations(draft.answer_text, retrieved_chunks, candidate_citations)
    used_chunk_ids = set(verification["used_chunk_ids"])
    citations = [citation for citation in candidate_citations if citation["chunk_id"] in used_chunk_ids]
    answer_text = draft.answer_text
    if verification["grounding_status"] == "unsupported":
        answer_text = "I could not produce an answer whose claims were structurally tied to the retrieved TTLAB sources."
    created_at = utc_now()
    response = {
        "answer_id": str(uuid.uuid4()),
        "question": question,
        "answer": answer_text,
        "grounding_status": verification["grounding_status"],
        "support_status": verification["support_status"],
        "provider": draft.provider,
        "model": draft.model,
        "retrieval_mode": mode,
        "top_k": top_k,
        "paper_id": paper_id,
        "citations": citations,
        "retrieved_chunks": retrieved_chunks,
        "retrieval_metadata": response_retrieval_metadata,
        "generation_metadata": draft.prompt_metadata,
        "answerability": answerability,
        "claim_support": verification["claim_support"],
        "warnings": warnings + draft.warnings + verification["warnings"],
        "unsupported_claims": verification["unsupported_claims"],
        "created_at": created_at.isoformat(),
    }
    response["runtime_provenance"] = build_runtime_provenance(
        session,
        record_type="rag_answer",
        generation_config={
            "mode": mode,
            "top_k": top_k,
            "audience": audience,
            "max_words": max_words,
            "paper_scoped": paper_id is not None,
            "retriever_config": retrieval.get("retriever_config", {}),
        },
        provider=draft.provider,
        model=draft.model,
        generated_at=created_at,
        retrieval_mode=mode,
        source_chunk_ids=[chunk["chunk_id"] for chunk in retrieved_chunks],
        generation_metadata=draft.prompt_metadata,
        retrieval_metadata=response["retrieval_metadata"]
        | {
            "retriever_config": retrieval.get("retriever_config", {}),
            "vector_provider": retrieval.get("vector_provider"),
        },
        corpus_scope=retrieval_scope,
    )
    if persist:
        store_answer(session, response)
    return response


def build_unsupported_answer(
    question: str,
    mode: str,
    top_k: int,
    provider_name: str,
    warnings: list[str],
    *,
    model_name: str | None = None,
    paper_id: str | None = None,
    retrieved_chunks: list[dict[str, Any]] | None = None,
    answerability: dict[str, Any] | None = None,
    retrieval_metadata: dict[str, Any] | None = None,
    provider_settings: Settings | None = None,
) -> dict[str, Any]:
    created_at = utc_now()
    resolved_answerability = answerability or {"answerable": False, "reason": "no_retrieved_chunks"}
    reason = str(resolved_answerability.get("reason") or "unknown")
    if reason == "no_retrieved_chunks":
        reason_warning = "No relevant indexed TTLAB chunks were retrieved."
        unsupported_claim = "No source chunks support an answer."
    elif reason == "hard_negative_source_mismatch":
        reason_warning = "Retrieved chunks did not sufficiently match the question; answer generation abstained."
        unsupported_claim = "Retrieved source chunks did not support the requested subject."
    elif reason == "no_source_specific_query_terms":
        reason_warning = "The question did not contain enough source-specific terms for a grounded answer."
        unsupported_claim = "The request was too broad to establish source support."
    else:
        reason_warning = f"Answer generation abstained because the answerability gate returned: {reason}."
        unsupported_claim = "The pre-generation answerability gate did not establish source support."
    response_warnings = list(dict.fromkeys([*warnings, reason_warning]))
    provider = get_provider(provider_name, model_name=model_name, settings=provider_settings)
    resolution = provider.resolution_metadata() if hasattr(provider, "resolution_metadata") else {}
    resolution = {
        **resolution,
        "effective_provider": "not_invoked",
        "effective_model": None,
        "fallback_used": False,
        "fallback_reason": None,
    }
    return {
        "answer_id": str(uuid.uuid4()),
        "question": question,
        "answer": "I could not answer this from the indexed TTLAB papers. Try a more specific question or index more paper chunks.",
        "grounding_status": "unsupported",
        "provider": "not_invoked",
        "model": "not_invoked",
        "retrieval_mode": mode,
        "top_k": top_k,
        "paper_id": paper_id,
        "citations": [],
        "retrieved_chunks": retrieved_chunks or [],
        "retrieval_metadata": retrieval_metadata
        or {
            "expanded_query": None,
            "query_expansions": [],
            "retrieval_strategy": "explicit_config_v1",
            "retrieval_scope": "public",
        },
        "generation_metadata": {"provider_resolution": resolution},
        "answerability": resolved_answerability,
        "claim_support": [],
        "support_status": "unsupported",
        "warnings": response_warnings,
        "unsupported_claims": [unsupported_claim],
        "created_at": created_at.isoformat(),
    }


def assess_answerability(
    question: str,
    results: list[dict[str, Any]],
    *,
    paper_id: str | None,
) -> dict[str, Any]:
    """Reject unrelated retrieval before any answer provider is invoked."""

    question_terms = source_query_terms(question)
    if not results:
        return {
            "answerable": False,
            "reason": "no_retrieved_chunks",
            "query_terms": sorted(question_terms),
            "matched_query_terms": [],
            "max_query_coverage": 0.0,
            "relevant_chunk_ids": [],
            "warnings": ["No relevant indexed TTLAB chunks were retrieved."],
        }
    # A paper-scoped request may use referential wording ("this paper"). The
    # explicit identifier supplies the scope, but the corpus boundary has still
    # been enforced by retrieval.
    if not question_terms and paper_id:
        return {
            "answerable": True,
            "reason": "explicit_paper_scope",
            "query_terms": [],
            "matched_query_terms": [],
            "max_query_coverage": 1.0,
            "relevant_chunk_ids": [str(result["chunk_id"]) for result in results],
            "warnings": [],
        }
    if not question_terms:
        return {
            "answerable": False,
            "reason": "no_source_specific_query_terms",
            "query_terms": [],
            "matched_query_terms": [],
            "max_query_coverage": 0.0,
            "relevant_chunk_ids": [],
            "warnings": ["The question did not contain enough source-specific terms for a defensible answer."],
        }

    scored_results: list[tuple[str, float, set[str]]] = []
    matched_union: set[str] = set()
    max_coverage = 0.0
    for result in results:
        searchable = " ".join(
            [
                str(result.get("paper_title") or ""),
                " ".join(str(value) for value in result.get("topics", [])),
                str(result.get("section") or ""),
                str(result.get("text") or result.get("snippet") or ""),
            ]
        )
        source_terms = augment_source_aliases(
            searchable,
            set(re.findall(r"[a-zA-Z0-9]+", searchable.lower())),
        )
        matched = question_terms.intersection(source_terms)
        coverage = len(matched) / len(question_terms)
        max_coverage = max(max_coverage, coverage)
        scored_results.append((str(result["chunk_id"]), coverage, matched))

    minimum_coverage = 0.25 if len(question_terms) >= 4 else 0.34
    relevant = [chunk_id for chunk_id, coverage, _matched in scored_results if coverage >= minimum_coverage]
    for _chunk_id, coverage, matched in scored_results:
        if coverage >= minimum_coverage:
            matched_union.update(matched)
    answerable = bool(relevant and max_coverage >= minimum_coverage)
    reason = "source_term_coverage" if answerable else "hard_negative_source_mismatch"
    return {
        "answerable": answerable,
        "reason": reason,
        "query_terms": sorted(question_terms),
        "matched_query_terms": sorted(matched_union),
        "max_query_coverage": round(max_coverage, 4),
        "minimum_query_coverage": minimum_coverage,
        "relevant_chunk_ids": relevant if answerable else [],
        "warnings": [] if answerable else [
            "Retrieved chunks did not contain enough of the question's source-specific terms; answer generation abstained."
        ],
    }


def source_query_terms(question: str) -> set[str]:
    stopwords = {
        "about", "answer", "are", "could", "discuss", "does", "explain", "find", "for", "from",
        "have", "how", "include", "indexed", "into", "most", "paper", "papers", "research", "show",
        "that", "the", "their", "this", "to", "ttlab", "what", "which", "who", "with", "work", "works",
    }
    controlled_acronyms = {"ai", "ml", "rag", "nlp", "iot"}
    terms = {
        token
        for token in re.findall(r"[a-zA-Z0-9]+", question.lower())
        if (len(token) > 2 or token in controlled_acronyms) and token not in stopwords
    }
    return terms


def augment_source_aliases(text: str, terms: set[str]) -> set[str]:
    lowered = text.lower()
    expanded = set(terms)
    aliases = {
        "rag": ("retrieval augmented generation", "retrieval-augmented generation"),
        "ai": ("artificial intelligence",),
        "ml": ("machine learning",),
        "nlp": ("natural language processing",),
        "iot": ("internet of things",),
    }
    for alias, phrases in aliases.items():
        if any(phrase in lowered for phrase in phrases):
            expanded.add(alias)
    return expanded


def format_retrieved_chunk(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "chunk_id": result["chunk_id"],
        "paper_id": result["paper_id"],
        "title": result["paper_title"],
        "authors": result.get("authors", []),
        "year": result.get("year"),
        "page_start": result.get("page_start"),
        "page_end": result.get("page_end"),
        "section": result.get("section"),
        "snippet": result.get("snippet", ""),
        "text": result.get("text", ""),
        "scores": result.get("scores", {}),
        "source": result.get("source", {}),
    }


def build_citations(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    citations: list[dict[str, Any]] = []
    seen: set[str] = set()
    for result in results:
        if result["chunk_id"] in seen:
            continue
        seen.add(result["chunk_id"])
        source = result.get("source", {})
        citations.append(
            {
                "paper_id": result["paper_id"],
                "title": result["paper_title"],
                "authors": result.get("authors", []),
                "year": result.get("year"),
                "chunk_id": result["chunk_id"],
                "section": result.get("section"),
                "page_start": result.get("page_start"),
                "page_end": result.get("page_end"),
                "snippet": result.get("snippet", ""),
                "score": result.get("scores", {}).get("combined", 0.0),
                "source_url": source.get("post_url"),
                "pdf_url": source.get("pdf_url"),
            }
        )
    return citations


def store_answer(session: Session, response: dict[str, Any]) -> None:
    answer = RAGAnswer(
        answer_id=response["answer_id"],
        question=response["question"],
        answer=response["answer"],
        retrieved_chunk_ids=[chunk["chunk_id"] for chunk in response["retrieved_chunks"]],
        cited_paper_ids=sorted({citation["paper_id"] for citation in response["citations"]}),
        citations_json=response["citations"],
        retrieval_mode=response["retrieval_mode"],
        top_k=response["top_k"],
        provider=response["provider"],
        model=response["model"],
        grounding_status=response["grounding_status"],
        unsupported_claims_json=response["unsupported_claims"],
        warnings_json=response["warnings"],
        retrieved_chunks_json=response["retrieved_chunks"],
        generation_metadata_json=response.get("generation_metadata", {}),
        runtime_provenance_json=response.get("runtime_provenance", {}),
        claim_support_json=response.get("claim_support", []),
        answerability_json=response.get("answerability", {}),
        created_at=datetime.fromisoformat(response["created_at"]),
    )
    session.add(answer)
    session.commit()


def serialize_answer(answer: RAGAnswer) -> dict[str, Any]:
    claim_support = list(answer.claim_support_json or [])
    support_status = (
        "support_unverified"
        if any(
            isinstance(item, dict) and item.get("classification") == "support_unverified"
            for item in claim_support
        )
        else "unsupported"
    )
    return {
        "answer_id": answer.answer_id,
        "question": answer.question,
        "answer": answer.answer,
        "grounding_status": answer.grounding_status,
        "provider": answer.provider,
        "model": answer.model,
        "retrieval_mode": answer.retrieval_mode,
        "top_k": answer.top_k,
        "paper_id": None,
        "citations": answer.citations_json,
        "retrieved_chunks": answer.retrieved_chunks_json,
        "retrieval_metadata": {},
        "generation_metadata": answer.generation_metadata_json,
        "runtime_provenance": answer.runtime_provenance_json,
        "answerability": answer.answerability_json,
        "claim_support": claim_support,
        "support_status": support_status,
        "warnings": answer.warnings_json,
        "unsupported_claims": answer.unsupported_claims_json,
        "review_status": answer.review_status,
        "reviewer_notes": answer.reviewer_notes,
        "reviewed_at": answer.reviewed_at.isoformat() if answer.reviewed_at else None,
        "reviewed_by": answer.reviewed_by,
        "citation_correct": answer.citation_correct,
        "answer_faithfulness_score": answer.answer_faithfulness_score,
        "usefulness_score": answer.usefulness_score,
        "created_at": answer.created_at.isoformat(),
    }


def ask_diagnostics(session: Session, settings: Settings | None = None) -> dict[str, Any]:
    # The anonymous diagnostics surface must not reveal reviewer/history data.
    configured = settings or get_settings()
    allowed = [provider.strip().lower() for provider in configured.allowed_llm_providers]
    pinned_models = sorted(configured.ollama_allowed_model_digests)
    allow_all_local = configured.all_local_ollama_models_enabled
    return {
        "total_stored_answers": None,
        "grounded_answers": None,
        "partial_answers": None,
        "unsupported_answers": None,
        "history_counts_visibility": "protected_reviewer_only",
        "history_counts_observed": False,
        "default_provider": configured.default_llm_provider,
        "allowed_providers": allowed,
        "provider_matrix": {
            "offline_extractive": {
                "enabled": "offline_extractive" in allowed,
                "effective_model": "sentence-overlap-v1",
                "identity_scope": "versioned_deterministic_algorithm",
            },
            "ollama": {
                "enabled": "ollama" in allowed,
                "configured_model": configured.ollama_default_model,
                "configured_model_pinned": configured.ollama_default_model in pinned_models,
                "pinned_model_count": len(pinned_models),
                "model_policy": "all_installed_local_models" if allow_all_local else "pinned_digest_only",
                "identity_scope": (
                    "installed_digest_observed_per_generation"
                    if allow_all_local
                    else "configured_digest_with_per_generation_attestation_state"
                ),
            },
        },
        "external_provider_available": external_provider_available(configured),
        "external_provider_availability_scope": (
            "local_demo_all_installed_models_not_runtime_reachability"
            if allow_all_local
            else "configured_pinned_model_not_runtime_reachability"
        ),
        "last_answer_timestamp": None,
        "scope": "public",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ask source-cited questions over indexed TTLAB chunks.")
    subparsers = parser.add_subparsers(dest="command")
    ask = subparsers.add_parser("ask")
    ask.add_argument("question")
    ask.add_argument("--mode", choices=["keyword", "feature_hashing", "dense", "hybrid"], default="keyword")
    ask.add_argument("--top-k", type=int, default=5)
    ask.add_argument("--provider", default="auto")
    ask.add_argument("--model", default=None)
    ask.add_argument("--paper-id", default=None)
    ask.add_argument("--audience", default="general")
    ask.add_argument("--max-words", type=int, default=250)
    ask.add_argument("--scope", choices=["public", "technical"], default="public")
    ask.add_argument(
        "--persist",
        action="store_true",
        help="Store the question, answer, and student-facing inputs in local history.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command != "ask":
        build_parser().print_help()
        return
    create_db_and_tables()
    with Session(engine) as session:
        response = ask_question(
            session,
            args.question,
            mode=args.mode,
            top_k=args.top_k,
            provider_name=args.provider,
            model_name=args.model,
            paper_id=args.paper_id,
            audience=args.audience,
            max_words=args.max_words,
            persist=args.persist,
            retrieval_scope=args.scope,
        )
    print(f"answer: {response['answer']}")
    print(f"grounding_status: {response['grounding_status']}")
    print("citations:")
    for citation in response["citations"]:
        print(
            f"- {citation['title']} pages {citation['page_start']}-{citation['page_end']} "
            f"chunk_id={citation['chunk_id']}"
        )
    if response["warnings"]:
        print("warnings:")
        for warning in response["warnings"]:
            print(f"- {warning}")


if __name__ == "__main__":
    main()
