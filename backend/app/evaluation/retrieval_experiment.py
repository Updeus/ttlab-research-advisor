from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import shutil
import subprocess
import time
from collections import Counter
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from jsonschema import Draft202012Validator
from sqlmodel import Session

from app.db import create_db_and_tables, engine
from app.evaluation.compare_retrieval_runs import compare_retrieval_results
from app.evaluation.retrieval_eval import (
    DEFAULT_BOOTSTRAP_REPETITIONS,
    DEFAULT_BOOTSTRAP_SEED,
    evaluate_retrieval,
    load_questions,
    write_results,
)
from app.evaluation.statistics import holm_bonferroni
from app.indexing.embedder import (
    DEFAULT_INDEX_PATH,
    DENSE_INDEX_PATH,
    DENSE_PROVIDER,
    FEATURE_HASHING_PROVIDER,
    corpus_descriptor,
    eligible_chunks,
)
from app.indexing.keyword_search import SearchFilters, enrich_keyword_results, search_keyword
from app.indexing.retriever import (
    BASELINE_RETRIEVER_CONFIG,
    DEFAULT_RETRIEVER_CONFIG,
    RetrieverConfig,
    expand_query,
    rank_retrieval_components,
)
from app.indexing.vector_store import (
    VectorSearchContext,
    load_vector_search_context,
    search_vector_store,
)

EXPERIMENT_ID = "ttlab-retrieval-phase2-v1"
DEFAULT_QUESTIONS = Path("data/evaluation/retrieval_silver_v1.jsonl")
DEFAULT_SCHEMA = Path("data/evaluation/retrieval_eval_results.schema.json")
DEFAULT_OUTPUT = Path("artifacts/phase2/retrieval")
TOP_K = 10
RETRIEVAL_DEPTH = 50
CANDIDATE_DEPTH = 150
WEIGHT_SUM = 0.90
ABLATION_FIELDS = (
    ("query_expansion", "enable_query_expansion"),
    ("metadata_boost", "enable_metadata_boost"),
    ("section_boost", "enable_section_boost"),
    ("evidence_adjustment", "enable_evidence_adjustment"),
    ("topic_adjustment", "enable_topic_adjustment"),
    ("diversity_penalty", "enable_diversity_penalty"),
)
STATISTICAL_METRICS = (
    "set_recall_at_3",
    "set_recall_at_5",
    "set_recall_at_10",
    "hit_at_10",
    "mrr",
    "ndcg_at_10",
    "unanswerable_abstention",
)
TAXONOMY = (
    "extraction",
    "intent_mismatch",
    "lexical_mismatch",
    "semantic_mismatch",
    "topic_identity_error",
    "over_broad_expansion",
    "ranking_diversity",
    "corpus_absence",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def git_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()


def split_questions(questions: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    dev = [dict(question) for question in questions if question.get("split") == "dev"]
    test = [dict(question) for question in questions if question.get("split") == "test"]
    unexpected = sorted({str(question.get("split")) for question in questions} - {"dev", "test"})
    if unexpected or len(dev) != 30 or len(test) != 20:
        raise ValueError(
            f"frozen split mismatch: dev={len(dev)} test={len(test)} unexpected={unexpected}"
        )
    if set(str(item["case_id"]) for item in dev) & set(str(item["case_id"]) for item in test):
        raise ValueError("development and test case IDs overlap")
    return dev, test


def load_result_schema(path: Path) -> Draft202012Validator:
    schema = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def precompute_components(
    session: Session,
    questions: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, dict[bool, dict[str, Any]]], dict[str, Any]]:
    """Load each validated vector index once and cache no source text on disk."""

    before = corpus_descriptor(session, eligible_chunks(session))
    contexts: dict[str, VectorSearchContext] = {
        FEATURE_HASHING_PROVIDER: load_vector_search_context(
            session,
            provider_name=FEATURE_HASHING_PROVIDER,
            index_path=DEFAULT_INDEX_PATH,
        ),
        DENSE_PROVIDER: load_vector_search_context(
            session,
            provider_name=DENSE_PROVIDER,
            index_path=DENSE_INDEX_PATH,
        ),
    }
    cache: dict[str, dict[bool, dict[str, Any]]] = {}
    started = time.perf_counter()
    for offset, question in enumerate(questions, start=1):
        case_id = str(question["case_id"])
        original = str(question["question"])
        expanded, additions = expand_query(original)
        variants = {False: (original, [])}
        if expanded != original:
            variants[True] = (expanded, additions)
        cache[case_id] = {}
        for expansion_enabled, (search_query, expansions) in variants.items():
            raw_keyword = search_keyword(
                session,
                search_query,
                top_k=CANDIDATE_DEPTH,
                filters=SearchFilters(),
            )
            keyword = enrich_keyword_results(session, raw_keyword)
            vectors: dict[str, list[dict[str, Any]]] = {}
            warnings: dict[str, list[str]] = {}
            for provider_name, context in contexts.items():
                results, provider_warnings = search_vector_store(
                    session,
                    search_query,
                    top_k=CANDIDATE_DEPTH,
                    provider_name=provider_name,
                    context=context,
                )
                vectors[provider_name] = results
                warnings[provider_name] = provider_warnings
            cache[case_id][expansion_enabled] = {
                "search_query": search_query,
                "query_expansions": expansions,
                "keyword": keyword,
                "vectors": vectors,
                "warnings": warnings,
            }
        if True not in cache[case_id]:
            # No expansion rule fired. Reuse the exact same immutable candidate
            # pool instead of repeating all three retrieval passes.
            cache[case_id][True] = cache[case_id][False]
        print(f"precompute={offset}/{len(questions)} case_id={case_id}", flush=True)
    after = corpus_descriptor(session, eligible_chunks(session))
    if before != after:
        raise RuntimeError("corpus changed while retrieval candidate pools were being computed")
    return cache, {
        "elapsed_seconds": round(time.perf_counter() - started, 6),
        "candidate_depth": CANDIDATE_DEPTH,
        "corpus": before,
        "contexts": {
            provider: {
                "index_path": str(context.index_path.relative_to(Path.cwd().resolve())),
                "active_index_path": str(context.active_index_path.relative_to(Path.cwd().resolve())),
                "index_sha256": sha256_file(context.active_index_path),
                "manifest_path": str(context.active_manifest_path.relative_to(Path.cwd().resolve())),
                "manifest_sha256": sha256_file(context.active_manifest_path),
                "generation_source": context.generation_source,
                "model_name": context.payload.get("model_name"),
                "model_revision": context.payload.get("model_revision"),
                "model_artifact_sha256": context.payload.get("model_artifact_sha256"),
                "dimensions": context.payload.get("dimensions"),
                "normalization": context.payload.get("normalization"),
            }
            for provider, context in contexts.items()
        },
    }


def response_factory(
    cache: Mapping[str, Mapping[bool, Mapping[str, Any]]],
    *,
    mode: str,
    provider: str | None,
    config: RetrieverConfig,
):
    def build(question: Mapping[str, Any], retrieval_depth: int) -> Mapping[str, Any]:
        case_id = str(question["case_id"])
        variant = cache[case_id][config.enable_query_expansion]
        vector_provider = provider or FEATURE_HASHING_PROVIDER
        vector_results = (
            list(variant["vectors"][vector_provider])
            if mode in {"feature_hashing", "dense", "hybrid"}
            else []
        )
        keyword_results = list(variant["keyword"]) if mode in {"keyword", "hybrid"} else []
        results = rank_retrieval_components(
            keyword_results,
            vector_results,
            mode=mode,
            top_k=retrieval_depth,
            query=str(variant["search_query"]),
            vector_provider=vector_provider,
            config=config,
        )
        warnings = list(variant["warnings"].get(vector_provider, [])) if vector_results else []
        return {
            "query": question["question"],
            "expanded_query": variant["search_query"],
            "query_expansions": variant["query_expansions"],
            "mode": mode,
            "results": results,
            "warnings": warnings,
            "vector_provider": vector_provider if mode != "keyword" else None,
            "retrieval_strategy": "frozen_component_pool_explicit_config_v1",
            "retriever_config": config.to_dict(),
        }

    return build


def base_run_config(
    questions_path: Path,
    questions: Sequence[Mapping[str, Any]],
    *,
    run_id: str,
    split: str,
    config: RetrieverConfig,
    execution_commit: str,
) -> dict[str, Any]:
    case_ids = [str(question["case_id"]) for question in questions]
    return {
        "experiment_id": EXPERIMENT_ID,
        "run_id": run_id,
        "split": split,
        "questions_path": questions_path.as_posix(),
        "questions_sha256": sha256_file(questions_path),
        "evaluated_case_ids": case_ids,
        "evaluated_case_ids_sha256": canonical_hash(case_ids),
        "retriever_config": config.to_dict(),
        "retriever_config_sha256": canonical_hash(config.to_dict()),
        "retrieval_depth": RETRIEVAL_DEPTH,
        "candidate_depth": CANDIDATE_DEPTH,
        "git_commit_at_execution": execution_commit,
        "experiment_code_sha256": sha256_file(Path(__file__)),
    }


def run_configuration(
    session: Session,
    cache: Mapping[str, Mapping[bool, Mapping[str, Any]]],
    questions_path: Path,
    questions: Sequence[Mapping[str, Any]],
    *,
    run_id: str,
    split: str,
    mode: str,
    provider: str | None,
    config: RetrieverConfig,
    bootstrap_repetitions: int,
    execution_commit: str,
) -> dict[str, Any]:
    started = time.perf_counter()
    result = evaluate_retrieval(
        session,
        questions,
        mode=mode,
        top_k=TOP_K,
        retrieval_depth=RETRIEVAL_DEPTH,
        bootstrap_repetitions=bootstrap_repetitions,
        bootstrap_seed=DEFAULT_BOOTSTRAP_SEED,
        retain_bootstrap_replicates=False,
        provider=provider or "none",
        retriever_config=config,
        response_factory=response_factory(cache, mode=mode, provider=provider, config=config),
        run_config=base_run_config(
            questions_path,
            questions,
            run_id=run_id,
            split=split,
            config=config,
            execution_commit=execution_commit,
        ),
    )
    result["run_config"]["elapsed_seconds"] = round(time.perf_counter() - started, 6)
    result["run_config"]["candidate_pool_reuse"] = True
    return result


def tuning_configs() -> list[tuple[str, RetrieverConfig]]:
    keyword_weights = (0.10, 0.20, 0.30, 0.40, 0.42, 0.50, 0.60, 0.70, 0.80)
    configs: list[tuple[str, RetrieverConfig]] = []
    for keyword_weight in keyword_weights:
        vector_weight = round(WEIGHT_SUM - keyword_weight, 2)
        config = replace(
            DEFAULT_RETRIEVER_CONFIG,
            keyword_weight=keyword_weight,
            vector_weight=vector_weight,
        )
        configs.append((f"kw-{keyword_weight:.2f}_dense-{vector_weight:.2f}", config))
    return configs


def select_tuned_configuration(candidate_results: Sequence[tuple[str, RetrieverConfig, Mapping[str, Any]]]) -> tuple[str, RetrieverConfig]:
    """Lexicographic dev-only objective with a documented deterministic tie break."""

    def score(item: tuple[str, RetrieverConfig, Mapping[str, Any]]) -> tuple[float, ...]:
        _run_id, config, result = item
        metrics = result["metrics"]
        return (
            float(metrics.get("mrr") or 0.0),
            float(metrics.get("ndcg_at_10") or 0.0),
            float(metrics.get("set_recall_at_10") or 0.0),
            -abs(config.keyword_weight - DEFAULT_RETRIEVER_CONFIG.keyword_weight),
            -config.keyword_weight,
        )

    run_id, config, _result = max(candidate_results, key=score)
    return run_id, config


def metric_snapshot(result: Mapping[str, Any]) -> dict[str, Any]:
    metrics = result["metrics"]
    names = (
        "set_recall_at_3",
        "set_recall_at_5",
        "set_recall_at_10",
        "hit_at_3",
        "hit_at_5",
        "hit_at_10",
        "precision_at_3",
        "precision_at_5",
        "precision_at_10",
        "mrr",
        "ndcg_at_10",
        "unanswerable_abstention_rate",
        "unanswerable_false_positive_rate",
    )
    intervals = result["statistics"]["metrics"]
    return {
        name: {
            "estimate": metrics.get(name),
            "ci_lower": intervals.get(name, {}).get("ci_lower"),
            "ci_upper": intervals.get(name, {}).get("ci_upper"),
        }
        for name in names
    }


def row_by_case(result: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {str(row["case_id"]): row for row in result["questions"]}


def error_taxonomy(
    questions: Sequence[Mapping[str, Any]],
    *,
    tuned: Mapping[str, Any],
    keyword: Mapping[str, Any],
    dense: Mapping[str, Any],
    no_expansion: Mapping[str, Any],
    no_diversity: Mapping[str, Any],
) -> dict[str, Any]:
    tuned_rows = row_by_case(tuned)
    keyword_rows = row_by_case(keyword)
    dense_rows = row_by_case(dense)
    expansion_rows = row_by_case(no_expansion)
    diversity_rows = row_by_case(no_diversity)
    counts: Counter[str] = Counter()
    cases: list[dict[str, Any]] = []
    for question in questions:
        case_id = str(question["case_id"])
        row = tuned_rows[case_id]
        answerable = question["answerability"] == "answerable"
        recall = row["metrics"].get("set_recall_at_10")
        complete = answerable and recall == 1.0
        tags: list[dict[str, str]] = []

        def add(tag: str, evidence: str) -> None:
            if tag not in {item["type"] for item in tags}:
                tags.append({"type": tag, "evidence": evidence})
                counts[tag] += 1

        if not answerable:
            add(
                "corpus_absence",
                "The source-reviewed label is unanswerable/out-of-corpus; this is a corpus-coverage condition, not a ranking miss.",
            )
        elif not complete:
            candidate_ids = {item["paper_id"] for item in row.get("candidate_ranked_results", [])}
            relevant_ids = set(question["relevant_paper_ids"])
            if relevant_ids & candidate_ids:
                add(
                    "intent_mismatch",
                    "At least one relevant paper entered the frozen top-50 candidate ranking but remained below the evaluated top 10.",
                )
            evidence_sections = {
                str(item.get("section") or "").strip().lower()
                for item in question.get("supporting_evidence", [])
            }
            if "unknown" in evidence_sections:
                add(
                    "extraction",
                    "A cited source passage has an Unknown section label; this is an extraction/structure-quality signal, not proof of causation.",
                )
            keyword_recall = keyword_rows[case_id]["metrics"].get("set_recall_at_10") or 0.0
            dense_recall = dense_rows[case_id]["metrics"].get("set_recall_at_10") or 0.0
            if keyword_recall < dense_recall:
                add(
                    "lexical_mismatch",
                    f"Dense Recall@10 ({dense_recall:.3f}) exceeded keyword Recall@10 ({keyword_recall:.3f}) for this case.",
                )
            if dense_recall < keyword_recall:
                add(
                    "semantic_mismatch",
                    f"Keyword Recall@10 ({keyword_recall:.3f}) exceeded dense Recall@10 ({dense_recall:.3f}) for this case.",
                )
            if question.get("category") in {"title_author_venue", "topic_application"}:
                add(
                    "topic_identity_error",
                    "The incomplete case belongs to the title/author/venue or topic/application stratum, so metadata/topic identity is a plausible diagnostic locus.",
                )
            no_expansion_recall = expansion_rows[case_id]["metrics"].get("set_recall_at_10") or 0.0
            if no_expansion_recall > float(recall or 0.0):
                add(
                    "over_broad_expansion",
                    f"Disabling query expansion increased Recall@10 from {float(recall or 0.0):.3f} to {no_expansion_recall:.3f}.",
                )
            no_diversity_recall = diversity_rows[case_id]["metrics"].get("set_recall_at_10") or 0.0
            if no_diversity_recall > float(recall or 0.0):
                add(
                    "ranking_diversity",
                    f"Disabling the diversity penalty increased Recall@10 from {float(recall or 0.0):.3f} to {no_diversity_recall:.3f}.",
                )
        cases.append(
            {
                "case_id": case_id,
                "category": question.get("category"),
                "answerability": question.get("answerability"),
                "set_recall_at_10": recall,
                "status": "complete_retrieval" if complete else ("out_of_corpus" if not answerable else "incomplete_retrieval"),
                "diagnostic_tags": tags,
            }
        )
    return {
        "taxonomy": {
            tag: {
                "case_count": counts[tag],
                "interpretation": "diagnostic signal, not a causal attribution",
            }
            for tag in TAXONOMY
        },
        "cases": cases,
        "limitations": [
            "The taxonomy applies deterministic counterfactual and label-stratum signals; it does not establish causal failure mechanisms.",
            "Extraction is flagged only where source-backed evidence has an Unknown section label, so other extraction defects may be missed.",
        ],
    }


def package_versions() -> dict[str, str | None]:
    names = (
        "fastapi",
        "sqlmodel",
        "sqlalchemy",
        "sentence-transformers",
        "torch",
        "transformers",
        "numpy",
        "scipy",
        "scikit-learn",
        "jsonschema",
    )
    versions: dict[str, str | None] = {}
    for name in names:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def write_manifest(output_dir: Path, metadata: Mapping[str, Any]) -> dict[str, Any]:
    files = []
    for path in sorted(candidate for candidate in output_dir.rglob("*") if candidate.is_file() and candidate.name != "manifest.json"):
        files.append(
            {
                "path": path.relative_to(output_dir).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    manifest = {
        "schema_version": "1.0.0",
        "experiment_id": EXPERIMENT_ID,
        "generated_at": datetime.now(UTC).isoformat(),
        **dict(metadata),
        "files": files,
        "file_count": len(files),
    }
    write_results(manifest, output_dir / "manifest.json")
    return manifest


def execute(args: argparse.Namespace) -> dict[str, Any]:
    questions_path = args.questions
    output_dir = args.output
    if output_dir.exists() and any(output_dir.iterdir()):
        existing_manifest = output_dir / "manifest.json"
        if not existing_manifest.is_file():
            raise ValueError(
                f"refusing to replace non-empty output without an experiment manifest: {output_dir}"
            )
        existing = json.loads(existing_manifest.read_text(encoding="utf-8"))
        if existing.get("experiment_id") != EXPERIMENT_ID:
            raise ValueError(f"refusing to replace output for a different experiment: {output_dir}")
        shutil.rmtree(output_dir)
    runs_dir = output_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    questions = load_questions(questions_path)
    dev, test = split_questions(questions)
    validator = load_result_schema(args.schema)
    all_runs: dict[str, dict[str, Any]] = {}
    execution_commit = git_commit()

    create_db_and_tables()
    with Session(engine) as session:
        cache, precompute = precompute_components(session, questions)

        def run_and_save(
            run_id: str,
            split: str,
            subset: Sequence[Mapping[str, Any]],
            mode: str,
            provider: str | None,
            config: RetrieverConfig,
        ) -> dict[str, Any]:
            result = run_configuration(
                session,
                cache,
                questions_path,
                subset,
                run_id=run_id,
                split=split,
                mode=mode,
                provider=provider,
                config=config,
                bootstrap_repetitions=args.bootstrap_repetitions,
                execution_commit=execution_commit,
            )
            errors = sorted(validator.iter_errors(result), key=lambda error: list(error.path))
            if errors:
                raise ValueError(f"result schema validation failed for {run_id}: {errors[0].message}")
            write_results(result, runs_dir / f"{run_id}.json")
            all_runs[run_id] = result
            print(
                f"run={run_id} mrr={result['metrics']['mrr']} "
                f"recall10={result['metrics']['set_recall_at_10']}",
                flush=True,
            )
            return result

        baseline_specs = (
            ("keyword", "keyword", None, BASELINE_RETRIEVER_CONFIG),
            ("feature_hashing", "feature_hashing", FEATURE_HASHING_PROVIDER, BASELINE_RETRIEVER_CONFIG),
            ("dense", "dense", DENSE_PROVIDER, BASELINE_RETRIEVER_CONFIG),
            ("heuristic_hybrid", "hybrid", DENSE_PROVIDER, DEFAULT_RETRIEVER_CONFIG),
        )
        for split_name, subset in (("dev", dev), ("test", test)):
            for label, mode, provider, config in baseline_specs:
                run_and_save(f"{label}_{split_name}", split_name, subset, mode, provider, config)

        tuning_results: list[tuple[str, RetrieverConfig, Mapping[str, Any]]] = []
        for label, config in tuning_configs():
            run_id = f"tuning_{label}_dev"
            result = run_and_save(run_id, "dev", dev, "hybrid", DENSE_PROVIDER, config)
            tuning_results.append((run_id, config, result))
        selected_source_run, selected_config = select_tuned_configuration(tuning_results)
        tuned_dev = run_and_save("tuned_hybrid_dev", "dev", dev, "hybrid", DENSE_PROVIDER, selected_config)
        tuned_test = run_and_save("tuned_hybrid_test", "test", test, "hybrid", DENSE_PROVIDER, selected_config)

        individual: dict[str, dict[str, Any]] = {}
        for label, field_name in ABLATION_FIELDS:
            config = replace(selected_config, **{field_name: False})
            individual[label] = run_and_save(
                f"ablation_individual_without_{label}_test",
                "test",
                test,
                "hybrid",
                DENSE_PROVIDER,
                config,
            )

        cumulative: dict[str, dict[str, Any]] = {}
        cumulative_config = selected_config
        disabled: list[str] = []
        for label, field_name in ABLATION_FIELDS:
            disabled.append(label)
            cumulative_config = replace(cumulative_config, **{field_name: False})
            cumulative["+".join(disabled)] = run_and_save(
                f"ablation_cumulative_{len(disabled):02d}_test",
                "test",
                test,
                "hybrid",
                DENSE_PROVIDER,
                cumulative_config,
            )

        sensitivity: dict[str, dict[str, Any]] = {}
        for delta in (-0.05, 0.05, 0.10, 0.20):
            keyword_weight = round(selected_config.keyword_weight + delta, 2)
            vector_weight = round(WEIGHT_SUM - keyword_weight, 2)
            if keyword_weight <= 0.0 or vector_weight <= 0.0:
                continue
            config = replace(
                selected_config,
                keyword_weight=keyword_weight,
                vector_weight=vector_weight,
            )
            label = f"kw-{keyword_weight:.2f}_dense-{vector_weight:.2f}"
            sensitivity[label] = run_and_save(
                f"sensitivity_{label}_dev", "dev", dev, "hybrid", DENSE_PROVIDER, config
            )

    comparison_runs = {
        "keyword": all_runs["keyword_test"],
        "feature_hashing": all_runs["feature_hashing_test"],
        "dense": all_runs["dense_test"],
        "heuristic_hybrid": all_runs["heuristic_hybrid_test"],
    }
    pairwise: dict[str, Any] = {}
    family_p_values: dict[str, float] = {}
    for baseline_name, baseline_result in comparison_runs.items():
        comparison = compare_retrieval_results(
            baseline_result,
            tuned_test,
            metrics=STATISTICAL_METRICS,
            repetitions=args.bootstrap_repetitions,
            seed=DEFAULT_BOOTSTRAP_SEED,
        )
        pairwise[f"tuned_minus_{baseline_name}"] = comparison
        for metric, details in comparison["comparisons"].items():
            family_p_values[f"tuned_minus_{baseline_name}:{metric}"] = details["paired_test"]["p_value"]
    family_correction = holm_bonferroni(family_p_values, familywise_alpha=0.05)
    for key, correction in family_correction.items():
        contrast, metric = key.split(":", 1)
        pairwise[contrast]["comparisons"][metric]["experiment_family_correction"] = correction
    write_results(
        {
            "schema_version": "1.0.0",
            "family": "all tuned-vs-baseline test-set metric contrasts",
            "test": "two-sided query-paired sign randomization on mean differences",
            "bootstrap": "query-paired percentile bootstrap",
            "multiplicity": "Holm-Bonferroni over every available contrast-metric p-value",
            "familywise_alpha": 0.05,
            "comparisons": pairwise,
        },
        output_dir / "paired_statistics.json",
    )

    taxonomy = error_taxonomy(
        test,
        tuned=tuned_test,
        keyword=all_runs["keyword_test"],
        dense=all_runs["dense_test"],
        no_expansion=individual["query_expansion"],
        no_diversity=individual["diversity_penalty"],
    )
    write_results(taxonomy, output_dir / "error_taxonomy.json")

    tuning_payload = {
        "schema_version": "1.0.0",
        "partition_used_for_selection": "dev",
        "held_out_test_labels_used_for_selection": False,
        "search_space": {
            "keyword_weights": [config.keyword_weight for _label, config in tuning_configs()],
            "vector_weight_rule": f"{WEIGHT_SUM:.2f} - keyword_weight",
            "other_terms": "fixed at the existing heuristic values",
            "candidate_count": len(tuning_configs()),
        },
        "objective": [
            "maximize dev MRR",
            "then maximize dev nDCG@10",
            "then maximize dev set Recall@10",
            "then prefer the weight closest to the existing heuristic",
            "then prefer the lower keyword weight",
        ],
        "candidates": [
            {
                "source_run_id": run_id,
                "config": config.to_dict(),
                "metrics": metric_snapshot(result),
            }
            for run_id, config, result in tuning_results
        ],
        "selected_source_run_id": selected_source_run,
        "selected_config": selected_config.to_dict(),
        "selected_config_sha256": canonical_hash(selected_config.to_dict()),
        "selected_dev_metrics": metric_snapshot(tuned_dev),
        "single_final_test_evaluation_run_id": "tuned_hybrid_test",
    }
    write_results(tuning_payload, output_dir / "tuning.json")

    summary = {
        "schema_version": "1.0.0",
        "experiment_id": EXPERIMENT_ID,
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset": {
            "path": questions_path.as_posix(),
            "sha256": sha256_file(questions_path),
            "case_count": len(questions),
            "dev_count": len(dev),
            "test_count": len(test),
            "category_counts": dict(sorted(Counter(str(item["category"]) for item in questions).items())),
            "label": "source-derived AI-reviewed silver retrieval set",
        },
        "controls": {
            "top_k_unique_papers": TOP_K,
            "retrieval_depth_chunks": RETRIEVAL_DEPTH,
            "candidate_pool_depth_chunks_per_component": CANDIDATE_DEPTH,
            "bootstrap_repetitions": args.bootstrap_repetitions,
            "bootstrap_seed": DEFAULT_BOOTSTRAP_SEED,
            "same_frozen_candidate_pools_for_all_configurations": True,
            "unjudged_policy": "non-relevant",
        },
        "precompute": precompute,
        "selected_tuned_config": selected_config.to_dict(),
        "test_results": {
            name: metric_snapshot(result)
            for name, result in {
                **comparison_runs,
                "tuned_hybrid": tuned_test,
            }.items()
        },
        "ablations": {
            "partition": "test; descriptive post-selection analyses, not used to choose the configuration",
            "individual": {name: metric_snapshot(result) for name, result in individual.items()},
            "cumulative": {name: metric_snapshot(result) for name, result in cumulative.items()},
        },
        "sensitivity": {
            "partition": "dev only",
            "selected": metric_snapshot(tuned_dev),
            "neighbours": {name: metric_snapshot(result) for name, result in sensitivity.items()},
        },
        "statistical_analysis_path": "artifacts/phase2/retrieval/paired_statistics.json",
        "error_taxonomy_path": "artifacts/phase2/retrieval/error_taxonomy.json",
        "limitations": [
            "Silver relevance judgments were created and verified by one AI reviewer process, not independent human assessors.",
            "Precision treats every unjudged paper as non-relevant even though relevance pooling may be incomplete.",
            "The held-out test partition contains only one unanswerable case; abstention estimates and tests are therefore not stable.",
            "Bootstrap intervals reflect query-sample uncertainty only, not silver-label or corpus-selection uncertainty.",
            "Post-selection ablations describe this test set and were not used to choose or retune the final configuration.",
            "The fixed TTLAB corpus limits external validity; no effectiveness claim beyond this corpus is supported.",
        ],
    }
    write_results(summary, output_dir / "summary.json")

    manifest = write_manifest(
        output_dir,
        {
            "source_git_commit_at_execution": execution_commit,
            "command": (
                "PYTHONPATH=backend .venv/bin/python -m app.evaluation.retrieval_experiment "
                f"--questions {questions_path.as_posix()} --output {output_dir.as_posix()} "
                f"--bootstrap-repetitions {args.bootstrap_repetitions}"
            ),
            "inputs": {
                "questions": {"path": questions_path.as_posix(), "sha256": sha256_file(questions_path)},
                "result_schema": {"path": args.schema.as_posix(), "sha256": sha256_file(args.schema)},
                "database_logical_corpus": precompute["corpus"],
            },
            "environment": {
                "python": platform.python_version(),
                "platform": platform.platform(),
                "machine": platform.machine(),
                "processor": platform.processor(),
                "packages": package_versions(),
            },
        },
    )
    print(f"experiment={EXPERIMENT_ID} files={manifest['file_count']} output={output_dir}")
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Execute frozen-corpus retrieval baselines, dev-only tuning, held-out testing, ablations, and statistics."
    )
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--bootstrap-repetitions",
        type=int,
        default=DEFAULT_BOOTSTRAP_REPETITIONS,
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.bootstrap_repetitions < 1000:
        raise SystemExit("bootstrap repetitions must be at least 1000 for the reported experiment")
    execute(args)


if __name__ == "__main__":
    main()
