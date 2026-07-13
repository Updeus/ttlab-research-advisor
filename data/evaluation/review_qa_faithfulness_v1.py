#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from sqlmodel import Session, select

from app.db import engine
from app.evaluation.qa_faithfulness_eval import (
    calculate_faithfulness_metrics,
    canonical_json_sha256,
    load_jsonl,
    segment_atomic_claims,
    sha256_path,
    write_jsonl,
)
from app.models import Paper


ROOT = Path(__file__).resolve().parents[2]
CASES_PATH = ROOT / "data/evaluation/qa_faithfulness_cases_v1.jsonl"
ANSWERS_PATH = ROOT / "artifacts/phase3/qa/offline_extractive_hybrid_heuristic_answers_v1.jsonl"
RAW_PATH = ROOT / "artifacts/phase3/private/qa/offline_extractive_hybrid_heuristic_raw_inputs_outputs_v1.jsonl"
LABELS_PATH = ROOT / "data/evaluation/qa_faithfulness_point_labels_v1.json"
CREATE_PATH = ROOT / "data/evaluation/qa_faithfulness_review_create_v1.jsonl"
VERIFY_PATH = ROOT / "data/evaluation/qa_faithfulness_review_verify_v1.jsonl"
FINAL_PATH = ROOT / "data/evaluation/qa_faithfulness_results_v1.jsonl"
METRICS_PATH = ROOT / "artifacts/phase3/qa/qa_faithfulness_metrics_v1.json"
MANIFEST_PATH = ROOT / "artifacts/phase3/qa/qa_faithfulness_manifest_v1.json"
CREATE_PROMPTS_PATH = ROOT / "artifacts/phase3/private/qa/review_create_prompts_v1.jsonl"
VERIFY_PROMPTS_PATH = ROOT / "artifacts/phase3/private/qa/review_verify_prompts_v1.jsonl"
PROMPT_TEMPLATE_PATH = ROOT / "artifacts/phase3/qa/qa_review_prompt_template_v1.txt"
SHUFFLE_SEED = 20260713

PROMPT_TEMPLATE = """You are codex-ai-review performing an AI-assisted formative QA audit.
Inspect the exact answer, each atomic claim, each inline source identifier, the structured citation, the cited chunk,
the extracted PDF page text, and every linked answer point. For each checkable claim, label source support as
supported, partially_supported, or unsupported; label each claim-citation link as correct, partially_correct,
incorrect, or missing; identify unsupported general knowledge; and record a concise source-specific rationale.
For each answer point, label covered, partially_covered, or not_covered. Judge abstention against the reviewed
answerability label. Do not infer facts from model memory. reviewer_type must remain ai. This is not human review.
"""


def now() -> str:
    return datetime.now(UTC).isoformat()


def build_reviews() -> dict[str, Any]:
    cases = {row["qa_case_id"]: row for row in load_jsonl(CASES_PATH)}
    answers = {row["qa_case_id"]: row for row in load_jsonl(ANSWERS_PATH)}
    raw_rows = {row["qa_case_id"]: row for row in load_jsonl(RAW_PATH)}
    labels = json.loads(LABELS_PATH.read_text(encoding="utf-8"))
    if set(cases) != set(answers) or set(cases) != set(raw_rows):
        raise ValueError("Cases, answers, and private source records do not have identical IDs")
    point_ids = {point["answer_point_id"] for case in cases.values() for point in case["answer_points"]}
    for pass_name in ("creation_pass", "verification_pass"):
        label_ids = set(labels[pass_name]["labels"])
        if label_ids != point_ids:
            raise ValueError(
                f"{pass_name} point-label coverage mismatch missing={sorted(point_ids-label_ids)} extra={sorted(label_ids-point_ids)}"
            )

    PROMPT_TEMPLATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROMPT_TEMPLATE_PATH.write_text(PROMPT_TEMPLATE, encoding="utf-8")
    create_order = sorted(cases)
    verify_order = list(create_order)
    random.Random(SHUFFLE_SEED).shuffle(verify_order)

    with Session(engine) as session:
        create_rows, create_prompts = _review_pass(
            session,
            order=create_order,
            cases=cases,
            answers=answers,
            raw_rows=raw_rows,
            label_config=labels,
            pass_name="creation_pass",
            review_pass="create",
        )
        verify_rows, verify_prompts = _review_pass(
            session,
            order=verify_order,
            cases=cases,
            answers=answers,
            raw_rows=raw_rows,
            label_config=labels,
            pass_name="verification_pass",
            review_pass="verify_shuffled",
        )

    write_jsonl(create_rows, CREATE_PATH)
    write_jsonl(verify_rows, VERIFY_PATH)
    write_jsonl(create_prompts, CREATE_PROMPTS_PATH)
    write_jsonl(verify_prompts, VERIFY_PROMPTS_PATH)

    create_by_id = {row["qa_case_id"]: row for row in create_rows}
    verify_by_id = {row["qa_case_id"]: row for row in verify_rows}
    final_rows = []
    for case_id in sorted(cases):
        case = cases[case_id]
        answer = answers[case_id]
        creation = create_by_id[case_id]
        verification = verify_by_id[case_id]
        claim_disagreements = _claim_disagreements(creation, verification)
        point_disagreements = _point_disagreements(creation, verification)
        final_rows.append(
            {
                "qa_case_id": case_id,
                "retrieval_case_id": case["retrieval_case_id"],
                "question": case["question"],
                "category": case["category"],
                "answerability": case["answerability"],
                "split": case["split"],
                "answer": answer["answer"],
                "answer_sha256": answer["answer_sha256"],
                "provider": answer["provider"],
                "model": answer["model"],
                "retrieval_mode": answer["retrieval_mode"],
                "top_k": answer["top_k"],
                "returned_citation_ids": answer["returned_citation_ids"],
                "did_abstain": verification["did_abstain"],
                "creation_review": _public_pass(creation),
                "verification_review": _public_pass(verification),
                "adjudicated_claims": verification["claim_judgments"],
                "adjudicated_answer_points": verification["answer_point_judgments"],
                "case_error_codes": verification["case_error_codes"],
                "disagreements": {
                    "claim_ids": claim_disagreements,
                    "answer_point_ids": point_disagreements,
                    "resolution": "Shuffled verification pass retained as final AI-assisted formative judgment.",
                },
                "review_status": "ai_reviewed_formative",
                "reviewer_type": "ai",
                "reviewer_id": "codex-ai-review",
                "reviewed_at": verification["reviewed_at"],
            }
        )
    write_jsonl(final_rows, FINAL_PATH)
    metrics = calculate_faithfulness_metrics(final_rows)
    metrics.update(
        {
            "experiment_id": "ttlab-qa-faithfulness-offline-extractive-hybrid-v1",
            "generated_at": now(),
            "evaluation_status": "ai_assisted_formative",
            "reviewer_type": "ai",
            "answer_provider": "offline_extractive",
            "answer_model": "sentence-overlap-v1",
            "retrieval_mode": "hybrid_current_untuned_heuristic",
        }
    )
    METRICS_PATH.write_text(json.dumps(metrics, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    manifest = _manifest(labels, final_rows, metrics)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest


def _review_pass(
    session: Session,
    *,
    order: Sequence[str],
    cases: Mapping[str, Mapping[str, Any]],
    answers: Mapping[str, Mapping[str, Any]],
    raw_rows: Mapping[str, Mapping[str, Any]],
    label_config: Mapping[str, Any],
    pass_name: str,
    review_pass: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    prompts: list[dict[str, Any]] = []
    reviewed_at = label_config[pass_name]["reviewed_at"]
    for position, case_id in enumerate(order, start=1):
        case = cases[case_id]
        answer = answers[case_id]
        raw = raw_rows[case_id]
        segmentation = segment_atomic_claims(answer["answer"], case_id=case_id, source_map=answer["source_map"])
        prompt_payload = {
            "instructions": PROMPT_TEMPLATE,
            "qa_case": case,
            "answer": answer["answer"],
            "atomic_claims": segmentation["claims"],
            "returned_citations": answer["citations"],
            "source_records": raw["source_records"],
        }
        prompt_hash = canonical_json_sha256(prompt_payload)
        claim_judgments = [
            _judge_claim(session, claim, case, answer, raw)
            for claim in segmentation["claims"]
        ]
        point_judgments = [
            _judge_point(
                point,
                label_config[pass_name]["labels"][point["answer_point_id"]],
                claim_judgments,
                case,
                answer,
            )
            for point in case["answer_points"]
        ]
        case_errors = _case_errors(case, answer, point_judgments)
        rows.append(
            {
                "qa_case_id": case_id,
                "review_pass": review_pass,
                "shuffled_position": position if review_pass == "verify_shuffled" else None,
                "shuffle_seed": SHUFFLE_SEED if review_pass == "verify_shuffled" else None,
                "reviewer_id": "codex-ai-review",
                "reviewer_type": "ai",
                "provider": label_config["provider"],
                "model": label_config["model"],
                "model_digest": label_config["model_digest"],
                "model_identity_limitation": label_config["model_identity_limitation"],
                "reviewed_at": reviewed_at,
                "raw_prompt_sha256": prompt_hash,
                "raw_prompt_path": str(
                    (CREATE_PROMPTS_PATH if review_pass == "create" else VERIFY_PROMPTS_PATH).relative_to(ROOT)
                ),
                "did_abstain": bool(segmentation["did_abstain"]),
                "claim_judgments": claim_judgments,
                "answer_point_judgments": point_judgments,
                "case_error_codes": case_errors,
                "source_inspection_scope": (
                    "Every claim-to-citation link was resolved to the exact retrieved chunk and extracted page text; "
                    "metadata claims were also checked against the frozen Paper record."
                ),
            }
        )
        prompts.append(
            {
                "qa_case_id": case_id,
                "review_pass": review_pass,
                "position": position,
                "prompt_sha256": prompt_hash,
                "prompt": prompt_payload,
            }
        )
    return rows, prompts


def _judge_claim(
    session: Session,
    claim: Mapping[str, Any],
    case: Mapping[str, Any],
    answer: Mapping[str, Any],
    raw: Mapping[str, Any],
) -> dict[str, Any]:
    source_records = {str(row["chunk_id"]): row for row in raw["source_records"]}
    citation_by_id = {str(row["chunk_id"]): row for row in answer["citations"]}
    source_ids = [str(value) for value in claim["inline_source_ids"]]
    checkable = not _nonpropositional_fragment(str(claim["text"]))
    claim_type = str(claim["claim_type"])
    support_label = "unsupported"
    rationale = "No source passage or frozen metadata record supports the claim."

    if claim_type.startswith("metadata_"):
        support_label, rationale = _metadata_support(session, claim)
    else:
        coverages = [
            _token_coverage(str(claim["text"]), str(source_records[source_id].get("chunk_text") or ""))
            for source_id in source_ids
            if source_id in source_records
        ]
        best = max(coverages, default=0.0)
        if best >= 0.8:
            support_label = "supported"
            rationale = "The atomic wording is directly present in the resolved retrieved chunk and its extracted PDF page text."
        elif best >= 0.5:
            support_label = "partially_supported"
            rationale = "The resolved source supports part, but not all, of the atomic wording."

    citation_judgments: list[dict[str, Any]] = []
    if not source_ids:
        citation_judgments.append(
            {
                "source_id": None,
                "citation_label": "missing",
                "paper_id": None,
                "chunk_id": None,
                "page_start": None,
                "page_end": None,
                "rationale": "The checkable corpus claim has no inline Ask TTLAB source identifier.",
            }
        )
    for source_id in source_ids:
        source = source_records.get(source_id)
        citation = citation_by_id.get(source_id)
        if source is None or citation is None:
            label = "incorrect"
            citation_rationale = "The inline identifier does not resolve to a returned citation and inspected source record."
        elif claim_type.startswith("metadata_"):
            desired_title = str(claim.get("segmentation_metadata", {}).get("title") or "")
            if _normalized(desired_title) != _normalized(str(source.get("paper_title") or "")):
                label = "incorrect"
                citation_rationale = "The source identifier resolves to a different paper than the metadata claim."
            elif _metadata_visible_on_pages(claim, source.get("pages", [])):
                label = "correct"
                citation_rationale = "The cited paper and extracted cited page directly show the claimed metadata."
            else:
                label = "partially_correct"
                citation_rationale = (
                    "The identifier resolves to the correct paper, but the cited page does not directly display all claimed metadata."
                )
        else:
            coverage = _token_coverage(str(claim["text"]), str(source.get("chunk_text") or ""))
            if coverage >= 0.8:
                label = "correct"
                citation_rationale = "The cited chunk/page directly contains the atomic answer wording."
            elif coverage >= 0.5:
                label = "partially_correct"
                citation_rationale = "The cited chunk/page supports only part of the claim."
            else:
                label = "incorrect"
                citation_rationale = "The cited chunk/page does not support the claim."
        citation_judgments.append(
            {
                "source_id": source_id,
                "citation_label": label,
                "paper_id": source.get("paper_id") if source else None,
                "chunk_id": source_id if source else None,
                "page_start": source.get("page_start") if source else None,
                "page_end": source.get("page_end") if source else None,
                "rationale": citation_rationale,
            }
        )

    error_codes: list[str] = []
    cited_papers = {row.get("paper_id") for row in citation_judgments if row.get("paper_id")}
    if cited_papers and not cited_papers.intersection(set(case["relevant_paper_ids"])) and case["answerability"] == "answerable":
        error_codes.append("off_topic_supported_claim")
    if not checkable:
        error_codes.append("nonpropositional_extractive_fragment")
    if support_label == "unsupported":
        error_codes.append("unsupported_claim")
    if any(row["citation_label"] == "incorrect" for row in citation_judgments):
        error_codes.append("incorrect_citation")
    return {
        **claim,
        "checkable_corpus_claim": checkable,
        "support_label": support_label,
        "citation_judgments": citation_judgments,
        "unsupported_general_knowledge": support_label == "unsupported" and not source_ids,
        "source_inspection_rationale": rationale,
        "error_codes": sorted(set(error_codes)),
    }


def _metadata_support(session: Session, claim: Mapping[str, Any]) -> tuple[str, str]:
    meta = claim.get("segmentation_metadata", {})
    title = str(meta.get("title") or "")
    papers = list(session.exec(select(Paper)).all())
    paper = next((row for row in papers if _normalized(row.title) == _normalized(title)), None)
    if paper is None:
        return "unsupported", "No frozen Paper record matches the parsed title."
    if claim["claim_type"] == "metadata_year":
        matches = paper.year == meta.get("year")
    else:
        claimed_authors = [str(value) for value in meta.get("authors", [])]
        if meta.get("author"):
            claimed_authors.append(str(meta["author"]))
        matches = bool(claimed_authors) and all(
            any(_normalized(author) == _normalized(actual) for actual in paper.authors)
            for author in claimed_authors
        )
    if matches:
        return "supported", "The claim matches the frozen paper title/year/authorship metadata record."
    return "unsupported", "The parsed metadata claim conflicts with the frozen Paper record."


def _metadata_visible_on_pages(claim: Mapping[str, Any], pages: Sequence[Mapping[str, Any]]) -> bool:
    text = " ".join(str(page.get("text") or "") for page in pages)
    meta = claim.get("segmentation_metadata", {})
    if claim["claim_type"] == "metadata_year":
        return str(meta.get("year")) in text and _token_coverage(str(meta.get("title") or ""), text) >= 0.7
    names = [str(value) for value in meta.get("authors", [])]
    if meta.get("author"):
        names.append(str(meta["author"]))
    return bool(names) and all(_last_name(name) in _normalized(text) for name in names)


def _judge_point(
    point: Mapping[str, Any],
    label: str,
    claims: Sequence[Mapping[str, Any]],
    case: Mapping[str, Any],
    answer: Mapping[str, Any],
) -> dict[str, Any]:
    relevant_claims = []
    point_papers = set(point["paper_ids"])
    for claim in claims:
        cited_papers = {row.get("paper_id") for row in claim["citation_judgments"] if row.get("paper_id")}
        if cited_papers.intersection(point_papers):
            relevant_claims.append(str(claim["claim_id"]))
    if label == "covered":
        rationale = "The answer explicitly supplies the substantive requested point using a linked relevant-paper claim."
    elif label == "partially_covered":
        rationale = "The answer supplies related relevant-paper evidence but omits one or more required elements of the point."
    else:
        rationale = "No answer claim supplies the required value, method detail, venue, comparison, or corpus-boundary decision."
    return {
        **point,
        "coverage_label": label,
        "linked_answer_claim_ids": relevant_claims,
        "rationale": rationale,
    }


def _case_errors(
    case: Mapping[str, Any], answer: Mapping[str, Any], point_judgments: Sequence[Mapping[str, Any]]
) -> list[str]:
    errors: list[str] = []
    if case["answerability"] == "unanswerable":
        if not answer["did_abstain"]:
            errors.extend(["failure_to_abstain_on_corpus_absence", "unanswerable_false_positive"])
        return errors
    labels = [point["coverage_label"] for point in point_judgments]
    if labels and all(label == "not_covered" for label in labels):
        errors.append("answer_point_omission")
    if any(label != "covered" for label in labels):
        errors.append("incomplete_answer")
    returned_papers = {row["paper_id"] for row in answer["retrieved_sources"]}
    relevant_papers = set(case["relevant_paper_ids"])
    if not returned_papers.intersection(relevant_papers):
        errors.append("relevant_paper_retrieval_miss")
    else:
        gold_chunks = {row["chunk_id"] for row in case["supporting_sources"]}
        returned_chunks = {row["chunk_id"] for row in answer["retrieved_sources"]}
        used_chunks = set(answer["source_map"].values()).intersection(
            source_id
            for claim in answer["segmentation"]["claims"]
            for source_id in claim["inline_source_ids"]
        )
        if gold_chunks and not gold_chunks.intersection(returned_chunks):
            errors.append("within_paper_evidence_retrieval_miss")
        elif gold_chunks and not gold_chunks.intersection(used_chunks):
            errors.append("answer_sentence_selection_miss")
    if returned_papers - relevant_papers:
        errors.append("off_topic_retrieval")
    return sorted(set(errors))


def _nonpropositional_fragment(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", text).strip().lower()
    if len(normalized.split()) < 5:
        return True
    if re.search(r"\b(?:of|for|the|a|an|and|or|to|with|which|that)$", normalized):
        return True
    if normalized in {"limitations and future work this study", "conclusion this research"}:
        return True
    return False


def _token_coverage(left: str, right: str) -> float:
    left_tokens = set(re.findall(r"[a-z0-9]+", _normalized(left)))
    right_tokens = set(re.findall(r"[a-z0-9]+", _normalized(right)))
    return len(left_tokens.intersection(right_tokens)) / len(left_tokens) if left_tokens else 0.0


def _normalized(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def _last_name(name: str) -> str:
    tokens = _normalized(name).split()
    return tokens[-1] if tokens else ""


def _public_pass(row: Mapping[str, Any]) -> dict[str, Any]:
    return {key: row[key] for key in row if key != "case_error_codes"}


def _claim_disagreements(left: Mapping[str, Any], right: Mapping[str, Any]) -> list[str]:
    left_by_id = {row["claim_id"]: row for row in left["claim_judgments"]}
    right_by_id = {row["claim_id"]: row for row in right["claim_judgments"]}
    return [
        claim_id
        for claim_id in sorted(left_by_id)
        if (
            left_by_id[claim_id]["support_label"],
            [item["citation_label"] for item in left_by_id[claim_id]["citation_judgments"]],
        )
        != (
            right_by_id[claim_id]["support_label"],
            [item["citation_label"] for item in right_by_id[claim_id]["citation_judgments"]],
        )
    ]


def _point_disagreements(left: Mapping[str, Any], right: Mapping[str, Any]) -> list[str]:
    left_by_id = {row["answer_point_id"]: row["coverage_label"] for row in left["answer_point_judgments"]}
    right_by_id = {row["answer_point_id"]: row["coverage_label"] for row in right["answer_point_judgments"]}
    return [point_id for point_id in sorted(left_by_id) if left_by_id[point_id] != right_by_id[point_id]]


def _manifest(labels: Mapping[str, Any], rows: Sequence[Mapping[str, Any]], metrics: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "dataset_id": "ttlab-qa-faithfulness-v1",
        "status": "executed_and_validated",
        "generated_at": now(),
        "case_count": len(rows),
        "answerable_case_count": sum(row["answerability"] == "answerable" for row in rows),
        "unanswerable_case_count": sum(row["answerability"] == "unanswerable" for row in rows),
        "review": {
            "reviewer_id": labels["reviewer_id"],
            "reviewer_type": labels["reviewer_type"],
            "provider": labels["provider"],
            "model": labels["model"],
            "model_digest": labels["model_digest"],
            "model_identity_limitation": labels["model_identity_limitation"],
            "passes": ["create", "verify_shuffled"],
            "shuffle_seed": SHUFFLE_SEED,
            "adjudication_policy": labels["adjudication_policy"],
        },
        "files": {
            str(path.relative_to(ROOT)): sha256_path(path)
            for path in (
                CASES_PATH,
                ROOT / "data/evaluation/qa_faithfulness_cases_v1.schema.json",
                ANSWERS_PATH,
                ROOT / "artifacts/phase3/qa/offline_extractive_hybrid_heuristic_run_manifest_v1.json",
                LABELS_PATH,
                CREATE_PATH,
                VERIFY_PATH,
                FINAL_PATH,
                ROOT / "data/evaluation/qa_faithfulness_results_v1.schema.json",
                ROOT / "data/evaluation/validate_qa_faithfulness_v1.py",
                ROOT / "data/evaluation/run_qa_faithfulness_v1.py",
                Path(__file__).resolve(),
                ROOT / "backend/app/evaluation/qa_faithfulness_eval.py",
                ROOT / "backend/tests/test_qa_faithfulness_evaluation.py",
                METRICS_PATH,
                PROMPT_TEMPLATE_PATH,
                CREATE_PROMPTS_PATH,
                VERIFY_PROMPTS_PATH,
                ROOT / "artifacts/phase3/qa/ollama_availability_v1.json",
            )
        },
        "raw_prompt_policy": (
            "Exact full-text review prompts are retained locally under artifacts/phase3/private and hash-linked here; "
            "they are excluded from the sanitized release to avoid redistributing full third-party paper text."
        ),
        "headline_metrics": metrics["metrics"],
        "ollama_comparison": {
            "status": "not_run_service_unavailable",
            "evidence_path": "artifacts/phase3/qa/ollama_availability_v1.json",
            "claim": "No Ollama quality, latency, model-tag, digest, or quantization comparison is reported.",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Create the two-pass AI-assisted TTLAB QA faithfulness review.")
    parser.parse_args()
    result = build_reviews()
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
