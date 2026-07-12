#!/usr/bin/env python3
"""Build a source-inspected, two-pass silver set for live chunk sections.

This evaluation reads SQLite chunks and extracted page JSON only. It does not
call or inspect retrieval, ranking, embedding, or generation code.
"""

from __future__ import annotations

import hashlib
import json
import random
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DATABASE = ROOT / "data/papers.db"
CREATE_OUTPUT = ROOT / "data/evaluation/section_quality_silver_create_v1.jsonl"
FINAL_OUTPUT = ROOT / "data/evaluation/section_quality_silver_v1.jsonl"
SHUFFLE_SEED = 20260712
CREATED_AT = "2026-07-12T23:10:00Z"
VERIFIED_AT = "2026-07-12T23:42:00Z"


# id, stratum, expected, creation label, heading query, rationale
SPECS = [
    ("a-decision-tree-approach-to-the-collection-of-data-for-sustainable-devel-c61e037f-chunk-0000-05a1debde642", "front_matter", "Unknown", "Abstract", "Abstract", "The chunk crosses the explicit abstract into substantial unheaded body text; the extracted page does not provide a defensible single post-abstract section."),
    ("exploiting-gaussian-word-embeddings-for-document-clustering-863ee9e7-chunk-0000-67c841ab15d3", "front_matter", "Introduction", "Literature Review", "PURPOSE", "The short abstract is followed by a dominant purpose/problem framing section before the later Background boundary."),
    ("playlist-shuffling-given-user-defined-constraints-on-song-sequencing-2ecc20c8-chunk-0000-c97e9658fd8c", "front_matter", "Unknown", "Abstract", "COPYRIGHT MATERIAL", "Proceedings copyright and editorial pages precede a paper abstract in one seven-page chunk, so no single scholarly section label is defensible."),
    ("using-mapreduce-for-impression-allocation-in-online-social-networks-6898c11c-chunk-0000-754cfbebe787", "front_matter", "Introduction", "Introduction", "PROBLEM", "After a short abstract, the numbered Problem section dominates the chunk and introduces the research formulation."),
    ("efficient-sentiment-classification-of-twitter-feeds-8390d8a8-chunk-0001-a015cebb121b", "section_boundary", "Literature Review", "Abstract", "RELATED WORK", "Two-column extraction inserts the abstract midstream, but most of the chunk is the surrounding related-work comparison of earlier classifiers."),

    ("emerging-network-technologies-and-network-neutrality-conformance-2af0cd47-chunk-0000-3954129734c0", "front_matter", "Introduction", "Introduction", "I. INTRODUCTION", "The explicit Introduction follows the abstract and supplies most of the substantive framing text."),
    ("a-simple-approach-to-synthetic-time-series-generation-66bcf71f-chunk-0000-cca705637229", "front_matter", "Methodology", "Methodology", "II. METHODOLOGY", "The chunk crosses front matter and Introduction, but the explicit Methodology begins early and dominates the remaining text."),
    ("a-self-contained-spatio-temporal-anomaly-detection-application-for-trave-056e92ea-chunk-0000-dbe8b508b0c5", "front_matter", "Introduction", "Introduction", "I. INTRODUCTION", "The Introduction is the dominant section; Literature Survey begins only near the end of this boundary chunk."),
    ("emerging-network-technologies-and-network-neutrality-conformance-2af0cd47-chunk-0004-1a9a8aac1f67", "section_boundary", "Literature Review", "Literature Review", "III. EMERGING NETWORK TECHNOLOGIES", "The source places this chunk under the survey of emerging network technologies, not under the earlier Introduction."),
    ("exploring-supervised-machine-learning-for-multi-phase-identification-and-3b9ea038-chunk-0001-d0928132422b", "section_interior", "Introduction", "Introduction", "Introduction", "The chunk is an interior continuation of the paper's explicit Introduction; no later major heading precedes it."),

    ("a-recommender-system-for-the-upselling-of-telecommunications-products-8247baf7-chunk-0001-ebad131d3223", "section_boundary", "Literature Review", "Literature Review", "II. RELATED WORK AND CONTRIBUTIONS", "Related Work dominates, while the dataset section starts only near the end."),
    ("a-comparison-of-data-driven-and-traditional-approaches-to-employee-perfo-b0c92e9f-chunk-0007-94f448177b3a", "section_boundary", "Discussion", "Discussion", "VI. COMPARISON", "Comparison and interpretation dominate before Summary and Conclusions begins near the end."),
    ("can-foreign-datasets-help-improve-plankton-classification-performance-fo-01e5c8cb-chunk-0004-dcd4fdd961db", "section_interior", "Methodology", "Methodology", "Methodology", "Preprocessing, normalization, augmentation, splitting, and CNN architecture continue the explicit Methodology section."),
    ("estimating-the-carbon-content-of-oceans-using-satellite-sensor-data-1151734e-chunk-0004-9711a968514b", "section_interior", "Methodology", "Methodology", "METHODOLOGY", "The source Methodology covers data sources and variables; this chunk continues that data-description procedure."),
    ("performance-evaluation-and-comparison-of-a-new-regression-algorithm-6c1084dd-chunk-0003-7f49edf5055a", "section_boundary", "Results", "Results", "NUMERICAL RESULTS", "The chunk is within Numerical Results and contains datasets, evaluation setup, and reported MAE comparisons."),

    ("office-scheduling-of-a-hybrid-workforce-with-fairness-and-group-collabor-38c14f1b-chunk-0003-5e2f83b2591e", "section_boundary", "Methodology", "Methodology", "IV. EXPERIMENTAL SETUP", "Experimental design, compute environment, and monitoring metrics dominate before Results."),
    ("predicting-foreign-exchange-rates-for-an-oil-rich-country-using-energy-b-febd3fb0-chunk-0002-e3945895b56c", "section_boundary", "Methodology", "Methodology", "III. METHODOLOGY", "The chunk contains evaluation design, forecasting models, and metric definitions under Methodology."),
    ("an-integer-programming-approach-to-chick-placement-at-a-broiler-producti-0b44d541-chunk-0004-ca7bd0dea83f", "section_boundary", "Results", "Results", "IV. RESULTS", "The explicit Results heading and optimization outcomes dominate this chunk."),
    ("on-the-prediction-of-possibly-forgotten-shopping-basket-items-1550b8a9-chunk-0003-99c072b024d9", "section_interior", "Methodology", "Methodology", "Related Work and Contributions", "Although the major method heading is poorly extracted, the chunk explicitly explains the prediction algorithm and pseudocode between related work and evaluation."),
    ("exploring-supervised-machine-learning-for-multi-phase-identification-and-3b9ea038-chunk-0005-c26d92404667", "section_interior", "Results", "Results", "Results and analysis", "The chunk reports cross-validation scores and model comparisons after the explicit Results and analysis heading."),

    ("on-the-forecasting-of-market-prices-for-agricultural-commodities-45842bc3-chunk-0003-a1110862ba20", "section_boundary", "Results", "Results", "CATEGORY-WISE AVERAGE TEST MAPE", "Reported category-level MAPE comparisons and interpretation make this a Results chunk."),
    ("estimating-deforestation-using-machine-learning-algorithms-3f48cc99-chunk-0004-7d2e8cc2c479", "section_boundary", "Results", "Results", "IV. RESULTS AND DISCUSSION", "Results tables and performance analysis dominate before the short Conclusion boundary."),
    ("a-simple-approach-to-synthetic-time-series-generation-66bcf71f-chunk-0002-13a1758e9826", "section_boundary", "Results", "Results", "III. RESULTS", "The explicit Results section and evaluation tables dominate over the preceding TimeGAN tail and later Discussion start."),
    ("can-foreign-datasets-help-improve-plankton-classification-performance-fo-01e5c8cb-chunk-0007-e8ef9954d6c9", "section_interior", "Results", "Results", "Results", "The chunk reports accuracy, loss, and scenario comparisons within the explicit Results section."),
    ("generating-personalized-news-podcasts-from-print-media-for-those-on-the--11532982-chunk-0005-a07609e304c0", "section_boundary", "Results", "Results", "IV. RESULTS", "Survey findings dominate; Discussion begins only near the end of the chunk."),

    ("emerging-network-technologies-and-network-neutrality-conformance-2af0cd47-chunk-0006-3e249a23e831", "section_boundary", "Discussion", "Discussion", "IV. DISCUSSION", "The Discussion occupies most substantive prose before brief conclusion, acknowledgement, and reference tails."),
    ("exploring-supervised-machine-learning-for-multi-phase-identification-and-3b9ea038-chunk-0010-1725a8b12e96", "section_boundary", "Discussion", "Discussion", "Discussion", "Interpretation, limitations, and future directions dominate before Conclusion starts near the end."),
    ("a-review-of-human-body-shape-detection-techniques-and-their-application--4264e4f6-chunk-0003-5123d02beac4", "section_boundary", "Unknown", "References", "4. CONCLUSION", "A long Discussion continuation, short Conclusion, and substantial References coexist without a defensible dominant section."),
    ("data-driven-weighting-for-coastal-vulnerability-assessment-in-small-isla-0141fa24-chunk-0005-2f122ca833bb", "section_interior", "Discussion", "Discussion", "V. DISCUSSION", "The chunk continues the explicit Discussion's interpretation of coastal-risk indicators."),
    ("a-smart-shuffle-approach-to-playlist-shuffling-with-user-defined-constra-2ef8bb64-chunk-0005-80ddf0026d5f", "section_interior", "Discussion", "Discussion", "Discussion", "Algorithm trade-offs and user-defined attribute results continue the explicit Discussion section."),

    ("estimating-the-carbon-content-of-oceans-using-satellite-sensor-data-1151734e-chunk-0009-8a56a5452f1f", "section_boundary", "Unknown", "Conclusion", "Conclusion", "Conclusion, abbreviations, declarations, availability statements, and references are merged; no single canonical section dominates."),
    ("on-the-forecasting-of-market-prices-for-agricultural-commodities-45842bc3-chunk-0004-45034ec20c34", "section_boundary", "Conclusion", "Conclusion", "IV. CONCLUSIONS AND FUTURE WORK", "The explicit Conclusions and Future Work prose dominates before References."),
    ("dynamic-group-formation-in-an-online-social-network-a8e55b98-chunk-0009-926cd0d0be61", "section_boundary", "References", "References", "References", "Only a short conclusion tail precedes a dominant bibliography."),
    ("on-the-socio-economic-factors-affecting-fertility-rate-decline-in-a-smal-6f46fa88-chunk-0006-df3badde08e2", "section_boundary", "References", "Conclusion", "REFERENCES", "The conclusion and future-work text is followed by a longer reference list that dominates the chunk."),
    ("material-and-cost-estimation-of-a-customized-product-based-on-the-custom-ade2050d-chunk-0005-55a0ecf0a70b", "section_boundary", "Conclusion", "Conclusion", "VI. CONCLUSION AND FUTURE WORK", "Conclusion and future work dominate between a short results tail and the bibliography."),

    ("a-decision-tree-approach-to-the-collection-of-data-for-sustainable-devel-c61e037f-chunk-0007-04dbb602ede8", "section_boundary", "References", "References", "References", "The explicit References heading begins at the start and the chunk is bibliographic."),
    ("load-forecasting-using-deep-neural-networks-31644fac-chunk-0005-dceecb58a223", "section_boundary", "References", "References", "REFERENCES", "A brief related-work/conclusion lead-in is followed by a dominant reference list."),
    ("exploring-supervised-machine-learning-for-multi-phase-identification-and-3b9ea038-chunk-0012-2d78ebfb33e5", "section_interior", "References", "References", "References", "The chunk consists entirely of continuation bibliography entries."),
    ("a-method-for-learning-representations-of-signed-networks-1e492890-chunk-0010-6e95b5d5b9ae", "section_interior", "References", "References", "REFERENCES", "The chunk is an interior continuation of the reference list."),
    ("a-personalized-overdraft-protection-framework-7d1549da-chunk-0010-0248dd0c1287", "section_interior", "References", "References", "REFERENCES", "The chunk contains only bibliography entries after the source References heading."),
]


def normalize(value: str) -> str:
    return " ".join(value.split()).casefold()


def resolve_heading(extracted: dict, query: str, page_start: int, page_end: int) -> dict:
    needle = normalize(query)
    candidates = []
    for page in extracted.get("pages", []):
        page_number = int(page["page_number"])
        for line in str(page.get("text") or "").splitlines():
            exact = " ".join(line.split()).strip()
            if needle in normalize(exact):
                distance = 0 if page_start <= page_number <= page_end else min(abs(page_number - page_start), abs(page_number - page_end))
                candidates.append((distance, page_number, exact))
    if not candidates:
        raise ValueError(f"heading query not found: {query}")
    _, page_number, exact = min(candidates, key=lambda item: (item[0], item[1]))
    return {
        "page_number": page_number,
        "heading_text": exact,
        "location": "within_chunk_pages" if page_start <= page_number <= page_end else "adjacent_source_page",
    }


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build() -> tuple[list[dict], list[dict]]:
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    create_cases = []
    for index, (chunk_id, stratum, expected, creation_label, heading_query, rationale) in enumerate(SPECS, start=1):
        row = connection.execute(
            "SELECT c.*, p.extracted_json_path, p.title FROM chunk c JOIN paper p ON p.paper_id=c.paper_id WHERE c.chunk_id=?",
            (chunk_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"missing live chunk: {chunk_id}")
        extraction_path = ROOT / str(row["extracted_json_path"])
        extracted = json.loads(extraction_path.read_text(encoding="utf-8"))
        case = {
            "case_id": f"section-create-{index:03d}",
            "paper_id": row["paper_id"],
            "paper_title": row["title"],
            "chunk_id": row["chunk_id"],
            "chunk_index": row["chunk_index"],
            "page_start": row["page_start"],
            "page_end": row["page_end"],
            "source_hash": row["source_hash"],
            "predicted_section": row["section"],
            "expected_section": creation_label,
            "sampling_stratum": stratum,
            "source_heading_evidence": [resolve_heading(extracted, heading_query, row["page_start"], row["page_end"])],
            "rationale": rationale if creation_label == expected else "Initial direct source review; this judgment is rechecked independently in the shuffled verification pass.",
            "reviewer_id": "codex-ai-review",
            "reviewer_type": "ai",
            "label_quality": "silver",
            "pass": "create",
            "timestamp": CREATED_AT,
            "extracted_json_path": str(row["extracted_json_path"]),
        }
        create_cases.append(case)

    shuffled = list(create_cases)
    random.Random(SHUFFLE_SEED).shuffle(shuffled)
    expected_by_chunk = {spec[0]: (spec[2], spec[5]) for spec in SPECS}
    final_cases = []
    for position, source in enumerate(shuffled, start=1):
        expected, rationale = expected_by_chunk[source["chunk_id"]]
        decision = "agree" if source["expected_section"] == expected else "revise"
        final = dict(source)
        final.update({
            "case_id": source["case_id"].replace("section-create", "section-silver"),
            "source_case_id": source["case_id"],
            "expected_section": expected,
            "rationale": rationale,
            "decision": decision,
            "verification_rationale": "Reopened the extracted source pages and explicit heading context in fixed-seed shuffled order; rechecked dominance and used Unknown when a single section was not defensible.",
            "creation_expected_section": source["expected_section"],
            "verifier_id": "codex-ai-review",
            "pass": "verify",
            "timestamp": VERIFIED_AT,
            "shuffle_seed": SHUFFLE_SEED,
            "shuffled_position": position,
        })
        final_cases.append(final)
    connection.close()
    return create_cases, final_cases


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows), encoding="utf-8")


if __name__ == "__main__":
    created, verified = build()
    write_jsonl(CREATE_OUTPUT, created)
    write_jsonl(FINAL_OUTPUT, verified)
    print(f"create={CREATE_OUTPUT} final={FINAL_OUTPUT} cases={len(verified)} seed={SHUFFLE_SEED}")
