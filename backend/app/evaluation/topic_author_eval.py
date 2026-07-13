"""Reproducible AI-silver evaluation of controlled topics and author links."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import random
import re
import shutil
import subprocess
import tempfile
from collections import Counter, defaultdict
from datetime import UTC, datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from sqlmodel import Session, create_engine, select

from app.indexing.embedder import cosine_similarity, get_provider, normalize
from app.ingestion.metadata_cleaner import active_author_for_name, normalize_author_key
from app.intelligence.topic_explorer import (
    TOPIC_RULES,
    author_detail,
    eligible_papers,
    normalize_topic,
    publication_topic_chunks,
    rebuild_topic_index,
    topic_candidates_for_paper,
)
from app.models import Author, AuthorAlias, AuthorTopic, Paper, PaperTopic

ROOT = Path(__file__).resolve().parents[3]
DATASET = ROOT / "data/evaluation/topic_author_silver_v1.jsonl"
SILVER_MANIFEST = ROOT / "data/evaluation/topic_author_silver_v1.manifest.json"
DATABASE = ROOT / "data/papers.db"
DENSE_INDEX = ROOT / "data/indexes/dense_embeddings.json"
DENSE_MANIFEST = ROOT / "data/indexes/dense_embeddings.manifest.json"
OUTPUT_DIR = ROOT / "artifacts/phase4/topic_author"
UNKNOWN = "other/unknown"
BOOTSTRAP_SEED = 94017
BOOTSTRAP_SAMPLES = 2000


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def label_universe(cases: list[dict[str, Any]]) -> list[str]:
    return sorted({label for case in cases for label in case["final_labels"]} | {UNKNOWN})


def expected_labels(case: dict[str, Any]) -> set[str]:
    labels = set(case["final_labels"])
    return labels or {UNKNOWN}


def lexical_predictions(session: Session, cases: list[dict[str, Any]]) -> tuple[dict[str, set[str]], dict[str, dict[str, float]]]:
    predictions: dict[str, set[str]] = {}
    scores: dict[str, dict[str, float]] = {}
    for case in cases:
        paper = session.get(Paper, case["paper_id"])
        if paper is None:
            raise RuntimeError(f"Missing paper {case['paper_id']}")
        candidates = topic_candidates_for_paper(session, paper)
        ranked = sorted(candidates.values(), key=lambda item: (-item.score, item.normalized_name))[:8]
        labels = {item.normalized_name for item in ranked}
        predictions[case["case_id"]] = labels or {UNKNOWN}
        scores[case["case_id"]] = {item.normalized_name: round(item.score, 6) for item in ranked}
    return predictions, scores


def dense_predictions(
    session: Session,
    cases: list[dict[str, Any]],
) -> tuple[dict[str, set[str]], dict[str, dict[str, float]], dict[str, Any]]:
    manifest = json.loads(DENSE_MANIFEST.read_text(encoding="utf-8"))
    silver_manifest = json.loads(SILVER_MANIFEST.read_text(encoding="utf-8"))
    if manifest["corpus"]["snapshot_hash"] != silver_manifest["corpus"]["snapshot_hash"]:
        raise RuntimeError("Dense index and silver corpus snapshots differ")
    if sha256_file(DENSE_INDEX) != manifest["index"]["sha256"]:
        raise RuntimeError("Dense index checksum differs from its authoritative manifest")
    payload = json.loads(DENSE_INDEX.read_text(encoding="utf-8"))
    vectors = {record["chunk_id"]: record["embedding"] for record in payload["records"]}
    provider = get_provider("dense", allow_model_download=False, device="cpu")
    rules = {
        normalize_topic(name)[0]: terms
        for name, terms in TOPIC_RULES
        if normalize_topic(name) is not None
    }
    labels = sorted(rules)
    prototypes = [
        f"Academic publication whose principal topic is {label}. Controlled vocabulary examples: {', '.join(rules[label])}."
        for label in labels
    ]
    prototype_vectors = dict(zip(labels, provider.embed_many(prototypes), strict=True))
    all_scores: dict[str, dict[str, float]] = {}
    for case in cases:
        paper = session.get(Paper, case["paper_id"])
        if paper is None:
            raise RuntimeError(f"Missing paper {case['paper_id']}")
        chunk_ids = [chunk.chunk_id for chunk in publication_topic_chunks(session, paper.paper_id)]
        source_vectors = [vectors[chunk_id] for chunk_id in chunk_ids if chunk_id in vectors]
        if not source_vectors:
            raise RuntimeError(f"No pinned dense vectors for {paper.paper_id}")
        centroid = normalize([
            sum(vector[index] for vector in source_vectors) / len(source_vectors)
            for index in range(len(source_vectors[0]))
        ])
        all_scores[case["case_id"]] = {
            label: cosine_similarity(centroid, prototype_vectors[label]) for label in labels
        }

    dev = [case for case in cases if case["split"] == "dev"]
    trials: list[dict[str, Any]] = []
    for step in range(20, 61):
        threshold = step / 100
        predictions = predictions_from_scores(all_scores, threshold=threshold, max_labels=6)
        result = calculate_metrics(dev, predictions, labels=label_universe(cases), include_per_label=False)
        trials.append({"threshold": threshold, "micro_f1": result["micro"]["f1"], "macro_f1": result["macro"]["f1"], "coverage": result["coverage"]})
    selected = max(trials, key=lambda row: (row["micro_f1"], row["macro_f1"], row["threshold"]))
    predictions = predictions_from_scores(all_scores, threshold=selected["threshold"], max_labels=6)
    rounded_scores = {
        case_id: dict(sorted(((label, round(score, 6)) for label, score in values.items()), key=lambda item: item[1], reverse=True)[:10])
        for case_id, values in all_scores.items()
    }
    config = {
        "method": "pinned_dense_primary-source-centroid_to_label-prototype_cosine",
        "model_name": manifest["configuration"]["model_name"],
        "model_revision": manifest["configuration"]["model_revision"],
        "model_artifact_sha256": manifest["configuration"]["model_artifact_sha256"],
        "dense_index_sha256": manifest["index"]["sha256"],
        "dense_manifest_sha256": sha256_file(DENSE_MANIFEST),
        "threshold_selection": "max dev micro-F1; ties macro-F1 then higher threshold",
        "selected_threshold": selected["threshold"],
        "max_labels": 6,
        "threshold_trials": trials,
        "test_labels_not_used_for_selection": True,
    }
    return predictions, rounded_scores, config


def predictions_from_scores(scores: dict[str, dict[str, float]], *, threshold: float, max_labels: int) -> dict[str, set[str]]:
    predictions: dict[str, set[str]] = {}
    for case_id, values in scores.items():
        ranked = sorted(values.items(), key=lambda item: (-item[1], item[0]))
        labels = {label for label, score in ranked[:max_labels] if score >= threshold}
        predictions[case_id] = labels or {UNKNOWN}
    return predictions


def prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1


def wilson(successes: int, trials: int, z: float = 1.959963984540054) -> list[float | None]:
    if trials == 0:
        return [None, None]
    p = successes / trials
    denominator = 1 + z * z / trials
    centre = (p + z * z / (2 * trials)) / denominator
    radius = z * math.sqrt((p * (1 - p) + z * z / (4 * trials)) / trials) / denominator
    return [max(0.0, centre - radius), min(1.0, centre + radius)]


def calculate_metrics(
    cases: list[dict[str, Any]],
    predictions: dict[str, set[str]],
    *,
    labels: list[str],
    include_per_label: bool = True,
) -> dict[str, Any]:
    counts = {label: {"tp": 0, "fp": 0, "fn": 0, "tn": 0} for label in labels}
    exact = 0
    predicted_non_unknown = 0
    for case in cases:
        expected = expected_labels(case)
        predicted = predictions[case["case_id"]]
        exact += expected == predicted
        predicted_non_unknown += predicted != {UNKNOWN}
        for label in labels:
            in_expected, in_predicted = label in expected, label in predicted
            key = "tp" if in_expected and in_predicted else "fp" if in_predicted else "fn" if in_expected else "tn"
            counts[label][key] += 1
    total_tp = sum(row["tp"] for row in counts.values())
    total_fp = sum(row["fp"] for row in counts.values())
    total_fn = sum(row["fn"] for row in counts.values())
    micro = prf(total_tp, total_fp, total_fn)
    label_prf = {label: prf(row["tp"], row["fp"], row["fn"]) for label, row in counts.items()}
    supported_labels = [label for label in labels if counts[label]["tp"] + counts[label]["fn"] > 0]
    macro = tuple(
        sum(label_prf[label][index] for label in supported_labels) / len(supported_labels)
        for index in range(3)
    )
    macro_all = tuple(sum(values[index] for values in label_prf.values()) / len(labels) for index in range(3))
    result: dict[str, Any] = {
        "case_count": len(cases),
        "micro": {"precision": micro[0], "recall": micro[1], "f1": micro[2]},
        "macro": {"precision": macro[0], "recall": macro[1], "f1": macro[2]},
        "macro_supported_label_count": len(supported_labels),
        "macro_all_vocabulary": {"precision": macro_all[0], "recall": macro_all[1], "f1": macro_all[2]},
        "exact_match": exact / len(cases) if cases else 0.0,
        "coverage": predicted_non_unknown / len(cases) if cases else 0.0,
    }
    if include_per_label:
        result["per_label"] = {
            label: {
                **counts[label],
                "precision": label_prf[label][0],
                "recall": label_prf[label][1],
                "f1": label_prf[label][2],
                "precision_wilson_95_ci": wilson(counts[label]["tp"], counts[label]["tp"] + counts[label]["fp"]),
                "recall_wilson_95_ci": wilson(counts[label]["tp"], counts[label]["tp"] + counts[label]["fn"]),
            }
            for label in labels
        }
    return result


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] * (upper - position) + ordered[upper] * (position - lower)


def add_bootstrap_ci(cases: list[dict[str, Any]], predictions: dict[str, set[str]], metrics: dict[str, Any], labels: list[str], seed_offset: int) -> None:
    rng = random.Random(BOOTSTRAP_SEED + seed_offset)
    samples: dict[str, list[float]] = defaultdict(list)
    for _ in range(BOOTSTRAP_SAMPLES):
        draw = [rng.choice(cases) for _ in cases]
        result = calculate_metrics(draw, predictions, labels=labels, include_per_label=False)
        for group in ("micro", "macro"):
            for metric in ("precision", "recall", "f1"):
                samples[f"{group}.{metric}"].append(result[group][metric])
        samples["coverage"].append(result["coverage"])
        samples["exact_match"].append(result["exact_match"])
    metrics["bootstrap_95_ci"] = {
        key: [percentile(values, 0.025), percentile(values, 0.975)] for key, values in samples.items()
    }
    metrics["bootstrap_config"] = {"samples": BOOTSTRAP_SAMPLES, "seed": BOOTSTRAP_SEED + seed_offset, "unit": "paper case"}


def classify_error(method: str, false_positive: bool, label: str) -> str:
    if label == UNKNOWN:
        return "controlled_vocabulary_boundary"
    if method == "dense":
        return "prototype_semantic_overreach" if false_positive else "prototype_threshold_or_rank_cap"
    if false_positive:
        return "ambiguous_lexeme_or_incidental_primary_section"
    return "lexical_gap_or_insufficient_repeat_evidence"


def raw_prediction_rows(cases: list[dict[str, Any]], method: str, predictions: dict[str, set[str]], scores: dict[str, dict[str, float]]) -> list[dict[str, Any]]:
    rows = []
    for case in cases:
        expected = expected_labels(case)
        predicted = predictions[case["case_id"]]
        fp, fn = sorted(predicted - expected), sorted(expected - predicted)
        rows.append({
            "case_id": case["case_id"], "split": case["split"], "paper_id": case["paper_id"],
            "method": method, "expected": sorted(expected), "predicted": sorted(predicted),
            "scores": scores.get(case["case_id"], {}), "exact_match": expected == predicted,
            "false_positives": [{"label": label, "error_type": classify_error(method, True, label)} for label in fp],
            "false_negatives": [{"label": label, "error_type": classify_error(method, False, label)} for label in fn],
            "source_evidence": [item.get("chunk_id") or item.get("locator") for item in case["evidence"]],
            "reviewer_type": "ai", "human_validation": False,
        })
    return rows


def possible_identity_pairs(authors: list[Author]) -> list[dict[str, Any]]:
    groups: dict[str, list[Author]] = defaultdict(list)
    for author in authors:
        tokens = normalize_author_key(author.canonical_name or author.name).split()
        if tokens:
            groups[tokens[-1]].append(author)
    pairs = []
    for surname, group in groups.items():
        for index, left in enumerate(group):
            for right in group[index + 1:]:
                left_tokens = normalize_author_key(left.canonical_name or left.name).split()
                right_tokens = normalize_author_key(right.canonical_name or right.name).split()
                if not left_tokens or not right_tokens or left_tokens[0][0] != right_tokens[0][0]:
                    continue
                left_first, right_first = left_tokens[0], right_tokens[0]
                initial_or_near_variant = (
                    min(len(left_first), len(right_first)) == 1
                    or SequenceMatcher(None, left_first, right_first).ratio() >= 0.84
                )
                if initial_or_near_variant:
                    pairs.append({
                        "surname": surname,
                        "left": {"author_id": left.id, "name": left.canonical_name or left.name},
                        "right": {"author_id": right.id, "name": right.canonical_name or right.name},
                        "status": "AUTHOR INPUT REQUIRED; candidate only, not merged",
                    })
    return pairs


def audit_authors(session: Session) -> dict[str, Any]:
    authors = list(session.exec(select(Author).order_by(Author.id)).all())
    active = [author for author in authors if author.identity_status not in {"merged", "invalid"}]
    aliases = list(session.exec(select(AuthorAlias)).all())
    aliases_by_normalized: dict[str, set[int]] = defaultdict(set)
    for alias in aliases:
        aliases_by_normalized[alias.normalized_alias].add(alias.canonical_author_id)
    collisions = {key: sorted(value) for key, value in aliases_by_normalized.items() if len(value) > 1}
    eligible_ids = {paper.paper_id for paper in eligible_papers(session)}
    paper_links = list(session.exec(select(PaperTopic)).all())
    author_links = list(session.exec(select(AuthorTopic)).all())
    excluded_topic_links = [link.link_id for link in paper_links if link.paper_id not in eligible_ids]
    evidence_leakage: list[dict[str, Any]] = []
    authorship_mismatch: list[dict[str, Any]] = []
    for link in author_links:
        for evidence in link.evidence_json:
            paper_id = evidence.get("paper_id")
            if paper_id not in eligible_ids:
                evidence_leakage.append({"link_id": link.link_id, "paper_id": paper_id})
                continue
            paper = session.get(Paper, paper_id)
            resolved_ids = {
                identity.id
                for name in (paper.authors if paper else [])
                if (identity := active_author_for_name(session, name)) is not None
            }
            if link.author_id not in resolved_ids:
                authorship_mismatch.append({"link_id": link.link_id, "paper_id": paper_id})
    unresolved_author_names = sorted(author.canonical_name or author.name for author in active if author.identity_status == "unresolved")
    output_claim_violations: list[dict[str, Any]] = []
    author_records: list[dict[str, Any]] = []
    for author in active:
        detail = author_detail(session, author.id or -1)
        if detail is None:
            continue
        summary = detail["potential_expertise_summary"]
        if detail["papers"] and (
            "bibliographic evidence only" not in summary
            or "does not establish broader expertise" not in summary
            or re.search(r"\b(is an expert|available for|recommended supervisor|endorsed researcher)\b", summary, re.I)
        ):
            output_claim_violations.append({"author_id": author.id, "summary": summary})
        author_records.append({
            "author_id": author.id,
            "canonical_name": author.canonical_name or author.name,
            "identity_status": author.identity_status,
            "identity_review_status": author.identity_review_status,
            "aliases": detail["aliases"],
            "eligible_paper_ids": [paper["paper_id"] for paper in detail["papers"]],
            "publication_topic_ids": [topic["topic_id"] for topic in detail["topics"]],
            "source_basis": detail["source_basis"],
        })
    return {
        "reviewer_type": "ai", "human_validation": False,
        "identity_counts": dict(Counter(author.identity_status for author in authors)),
        "active_canonical_identity_count": len(active),
        "active_identities_with_eligible_publications": sum(bool(record["eligible_paper_ids"]) for record in author_records),
        "unresolved_active_identity_count": len(unresolved_author_names),
        "unresolved_active_identity_names": unresolved_author_names,
        "possible_same_person_pairs_not_merged": possible_identity_pairs(active),
        "alias_collision_count": len(collisions), "alias_collisions": collisions,
        "excluded_paper_topic_link_count": len(excluded_topic_links), "excluded_paper_topic_links": excluded_topic_links,
        "excluded_author_evidence_count": len(evidence_leakage), "excluded_author_evidence": evidence_leakage,
        "authorship_mismatch_count": len(authorship_mismatch), "authorship_mismatches": authorship_mismatch,
        "overclaim_output_violation_count": len(output_claim_violations), "overclaim_output_violations": output_claim_violations,
        "publication_derived_author_topic_link_count": len(author_links),
        "author_records": author_records,
        "limitations": [
            "Canonical rows and exact normalized aliases are used, but unresolved initial/full-name candidates are not merged without authoritative evidence.",
            "Topic links describe only the eligible indexed publication corpus and do not establish current expertise, availability, endorsement, or supervision suitability.",
            "This is an automated and AI-reviewed audit, not author or institutional validation.",
        ],
    }


def git_commit() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()


def run(output_dir: Path = OUTPUT_DIR) -> dict[str, Any]:
    cases = load_jsonl(DATASET)
    labels = label_universe(cases)
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ttlab-topic-eval-") as directory:
        copy_path = Path(directory) / "papers.db"
        shutil.copy2(DATABASE, copy_path)
        disposable_engine = create_engine(f"sqlite:///{copy_path}")
        with Session(disposable_engine) as session:
            rebuild_summary = rebuild_topic_index(session)
            lexical, lexical_scores = lexical_predictions(session, cases)
            dense, dense_scores, dense_config = dense_predictions(session, cases)
            author_audit = audit_authors(session)
    metrics: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "reviewer_type": "ai", "human_validation": False,
        "labels": labels,
        "methods": {},
    }
    all_predictions = []
    for method_index, (method, predictions, scores) in enumerate((("controlled_lexical", lexical, lexical_scores), ("dense_prototype", dense, dense_scores))):
        method_results: dict[str, Any] = {}
        for split_index, split in enumerate(("dev", "test", "all")):
            subset = cases if split == "all" else [case for case in cases if case["split"] == split]
            result = calculate_metrics(subset, predictions, labels=labels)
            add_bootstrap_ci(subset, predictions, result, labels, method_index * 10 + split_index)
            method_results[split] = result
        metrics["methods"][method] = method_results
        all_predictions.extend(raw_prediction_rows(cases, "dense" if method == "dense_prototype" else "lexical", predictions, scores))
    metrics["dense_configuration"] = dense_config
    metrics["error_taxonomy"] = sorted({error["error_type"] for row in all_predictions for key in ("false_positives", "false_negatives") for error in row[key]})
    predictions_path = output_dir / "topic_predictions.jsonl"
    predictions_path.write_bytes(b"".join(canonical_bytes(row) + b"\n" for row in all_predictions))
    metrics_path = output_dir / "topic_metrics.json"
    metrics_path.write_text(json.dumps(metrics, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    author_path = output_dir / "author_identity_audit.json"
    author_path.write_text(json.dumps(author_audit, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    silver_manifest = json.loads(SILVER_MANIFEST.read_text(encoding="utf-8"))
    run_manifest = {
        "schema_version": 1, "generated_at": datetime.now(UTC).isoformat(),
        "code_commit": git_commit(),
        "topic_code_sha256": sha256_file(ROOT / "backend/app/intelligence/topic_explorer.py"),
        "evaluation_code_sha256": sha256_file(Path(__file__)),
        "silver_dataset_sha256": silver_manifest["dataset_sha256"],
        "corpus": silver_manifest["corpus"],
        "runtime": {name: importlib.metadata.version(name) for name in ("sqlmodel", "sentence-transformers", "torch", "transformers")},
        "database_execution": "disposable byte copy; live database not mutated",
        "topic_rebuild_summary": rebuild_summary,
        "outputs": {
            "topic_predictions.jsonl": sha256_file(predictions_path),
            "topic_metrics.json": sha256_file(metrics_path),
            "author_identity_audit.json": sha256_file(author_path),
        },
        "reviewer_type": "ai", "human_validation": False,
    }
    manifest_path = output_dir / "topic_author_evaluation_manifest.json"
    manifest_path.write_text(json.dumps(run_manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {
        "metrics": metrics,
        "author_audit": author_audit,
        "manifest": run_manifest,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()
    result = run(args.output_dir)
    print(json.dumps({
        "lexical_test": result["metrics"]["methods"]["controlled_lexical"]["test"],
        "dense_test": result["metrics"]["methods"]["dense_prototype"]["test"],
        "author_audit": {key: result["author_audit"][key] for key in ("active_canonical_identity_count", "alias_collision_count", "excluded_paper_topic_link_count", "excluded_author_evidence_count", "authorship_mismatch_count", "overclaim_output_violation_count")},
    }, indent=2))


if __name__ == "__main__":
    main()
