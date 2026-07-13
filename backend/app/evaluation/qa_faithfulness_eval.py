from __future__ import annotations

import hashlib
import json
import random
import re
from collections import Counter, defaultdict
from pathlib import Path
from statistics import fmean
from typing import Any, Iterable, Mapping, Sequence


BOOTSTRAP_SEED = 20260712
BOOTSTRAP_REPETITIONS = 10_000
CONFIDENCE_LEVEL = 0.95

CLAIM_SUPPORT_LABELS = {"supported", "partially_supported", "unsupported"}
CITATION_LABELS = {"correct", "partially_correct", "incorrect", "missing", "not_required"}
POINT_COVERAGE_LABELS = {"covered", "partially_covered", "not_covered"}

METRIC_DEFINITIONS: dict[str, str] = {
    "supported_claim_rate": (
        "Strict micro rate: AI-reviewed supported atomic corpus claims divided by all checkable atomic corpus claims; "
        "partially supported claims are not counted as supported."
    ),
    "citation_precision_correctness": (
        "Correct claim-to-inline-citation links divided by all reviewed claim-to-inline-citation links; partial links are "
        "not counted as correct."
    ),
    "citation_completeness": (
        "Checkable corpus claims carrying at least one inline source identifier divided by all checkable corpus claims."
    ),
    "correct_citation_completeness": (
        "Checkable corpus claims carrying at least one AI-reviewed correct inline citation divided by all checkable "
        "corpus claims."
    ),
    "answer_point_coverage": (
        "Strict micro rate: reviewed gold answer points marked covered divided by all linked answer points; partial points "
        "are not counted as covered."
    ),
    "unsupported_claim_rate": (
        "AI-reviewed unsupported atomic corpus claims divided by all checkable atomic corpus claims."
    ),
    "abstention_accuracy": (
        "Cases with the correct answer/abstain decision divided by all cases: answerable cases should answer and "
        "unanswerable cases should abstain."
    ),
    "unanswerable_abstention_rate": (
        "Judged-unanswerable cases that abstained divided by all judged-unanswerable cases."
    ),
    "returned_citation_utilization": (
        "Unique returned citation records referenced inline by at least one claim divided by all unique returned "
        "citation records. This is traceability hygiene, not entailment."
    ),
}


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(path)
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON on {path}:{line_number}: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"Expected an object on {path}:{line_number}")
        rows.append(value)
    return rows


def write_jsonl(rows: Iterable[Mapping[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(dict(row), ensure_ascii=False, sort_keys=True) + "\n")


def extract_inline_source_ids(text: str, source_map: Mapping[str, str] | None = None) -> list[str]:
    mapped: list[str] = []
    aliases = dict(source_map or {})
    for match in re.findall(r"\[([^\[\]]+)\]", text):
        for raw_value in match.split(","):
            value = raw_value.strip()
            if not value:
                continue
            # Bracketed numbers copied from a paper are bibliography markers,
            # not Ask TTLAB source identifiers. When a response-specific map
            # is available, accept only identifiers that the generator was
            # actually given.
            if source_map is not None and value not in aliases:
                continue
            source_id = aliases.get(value, value)
            if source_id not in mapped:
                mapped.append(source_id)
    return mapped


def segment_atomic_claims(
    answer_text: str,
    *,
    case_id: str,
    source_map: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Segment the deterministic extractive answer into auditable claim units.

    The segmenter intentionally treats introductory ranking language and safety
    disclaimers as non-corpus statements. It splits each evidence bullet into
    metadata and evidence units, then splits evidence only at clear sentence,
    semicolon, or contrast boundaries. Reviewers may revise a segment in either
    persisted review pass; the heuristic is not treated as a ground-truth NLI
    system.
    """

    claims: list[dict[str, Any]] = []
    non_claim_lines: list[dict[str, str]] = []
    did_abstain = _looks_like_abstention(answer_text)

    def add_claim(
        text: str,
        claim_type: str,
        source_ids: Sequence[str],
        *,
        checkable: bool = True,
        requires_citation: bool = True,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        cleaned = re.sub(r"\s+", " ", text).strip(" -:;,.\n")
        if not cleaned:
            return
        claims.append(
            {
                "claim_id": f"{case_id}-claim-{len(claims) + 1:03d}",
                "text": cleaned,
                "claim_type": claim_type,
                "checkable_corpus_claim": checkable,
                "requires_citation": requires_citation,
                "inline_source_ids": list(dict.fromkeys(source_ids)),
                "segmentation_metadata": dict(metadata or {}),
            }
        )

    for raw_line in answer_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if not line.startswith("-"):
            category = _non_claim_line_category(line)
            if category:
                non_claim_lines.append({"text": line, "category": category})
                continue
            source_ids = extract_inline_source_ids(line, source_map)
            without_refs = re.sub(r"\s*\[[^\[\]]+\]\s*", " ", line)
            for clause in split_checkable_clauses(without_refs):
                add_claim(clause, "prose_evidence", source_ids)
            continue

        source_ids = extract_inline_source_ids(line, source_map)
        body = re.sub(r"^-\s*", "", line)
        body = re.sub(r"\s*\[[^\[\]]+\]\s*$", "", body).strip()
        prefix, separator, evidence = body.partition(":")
        if not separator:
            for clause in split_checkable_clauses(body):
                add_claim(clause, "bullet_evidence", source_ids)
            continue

        prefix = prefix.strip()
        evidence = evidence.strip()
        paper_metadata = parse_paper_prefix(prefix)
        if paper_metadata:
            title = paper_metadata["title"]
            year = paper_metadata.get("year")
            authors = paper_metadata.get("authors", [])
            if year is not None:
                add_claim(
                    f'"{title}" is an indexed paper dated {year}',
                    "metadata_year",
                    source_ids,
                    metadata={"title": title, "year": year},
                )
            if authors:
                add_claim(
                    f'{", ".join(authors)} authored "{title}"',
                    "metadata_authorship",
                    source_ids,
                    metadata={"title": title, "authors": authors},
                )
        else:
            author_match = re.fullmatch(r"(.+?)", prefix)
            appearance_match = re.match(r"appears on (.+?)(?:\.|$)", evidence, flags=re.IGNORECASE)
            if author_match and appearance_match:
                author = author_match.group(1).strip()
                titles = [value.strip() for value in appearance_match.group(1).split(";") if value.strip()]
                for title in titles:
                    add_claim(
                        f'{author} authored or co-authored "{title}"',
                        "metadata_authorship",
                        source_ids,
                        metadata={"author": author, "title": title},
                    )
                continue

        for clause in split_checkable_clauses(evidence):
            add_claim(
                clause,
                "source_evidence",
                source_ids,
                metadata={"paper_title": paper_metadata.get("title") if paper_metadata else prefix},
            )

    return {
        "did_abstain": did_abstain,
        "claims": claims,
        "non_claim_lines": non_claim_lines,
        "segmenter": {
            "name": "ttlab-rule-segmenter",
            "version": "1.0.0",
            "review_required": True,
        },
    }


def parse_paper_prefix(prefix: str) -> dict[str, Any] | None:
    match = re.fullmatch(r"(?P<title>.+?)\s+\((?P<year>\d{4})\)(?:\s+-\s+(?P<authors>.+))?", prefix)
    if not match:
        return None
    authors = [value.strip() for value in (match.group("authors") or "").split(",") if value.strip()]
    return {"title": match.group("title").strip(), "year": int(match.group("year")), "authors": authors}


def split_checkable_clauses(text: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return []
    sentence_parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'])", normalized)
    clauses: list[str] = []
    for sentence in sentence_parts:
        pieces = re.split(r"\s*;\s*|,\s+(?=(?:while|whereas|but)\b)", sentence, flags=re.IGNORECASE)
        clauses.extend(piece.strip() for piece in pieces if piece.strip())
    return clauses


def _looks_like_abstention(text: str) -> bool:
    lowered = text.lower()
    patterns = (
        "i could not answer this from",
        "i could not find enough readable evidence",
        "insufficient evidence",
        "the provided sources do not support",
        "the indexed ttlab papers do not support",
    )
    return any(pattern in lowered for pattern in patterns)


def _non_claim_line_category(line: str) -> str | None:
    lowered = line.lower()
    if lowered.startswith(("based on the indexed", "based on authorship", "the retrieved chunks include")):
        return "framing"
    if lowered.startswith("the strongest matching papers are"):
        return "framing"
    if lowered.startswith(("i could not", "i did not find explicit", "the provided sources do not")):
        return "abstention_or_scope_statement"
    if "not a verified supervisor recommendation" in lowered:
        return "safety_disclaimer"
    return None


def source_overlap_suggestion(claim: Mapping[str, Any], source_texts: Sequence[str]) -> dict[str, Any]:
    """Return an auditable lexical suggestion, never a final support label."""

    claim_tokens = _tokens(str(claim.get("text") or ""))
    if not claim_tokens:
        return {"suggested_label": "unsupported", "coverage": 0.0, "method": "token_coverage_v1"}
    source_tokens = set()
    for source_text in source_texts:
        source_tokens.update(_tokens(source_text))
    coverage = len(set(claim_tokens).intersection(source_tokens)) / len(set(claim_tokens))
    if coverage >= 0.8:
        suggestion = "supported"
    elif coverage >= 0.5:
        suggestion = "partially_supported"
    else:
        suggestion = "unsupported"
    return {
        "suggested_label": suggestion,
        "coverage": round(coverage, 6),
        "method": "token_coverage_v1",
        "warning": "Lexical coverage is a reviewer aid and is not entailment ground truth.",
    }


def calculate_faithfulness_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not rows:
        raise ValueError("At least one adjudicated QA row is required")
    per_case = [_case_counts(row) for row in rows]
    aggregates = _aggregate_counts(per_case)
    metrics = _metrics_from_counts(aggregates)
    intervals = _bootstrap_metrics(per_case)
    categories: dict[str, Any] = {}
    by_category: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row, counts in zip(rows, per_case, strict=True):
        by_category[str(row.get("category") or "unknown")].append(counts)
    for category, counts in sorted(by_category.items()):
        category_aggregate = _aggregate_counts(counts)
        categories[category] = {
            "case_count": len(counts),
            "counts": category_aggregate,
            "metrics": _metrics_from_counts(category_aggregate),
        }

    taxonomy_claims: Counter[str] = Counter()
    taxonomy_cases: Counter[str] = Counter()
    for row in rows:
        case_codes: set[str] = set()
        for claim in row.get("adjudicated_claims", []):
            for code in claim.get("error_codes", []):
                taxonomy_claims[str(code)] += 1
                case_codes.add(str(code))
        for code in row.get("case_error_codes", []):
            case_codes.add(str(code))
        for code in case_codes:
            taxonomy_cases[code] += 1

    return {
        "case_count": len(rows),
        "metric_definitions": METRIC_DEFINITIONS,
        "counts": aggregates,
        "metrics": metrics,
        "confidence_intervals": intervals,
        "category_results": categories,
        "error_taxonomy": {
            "claim_occurrences": dict(sorted(taxonomy_claims.items())),
            "affected_cases": dict(sorted(taxonomy_cases.items())),
        },
        "review_consistency": review_consistency(rows),
        "limitations": [
            "The labels are two-pass AI-assisted formative judgments, not human gold judgments.",
            "The clustered bootstrap resamples the 50 QA cases and does not model silver-label or corpus-selection uncertainty.",
            "Category cohorts contain only four or five questions, so category estimates are descriptive and imprecise.",
            "Strict metrics give no credit to partial support or partial coverage; weighted supplements are reported separately.",
        ],
    }


def review_consistency(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    claim_total = claim_exact = point_total = point_exact = case_total = case_exact = 0
    for row in rows:
        creation = row.get("creation_review", {})
        verification = row.get("verification_review", {})
        create_claims = {str(item["claim_id"]): item for item in creation.get("claim_judgments", [])}
        verify_claims = {str(item["claim_id"]): item for item in verification.get("claim_judgments", [])}
        for claim_id in sorted(set(create_claims).intersection(verify_claims)):
            claim_total += 1
            if _claim_label_tuple(create_claims[claim_id]) == _claim_label_tuple(verify_claims[claim_id]):
                claim_exact += 1
        create_points = {str(item["answer_point_id"]): item for item in creation.get("answer_point_judgments", [])}
        verify_points = {str(item["answer_point_id"]): item for item in verification.get("answer_point_judgments", [])}
        for point_id in sorted(set(create_points).intersection(verify_points)):
            point_total += 1
            if create_points[point_id].get("coverage_label") == verify_points[point_id].get("coverage_label"):
                point_exact += 1
        if creation and verification:
            case_total += 1
            if creation.get("did_abstain") == verification.get("did_abstain"):
                case_exact += 1
    return {
        "reviewer_type": "ai",
        "passes": ["create", "verify_shuffled"],
        "claim_label_exact_agreement": _safe_rate(claim_exact, claim_total),
        "claim_comparisons": claim_total,
        "answer_point_exact_agreement": _safe_rate(point_exact, point_total),
        "answer_point_comparisons": point_total,
        "abstention_decision_exact_agreement": _safe_rate(case_exact, case_total),
        "case_comparisons": case_total,
        "interpretation": "Annotation consistency from two passes by the same AI reviewer; not human inter-rater reliability.",
    }


def _claim_label_tuple(value: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        value.get("support_label"),
        tuple(item.get("citation_label") for item in value.get("citation_judgments", [])),
        bool(value.get("unsupported_general_knowledge", False)),
    )


def _case_counts(row: Mapping[str, Any]) -> dict[str, Any]:
    claims = [claim for claim in row.get("adjudicated_claims", []) if claim.get("checkable_corpus_claim")]
    claim_count = len(claims)
    supported = sum(claim.get("support_label") == "supported" for claim in claims)
    partial_support = sum(claim.get("support_label") == "partially_supported" for claim in claims)
    unsupported = sum(claim.get("support_label") == "unsupported" for claim in claims)
    claims_with_citation = sum(bool(claim.get("inline_source_ids")) for claim in claims)
    claims_with_correct = 0
    citation_links = citation_correct = citation_partial = citation_incorrect = 0
    unsupported_general = 0
    used_ids: set[str] = set()
    for claim in claims:
        judgments = list(claim.get("citation_judgments", []))
        if any(item.get("citation_label") == "correct" for item in judgments):
            claims_with_correct += 1
        for item in judgments:
            label = item.get("citation_label")
            if label in {"correct", "partially_correct", "incorrect"}:
                citation_links += 1
                citation_correct += label == "correct"
                citation_partial += label == "partially_correct"
                citation_incorrect += label == "incorrect"
            source_id = item.get("source_id")
            if source_id:
                used_ids.add(str(source_id))
        unsupported_general += bool(claim.get("unsupported_general_knowledge", False))

    points = list(row.get("adjudicated_answer_points", []))
    point_count = len(points)
    points_covered = sum(point.get("coverage_label") == "covered" for point in points)
    points_partial = sum(point.get("coverage_label") == "partially_covered" for point in points)
    returned_ids = {str(value) for value in row.get("returned_citation_ids", [])}
    answerability = row.get("answerability")
    did_abstain = bool(row.get("did_abstain"))
    correct_decision = (answerability == "unanswerable" and did_abstain) or (
        answerability == "answerable" and not did_abstain
    )
    return {
        "case_id": row.get("qa_case_id"),
        "claim_count": claim_count,
        "supported_claims": supported,
        "partially_supported_claims": partial_support,
        "unsupported_claims": unsupported,
        "claims_with_citation": claims_with_citation,
        "claims_with_correct_citation": claims_with_correct,
        "citation_links": citation_links,
        "correct_citation_links": citation_correct,
        "partial_citation_links": citation_partial,
        "incorrect_citation_links": citation_incorrect,
        "unsupported_general_knowledge_claims": unsupported_general,
        "answer_point_count": point_count,
        "covered_answer_points": points_covered,
        "partially_covered_answer_points": points_partial,
        "returned_citations": len(returned_ids),
        "used_returned_citations": len(returned_ids.intersection(used_ids)),
        "case_count": 1,
        "correct_answerability_decisions": int(correct_decision),
        "unanswerable_cases": int(answerability == "unanswerable"),
        "unanswerable_abstentions": int(answerability == "unanswerable" and did_abstain),
        "answerable_cases": int(answerability == "answerable"),
        "answerable_responses": int(answerability == "answerable" and not did_abstain),
    }


def _aggregate_counts(per_case: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    keys = [key for key in per_case[0] if key != "case_id"] if per_case else []
    return {key: int(sum(int(item.get(key, 0)) for item in per_case)) for key in keys}


def _metrics_from_counts(counts: Mapping[str, int]) -> dict[str, float | None]:
    return {
        "supported_claim_rate": _safe_rate(counts.get("supported_claims", 0), counts.get("claim_count", 0)),
        "weighted_supported_claim_rate": _safe_rate(
            counts.get("supported_claims", 0) + 0.5 * counts.get("partially_supported_claims", 0),
            counts.get("claim_count", 0),
        ),
        "citation_precision_correctness": _safe_rate(
            counts.get("correct_citation_links", 0), counts.get("citation_links", 0)
        ),
        "weighted_citation_correctness": _safe_rate(
            counts.get("correct_citation_links", 0) + 0.5 * counts.get("partial_citation_links", 0),
            counts.get("citation_links", 0),
        ),
        "citation_completeness": _safe_rate(counts.get("claims_with_citation", 0), counts.get("claim_count", 0)),
        "correct_citation_completeness": _safe_rate(
            counts.get("claims_with_correct_citation", 0), counts.get("claim_count", 0)
        ),
        "answer_point_coverage": _safe_rate(
            counts.get("covered_answer_points", 0), counts.get("answer_point_count", 0)
        ),
        "weighted_answer_point_coverage": _safe_rate(
            counts.get("covered_answer_points", 0) + 0.5 * counts.get("partially_covered_answer_points", 0),
            counts.get("answer_point_count", 0),
        ),
        "unsupported_claim_rate": _safe_rate(counts.get("unsupported_claims", 0), counts.get("claim_count", 0)),
        "unsupported_general_knowledge_rate": _safe_rate(
            counts.get("unsupported_general_knowledge_claims", 0), counts.get("claim_count", 0)
        ),
        "abstention_accuracy": _safe_rate(
            counts.get("correct_answerability_decisions", 0), counts.get("case_count", 0)
        ),
        "unanswerable_abstention_rate": _safe_rate(
            counts.get("unanswerable_abstentions", 0), counts.get("unanswerable_cases", 0)
        ),
        "answerable_response_rate": _safe_rate(counts.get("answerable_responses", 0), counts.get("answerable_cases", 0)),
        "returned_citation_utilization": _safe_rate(
            counts.get("used_returned_citations", 0), counts.get("returned_citations", 0)
        ),
    }


def _bootstrap_metrics(per_case: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not per_case:
        raise ValueError("Cannot bootstrap an empty QA evaluation")
    rng = random.Random(BOOTSTRAP_SEED)
    metric_names = list(_metrics_from_counts(_aggregate_counts(per_case)))
    replicates: dict[str, list[float]] = {metric: [] for metric in metric_names}
    for _ in range(BOOTSTRAP_REPETITIONS):
        sampled = [per_case[rng.randrange(len(per_case))] for _ in range(len(per_case))]
        values = _metrics_from_counts(_aggregate_counts(sampled))
        for metric, value in values.items():
            if value is not None:
                replicates[metric].append(float(value))
    estimates = _metrics_from_counts(_aggregate_counts(per_case))
    return {
        "method": "case_cluster_percentile_bootstrap",
        "unit": "qa_case",
        "confidence_level": CONFIDENCE_LEVEL,
        "repetitions": BOOTSTRAP_REPETITIONS,
        "seed": BOOTSTRAP_SEED,
        "silver_label_uncertainty_included": False,
        "metrics": {
            metric: {
                "estimate": estimates[metric],
                "ci_lower": _percentile(values, 0.025) if values else None,
                "ci_upper": _percentile(values, 0.975) if values else None,
                "valid_replicates": len(values),
            }
            for metric, values in replicates.items()
        },
    }


def _percentile(values: Sequence[float], probability: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        raise ValueError("percentile requires values")
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _safe_rate(numerator: float | int, denominator: float | int) -> float | None:
    if not denominator:
        return None
    return round(float(numerator) / float(denominator), 6)


def _tokens(text: str) -> list[str]:
    return [token.lower() for token in re.findall(r"[a-zA-Z0-9]+", text) if len(token) > 1]
