#!/usr/bin/env python3
"""Build the source-backed Phase 4 topic silver set from reviewed annotations.

The labels below are AI-reviewed silver judgments, not human gold labels.  The
same Codex reviewer made two temporally separated passes.  Pass B used a fixed
shuffle and the final reconciliation follows Pass B after re-reading the title
and source passages.  The script never calls retrieval or generated artefacts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from app.db import engine
from app.models import Chunk, Paper

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "data/evaluation/topic_author_silver_v1.jsonl"
MANIFEST = ROOT / "data/evaluation/topic_author_silver_v1.manifest.json"
SCHEMA = ROOT / "data/evaluation/topic_author_silver_v1.schema.json"
DENSE_MANIFEST = ROOT / "data/indexes/dense_embeddings.manifest.json"
TOPIC_CODE = ROOT / "backend/app/intelligence/topic_explorer.py"
PASS_A_SEED = 42017
PASS_B_SEED = 73129
REVIEW_DATE = "2026-07-12"

LABELS = [
    "rag", "ai", "machine learning", "information retrieval", "data science",
    "research discovery", "web applications", "open data", "education", "optimization",
    "iot", "agriculture", "climate", "telecommunications", "mobile services", "networks",
    "visualization", "natural language processing", "summarization", "chatbots", "clustering",
    "word embeddings", "cybersecurity", "fraud detection", "privacy", "transportation",
    "dangerous driving", "insurance", "pricing", "marketing", "recommendation systems",
    "e commerce", "supply chain", "smart grid", "body shape detection", "civil society",
    "internet resilience", "simulation", "energy",
]

# Pass B / reconciled labels.  Labels denote a principal problem, method, or
# application explicitly supported by the paper title/abstract, not a passing
# mention, a cited work, a generated summary, or a broad real-world association.
FINAL_LABELS: dict[str, list[str]] = {
    "a-comparison-of-large-language-models-in-a-retrieval-augmented-generatio-61f51db0": ["rag", "ai", "information retrieval", "natural language processing"],
    "a-consumer-focused-open-data-platform-8fd2a9df": ["open data", "web applications", "visualization"],
    "a-data-centric-approach-to-school-discipline-1b433321": ["data science", "education"],
    "a-global-hierarchical-llm-framework-for-precise-responses-through-subscr-4c7c8562": ["rag", "ai", "information retrieval", "natural language processing"],
    "a-method-for-learning-representations-of-signed-networks-1e492890": ["machine learning", "networks"],
    "a-personalized-overdraft-protection-framework-7d1549da": ["ai", "machine learning"],
    "a-recommender-system-for-the-upselling-of-telecommunications-products-8247baf7": ["machine learning", "telecommunications", "marketing", "recommendation systems"],
    "a-review-of-human-body-shape-detection-techniques-and-their-application--4264e4f6": ["machine learning", "body shape detection"],
    "a-self-contained-spatio-temporal-anomaly-detection-application-for-trave-056e92ea": ["machine learning", "transportation"],
    "a-simple-approach-to-synthetic-time-series-generation-66bcf71f": ["simulation"],
    "a-smart-shuffle-approach-to-playlist-shuffling-with-user-defined-constra-2ef8bb64": ["optimization", "recommendation systems"],
    "a-study-of-qos-support-performance-and-pricing-of-mobile-data-plans-in-t-8bb51c9b": ["telecommunications", "mobile services", "networks", "pricing"],
    "a-successive-quadratic-approximation-approach-for-tuning-parameters-in-a-a237a1cc": ["machine learning", "optimization"],
    "a-unique-approach-to-demand-side-management-of-electric-vehicle-charging-270fd54b": ["optimization", "transportation", "energy"],
    "a-data-science-approach-to-risk-assessment-for-automobile-insurance-poli-afea8a81": ["data science", "optimization", "insurance", "pricing"],
    "ai-driven-personalization-as-a-disruptive-strategy-for-the-creation-of-n-fe2bc5a4": ["ai", "marketing", "recommendation systems"],
    "above-ground-biomass-estimation-of-a-cocoa-plantation-using-machine-lear-7dfebebb": ["machine learning", "agriculture", "climate"],
    "an-integer-programming-approach-to-chick-placement-at-a-broiler-producti-0b44d541": ["optimization", "agriculture"],
    "an-open-dataset-of-labelled-tropical-crops-9b1b8d0e": ["machine learning", "open data", "agriculture", "climate"],
    "an-open-source-real-time-data-portal-c0f8823f": ["web applications", "open data", "iot", "visualization"],
    "application-for-the-detection-of-dangerous-driving-and-an-associated-gam-89c35dfe": ["transportation", "dangerous driving"],
    "association-rule-mining-of-household-electrical-energy-usage-91e53f3a": ["machine learning", "smart grid", "energy"],
    "automating-the-collection-display-summarization-and-podcasting-of-academ-498c837a": ["research discovery", "web applications", "natural language processing", "summarization"],
    "bilingual-dialect-classification-using-nlp-f02e3cc3": ["machine learning", "natural language processing"],
    "csp-customer-satisfaction-based-pricing-for-advanced-cellular-networks-152e8f32": ["telecommunications", "mobile services", "networks", "pricing"],
    "can-foreign-datasets-help-improve-plankton-classification-performance-fo-01e5c8cb": ["machine learning"],
    "congestion-detection-for-qos-enabled-wireless-networks-and-its-potential-25cd8353": ["telecommunications", "mobile services", "networks"],
    "constant-time-fixed-memory-zero-false-negative-error-logging-for-low-pow-94e78541": ["iot", "simulation"],
    "crop-price-prediction-a-comparison-of-the-recursive-and-direct-forecasti-5e0aaa71": ["data science", "agriculture", "pricing"],
    "cybersecurity-threat-analysis-for-an-energy-rich-small-island-developing-5d061ce8": ["cybersecurity", "internet resilience", "energy"],
    "cyclic-beam-switching-for-smart-grid-networks-009fe57c": ["telecommunications", "networks", "smart grid", "energy"],
    "data-driven-weighting-for-coastal-vulnerability-assessment-in-small-isla-0141fa24": ["data science", "climate", "internet resilience"],
    "data4good-an-established-framework-for-supporting-civil-society-organiza-597c7482": ["data science", "civil society"],
    "design-and-evaluation-of-a-mobile-medication-management-system-for-vulne-2c0301ce": [],
    "design-and-specifications-of-a-repository-for-real-time-open-data-be5e53d0": ["web applications", "open data", "iot"],
    "developing-an-algorithm-for-generating-a-tabla-accompaniment-for-hindust-0303df18": [],
    "dynamic-group-formation-in-an-online-social-network-a8e55b98": ["networks", "clustering"],
    "efficient-m-commerce-platform-for-developing-countries-f6fc2409": ["web applications", "telecommunications", "mobile services", "e commerce"],
    "efficient-sentiment-classification-of-twitter-feeds-8390d8a8": ["machine learning", "natural language processing"],
    "a-decision-tree-approach-to-customer-surveys-8f7fac4b": [],
    "estimating-deforestation-using-machine-learning-algorithms-3f48cc99": ["machine learning", "climate"],
    "estimating-the-carbon-content-of-oceans-using-satellite-sensor-data-1151734e": ["data science", "climate"],
    "event-scheduling-with-soft-constraints-and-on-demand-re-optimization-224f19ec": ["optimization"],
    "exploiting-gaussian-word-embeddings-for-document-clustering-863ee9e7": ["information retrieval", "natural language processing", "clustering", "word embeddings"],
    "exploring-supervised-machine-learning-for-multi-phase-identification-and-3b9ea038": ["machine learning"],
    "generating-personalized-news-podcasts-from-print-media-for-those-on-the--11532982": ["natural language processing", "summarization"],
    "generative-ai-and-multi-agent-systems-approach-to-psychometric-evaluatio-720fdd0f": ["ai"],
    "heuristics-for-advertising-revenue-optimization-in-online-social-network-85ddf731": ["optimization", "networks", "marketing"],
    "instant-message-summarization-with-emoji-unicode-characterset-support-96db0872": ["natural language processing", "summarization"],
    "load-forecasting-using-deep-neural-networks-31644fac": ["machine learning", "energy"],
    "location-obfuscation-using-smart-meter-readings-5bfe1825": ["privacy", "smart grid", "energy"],
    "marketing-channel-recommendations-in-banking-3deb0e4b": ["machine learning", "marketing", "recommendation systems"],
    "material-and-cost-estimation-of-a-customized-product-based-on-the-custom-ade2050d": ["machine learning", "natural language processing", "pricing"],
    "network-neutrality-violation-detection-for-streaming-media-traffic-in-wi-0506f67c": ["telecommunications", "mobile services", "networks"],
    "optesim-optimal-cellular-prepaid-plans-for-a-customer-base-with-esim-cap-13511a8a": ["optimization", "telecommunications", "mobile services", "pricing"],
    "office-scheduling-of-a-hybrid-workforce-with-fairness-and-group-collabor-38c14f1b": ["optimization", "clustering"],
    "on-gpu-acceleration-of-the-vector-quantization-image-compression-algorit-c70cc898": [],
    "premium-rate-services-fraud-detection-37e69fcf": ["machine learning", "telecommunications", "fraud detection"],
    "spatio-temporal-clustering-for-optimizing-time-sensitive-product-deliver-3a81a842": ["optimization", "clustering", "transportation", "supply chain"],
    "using-chatbot-technologies-to-help-individuals-make-sound-personalized-f-febafb9d": ["natural language processing", "chatbots"],
}

# The disagreements are deliberately retained as raw evidence of the second
# pass.  They are boundary judgments, not simulated independent reviewers.
PASS_A_OVERRIDES: dict[str, list[str]] = {
    "a-consumer-focused-open-data-platform-8fd2a9df": ["open data", "web applications"],
    "a-method-for-learning-representations-of-signed-networks-1e492890": ["machine learning", "networks", "word embeddings"],
    "a-simple-approach-to-synthetic-time-series-generation-66bcf71f": ["privacy", "simulation"],
    "a-unique-approach-to-demand-side-management-of-electric-vehicle-charging-270fd54b": ["optimization", "transportation", "smart grid", "energy"],
    "an-open-source-real-time-data-portal-c0f8823f": ["web applications", "open data", "iot"],
    "design-and-evaluation-of-a-mobile-medication-management-system-for-vulne-2c0301ce": ["web applications"],
    "estimating-the-carbon-content-of-oceans-using-satellite-sensor-data-1151734e": ["data science", "iot", "climate"],
    "generating-personalized-news-podcasts-from-print-media-for-those-on-the--11532982": ["ai", "natural language processing", "summarization"],
    "premium-rate-services-fraud-detection-37e69fcf": ["machine learning", "telecommunications", "fraud detection", "pricing"],
    "using-chatbot-technologies-to-help-individuals-make-sound-personalized-f-febafb9d": ["education", "natural language processing", "chatbots"],
}

UNKNOWN_RATIONALES = {
    "design-and-evaluation-of-a-mobile-medication-management-system-for-vulne-2c0301ce": "The primary subject is a mobile-health medication manager; mobile healthcare is outside the fixed vocabulary, and mobile is not treated as a web application.",
    "developing-an-algorithm-for-generating-a-tabla-accompaniment-for-hindust-0303df18": "The primary subject is audio/music-signal accompaniment, for which the controlled vocabulary has no label.",
    "a-decision-tree-approach-to-customer-surveys-8f7fac4b": "The paper uses an adaptive hierarchical survey design; decision tree in this paper is not evidence of a machine-learning classifier.",
    "on-gpu-acceleration-of-the-vector-quantization-image-compression-algorit-c70cc898": "The primary subject is GPU image-compression acceleration; the vocabulary has no image compression or parallel-computing label.",
}


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def snippet(value: str, limit: int = 480) -> str:
    cleaned = " ".join(str(value or "").split())
    return cleaned if len(cleaned) <= limit else cleaned[:limit].rstrip(" ,.;:") + "..."


def load_corpus_descriptor() -> dict[str, Any]:
    manifest = json.loads(DENSE_MANIFEST.read_text(encoding="utf-8"))
    return {
        "snapshot_id": manifest["corpus"]["snapshot_id"],
        "snapshot_hash": manifest["corpus"]["snapshot_hash"],
        "eligible_paper_count": manifest["corpus"]["eligible_paper_count"],
        "eligible_chunk_count": manifest["corpus"]["eligible_chunk_count"],
    }


def evidence_for(session: Session, paper: Paper) -> list[dict[str, Any]]:
    title_text = paper.title.strip()
    evidence: list[dict[str, Any]] = [{
        "evidence_type": "paper_title",
        "locator": "paper.title",
        "text": title_text,
        "sha256": sha256_bytes(title_text.encode("utf-8")),
    }]
    chunks = list(
        session.exec(
            select(Chunk).where(Chunk.paper_id == paper.paper_id).order_by(Chunk.chunk_index).limit(2)
        ).all()
    )
    for chunk in chunks:
        evidence.append({
            "evidence_type": "source_chunk",
            "chunk_id": chunk.chunk_id,
            "source_hash": chunk.source_hash,
            "section": chunk.section or "Unknown",
            "page_start": chunk.page_start,
            "page_end": chunk.page_end,
            "text": snippet(chunk.text),
        })
    return evidence


def rationale_for(paper: Paper, labels: list[str]) -> str:
    if not labels:
        return UNKNOWN_RATIONALES[paper.paper_id]
    return (
        f"The title and opening publication passage identify {', '.join(labels)} as principal problem, method, "
        "or application labels. Incidental background and cited-work vocabulary are excluded."
    )


def build_records() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    corpus = load_corpus_descriptor()
    ids = list(FINAL_LABELS)
    pass_a_order = ids.copy()
    pass_b_order = ids.copy()
    random.Random(PASS_A_SEED).shuffle(pass_a_order)
    random.Random(PASS_B_SEED).shuffle(pass_b_order)
    pass_a_rank = {paper_id: index for index, paper_id in enumerate(pass_a_order)}
    pass_b_rank = {paper_id: index for index, paper_id in enumerate(pass_b_order)}
    records: list[dict[str, Any]] = []
    with Session(engine) as session:
        for sample_index, paper_id in enumerate(ids):
            paper = session.get(Paper, paper_id)
            if paper is None:
                raise RuntimeError(f"Missing reviewed paper: {paper_id}")
            if paper.corpus_eligibility_status != "eligible":
                raise RuntimeError(f"Silver paper is not eligible: {paper_id}")
            final = sorted(FINAL_LABELS[paper_id])
            unknown = not final
            pass_a = sorted(PASS_A_OVERRIDES.get(paper_id, final))
            split = "test" if sample_index % 5 in {0, 3} else "dev"
            stratum = "other_unknown" if unknown else ("multi_label" if len(final) > 1 else "single_label")
            evidence = evidence_for(session, paper)
            records.append({
                "schema_version": 1,
                "case_id": f"topic-silver-{sample_index + 1:03d}",
                "split": split,
                "stratum": stratum,
                "paper_id": paper.paper_id,
                "title": paper.title,
                "year": paper.year,
                "corpus": corpus,
                "evidence": evidence,
                "review_passes": [
                    {
                        "pass_id": "create",
                        "reviewer_id": "codex-ai-review-pass-a",
                        "reviewer_type": "ai",
                        "model_family": "GPT-5/Codex",
                        "review_date_utc": REVIEW_DATE,
                        "order_seed": PASS_A_SEED,
                        "order_position": pass_a_rank[paper_id],
                        "labels": pass_a,
                        "other_unknown": not pass_a,
                        "rationale": rationale_for(paper, pass_a),
                    },
                    {
                        "pass_id": "verify",
                        "reviewer_id": "codex-ai-review-pass-b",
                        "reviewer_type": "ai",
                        "model_family": "GPT-5/Codex",
                        "review_date_utc": REVIEW_DATE,
                        "order_seed": PASS_B_SEED,
                        "order_position": pass_b_rank[paper_id],
                        "labels": final,
                        "other_unknown": unknown,
                        "rationale": rationale_for(paper, final),
                    },
                ],
                "final_labels": final,
                "final_other_unknown": unknown,
                "label_evidence": {
                    label: [item.get("chunk_id") or item["locator"] for item in evidence]
                    for label in final
                },
                "adjudication": {
                    "method": "same-AI two-pass source reinspection; not independent review or human IRR",
                    "changed_after_verify": pass_a != final,
                    "rationale": rationale_for(paper, final),
                },
            })
    return records, {
        "pass_a_order_sha256": sha256_bytes(canonical_bytes(pass_a_order)),
        "pass_b_order_sha256": sha256_bytes(canonical_bytes(pass_b_order)),
        "pass_a_seed": PASS_A_SEED,
        "pass_b_seed": PASS_B_SEED,
    }


def schema() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://local.ttlab/topic_author_silver_v1.schema.json",
        "title": "TTLAB topic controlled-vocabulary AI-reviewed silver case",
        "type": "object",
        "required": ["schema_version", "case_id", "split", "stratum", "paper_id", "corpus", "evidence", "review_passes", "final_labels", "final_other_unknown", "adjudication"],
        "properties": {
            "schema_version": {"const": 1},
            "case_id": {"type": "string", "pattern": "^topic-silver-[0-9]{3}$"},
            "split": {"enum": ["dev", "test"]},
            "stratum": {"enum": ["single_label", "multi_label", "other_unknown"]},
            "paper_id": {"type": "string", "minLength": 1},
            "corpus": {"type": "object"},
            "evidence": {"type": "array", "minItems": 2},
            "review_passes": {"type": "array", "minItems": 2, "maxItems": 2},
            "final_labels": {"type": "array", "items": {"enum": LABELS}, "uniqueItems": True},
            "final_other_unknown": {"type": "boolean"},
            "adjudication": {"type": "object"},
        },
        "additionalProperties": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    records, pass_metadata = build_records()
    payload = b"".join(canonical_bytes(record) + b"\n" for record in records)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(payload)
    SCHEMA.write_text(json.dumps(schema(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    counts = {name: sum(record["stratum"] == name for record in records) for name in ("single_label", "multi_label", "other_unknown")}
    label_support = {label: sum(label in record["final_labels"] for record in records) for label in LABELS}
    manifest = {
        "schema_version": 1,
        "dataset": str(args.output.relative_to(ROOT)),
        "dataset_sha256": sha256_bytes(payload),
        "generated_at": datetime.now(UTC).isoformat(),
        "reviewer_type": "ai",
        "human_validation": False,
        "review_method": "same Codex AI reviewer, two fixed-seed shuffled source-inspection passes; not independent or human IRR",
        "case_count": len(records),
        "split_counts": {name: sum(record["split"] == name for record in records) for name in ("dev", "test")},
        "stratum_counts": counts,
        "label_support": label_support,
        "pass_disagreement_cases": sum(record["adjudication"]["changed_after_verify"] for record in records),
        "pass_exact_agreement": sum(not record["adjudication"]["changed_after_verify"] for record in records) / len(records),
        "annotation_config_sha256": sha256_bytes(canonical_bytes({"final": FINAL_LABELS, "pass_a_overrides": PASS_A_OVERRIDES, "criteria": "principal title/abstract problem, method, or application; exclude incidental/background/generated"})),
        "builder_sha256": sha256_bytes(Path(__file__).read_bytes()),
        "topic_code_sha256": sha256_bytes(TOPIC_CODE.read_bytes()),
        "corpus": records[0]["corpus"],
        **pass_metadata,
        "limitations": [
            "Silver labels were produced by one AI reviewer in two passes; they are not human gold labels or inter-rater reliability.",
            "Rare labels have low support and correspondingly wide uncertainty intervals.",
            "The fixed vocabulary cannot represent every TTLAB research domain; other/unknown is intentional.",
        ],
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"dataset": str(args.output), "sha256": manifest["dataset_sha256"], "cases": len(records), "splits": manifest["split_counts"], "strata": counts, "pass_disagreements": manifest["pass_disagreement_cases"]}, indent=2))


if __name__ == "__main__":
    main()
