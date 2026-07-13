from __future__ import annotations

import argparse
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlmodel import Session, select

from app.db import create_db_and_tables, engine
from app.indexing.retriever import retrieve
from app.intelligence.citation_verifier import verify_citations
from app.intelligence.llm_provider import external_provider_available, get_provider
from app.models import RAGAnswer


def utc_now() -> datetime:
    return datetime.now(UTC)


def ask_question(
    session: Session,
    question: str,
    *,
    mode: str = "hybrid",
    top_k: int = 5,
    audience: str = "general",
    max_words: int = 250,
    provider_name: str = "auto",
    model_name: str | None = None,
    paper_id: str | None = None,
    persist: bool = False,
) -> dict[str, Any]:
    retrieval = retrieve(session, question, mode=mode, top_k=top_k, paper_id=paper_id, include_text=True)
    retrieved_chunks = [format_retrieved_chunk(result) for result in retrieval["results"]]
    warnings = list(retrieval.get("warnings", []))
    if not retrieved_chunks:
        answer = build_unsupported_answer(question, mode, top_k, provider_name, warnings, model_name=model_name, paper_id=paper_id)
        if persist:
            store_answer(session, answer)
        return answer

    provider = get_provider(provider_name, model_name=model_name)
    draft = provider.generate_answer(question, retrieved_chunks, audience=audience, max_words=max_words)
    citations = build_citations(retrieval["results"][: min(len(retrieval["results"]), top_k)])
    verification = verify_citations(draft.answer_text, retrieved_chunks, citations)
    created_at = utc_now()
    response = {
        "answer_id": str(uuid.uuid4()),
        "question": question,
        "answer": draft.answer_text,
        "grounding_status": verification["grounding_status"],
        "provider": draft.provider,
        "model": draft.model,
        "retrieval_mode": mode,
        "top_k": top_k,
        "paper_id": paper_id,
        "citations": citations,
        "retrieved_chunks": retrieved_chunks,
        "retrieval_metadata": {
            "expanded_query": retrieval.get("expanded_query"),
            "query_expansions": retrieval.get("query_expansions", []),
            "retrieval_strategy": retrieval.get("retrieval_strategy", "standard"),
        },
        "generation_metadata": draft.prompt_metadata,
        "warnings": warnings + draft.warnings + verification["warnings"],
        "unsupported_claims": verification["unsupported_claims"],
        "created_at": created_at.isoformat(),
    }
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
) -> dict[str, Any]:
    created_at = utc_now()
    provider = get_provider(provider_name, model_name=model_name)
    return {
        "answer_id": str(uuid.uuid4()),
        "question": question,
        "answer": "I could not answer this from the indexed TTLAB papers. Try a more specific question or index more paper chunks.",
        "grounding_status": "unsupported",
        "provider": getattr(provider, "provider", "offline_extractive"),
        "model": getattr(provider, "model", "sentence-overlap-v1"),
        "retrieval_mode": mode,
        "top_k": top_k,
        "paper_id": paper_id,
        "citations": [],
        "retrieved_chunks": [],
        "retrieval_metadata": {"expanded_query": None, "query_expansions": [], "retrieval_strategy": "standard"},
        "generation_metadata": {},
        "warnings": warnings + ["No relevant indexed TTLAB chunks were retrieved."],
        "unsupported_claims": ["No source chunks support an answer."],
        "created_at": created_at.isoformat(),
    }


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
        created_at=datetime.fromisoformat(response["created_at"]),
    )
    session.add(answer)
    session.commit()


def serialize_answer(answer: RAGAnswer) -> dict[str, Any]:
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
        "generation_metadata": {},
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


def ask_diagnostics(session: Session) -> dict[str, Any]:
    answers = list(session.exec(select(RAGAnswer)).all())
    last_answer = max((answer.created_at for answer in answers), default=None)
    return {
        "total_stored_answers": len(answers),
        "grounded_answers": sum(1 for answer in answers if answer.grounding_status == "grounded"),
        "partial_answers": sum(1 for answer in answers if answer.grounding_status == "partial"),
        "unsupported_answers": sum(1 for answer in answers if answer.grounding_status == "unsupported"),
        "default_provider": "ollama",
        "external_provider_available": external_provider_available(),
        "last_answer_timestamp": last_answer.isoformat() if last_answer else None,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ask source-grounded questions over indexed TTLAB chunks.")
    subparsers = parser.add_subparsers(dest="command")
    ask = subparsers.add_parser("ask")
    ask.add_argument("question")
    ask.add_argument("--mode", choices=["keyword", "feature_hashing", "dense", "hybrid", "semantic"], default="hybrid")
    ask.add_argument("--top-k", type=int, default=5)
    ask.add_argument("--provider", default="auto")
    ask.add_argument("--model", default=None)
    ask.add_argument("--paper-id", default=None)
    ask.add_argument("--audience", default="general")
    ask.add_argument("--max-words", type=int, default=250)
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
            persist=True,
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
