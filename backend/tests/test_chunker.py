import pytest

from app.indexing.chunker import (
    build_chunks_from_extraction,
    detect_section_boundary,
    detect_section_heading,
    infer_section,
    is_strong_section_heading,
    page_sentence_units,
)


def make_extracted_fixture() -> dict[str, object]:
    page_one = "Introduction. " + " ".join(
        f"Sentence {index} explains the research platform with enough words for chunking."
        for index in range(90)
    )
    page_two = "Methodology. " + " ".join(
        f"Sentence {index} describes deterministic extraction and chunk creation for source citation."
        for index in range(90, 180)
    )
    return {
        "paper_id": "chunk-paper",
        "pages": [
            {"page_number": 1, "text": page_one},
            {"page_number": 2, "text": page_two},
        ],
    }


def test_chunker_creates_page_aware_chunks() -> None:
    chunks = build_chunks_from_extraction(make_extracted_fixture(), target_words=140, overlap_words=30)

    assert len(chunks) > 1
    assert chunks[0]["page_start"] == 1
    assert chunks[-1]["page_end"] == 2
    assert all(chunk["paper_id"] == "chunk-paper" for chunk in chunks)


def test_chunker_preserves_overlap_and_stable_ids() -> None:
    extracted = make_extracted_fixture()
    chunks = build_chunks_from_extraction(extracted, target_words=140, overlap_words=30)
    repeated = build_chunks_from_extraction(extracted, target_words=140, overlap_words=30)
    first_words = set(chunks[0]["text"].split())
    second_words = set(chunks[1]["text"].split())

    assert first_words.intersection(second_words)
    assert [chunk["chunk_id"] for chunk in chunks] == [chunk["chunk_id"] for chunk in repeated]


def test_section_detection_requires_heading_evidence() -> None:
    assert infer_section("This study uses a methodology based on interviews and reports results later.") == "Unknown"
    assert infer_section("II. METHODOLOGY\nWe created a deterministic extraction pipeline.") == "Methodology"
    assert infer_section("Abstract This paper presents a source-traceable system.") == "Abstract"


def test_section_heading_propagates_conservatively_across_page_units() -> None:
    extracted = {
        "paper_id": "sections",
        "pages": [
            {
                "page_number": 1,
                "text": "II. METHODOLOGY\nWe constructed the system. We recorded each configuration.",
            },
            {
                "page_number": 2,
                "text": "We continued the experiment without repeating the heading.",
            },
        ],
    }

    chunks = build_chunks_from_extraction(extracted, target_words=20, overlap_words=0, min_chars=0)

    assert chunks
    assert all(chunk["section"] == "Methodology" for chunk in chunks)


@pytest.mark.parametrize(
    ("heading", "expected"),
    [
        ("II. RELATED WORK AND CONTRIBUTIONS", "Literature Review"),
        ("RELATED WORKS", "Literature Review"),
        ("DATA", "Methodology"),
        ("DATASET", "Methodology"),
        ("III. DATA DESCRIPTION", "Methodology"),
        ("DESCRIPTION OF DATASETS", "Methodology"),
        ("IV. PROPOSED APPROACH", "Methodology"),
        ("V. TRADITIONAL APPROACH", "Methodology"),
        ("MODEL DESCRIPTION", "Methodology"),
        ("FRAMEWORK", "Methodology"),
        ("IMPLEMENTATION", "Methodology"),
        ("EXPERIMENTAL SETUP", "Methodology"),
        ("VI. COMPARISON", "Discussion"),
        ("VII. SUMMARY AND CONCLUSIONS", "Conclusion"),
        ("Results and analysis", "Results"),
        ("NUMERICAL RESULTS", "Results"),
        ("EXPERIMENTAL RESULTS", "Results"),
        ("PERFORMANCE EVALUATION", "Results"),
        ("ANALYSIS", "Results"),
        ("EVALUATION", "Results"),
        ("LIMITATIONS AND FUTURE DIRECTIONS", "Conclusion"),
        ("CONCLUSIONS AND RECOMMENDATIONS", "Conclusion"),
        ("CONCLUSION AND FUTURE WORK", "Conclusion"),
        ("RECOMMENDATIONS", "Conclusion"),
    ],
)
def test_observed_major_heading_aliases(heading: str, expected: str) -> None:
    assert detect_section_heading(heading) == expected


def test_employee_performance_headings_replace_related_work_state() -> None:
    extracted = {
        "paper_id": "employee-performance",
        "pages": [
            {
                "page_number": 1,
                "text": "\n".join(
                    [
                        "II. RELATED WORK",
                        "Prior studies compared review techniques.",
                        "III. DATA DESCRIPTION",
                        "The dataset contains employee records.",
                        "IV. PROPOSED APPROACH",
                        "The learned model estimates performance.",
                        "V. TRADITIONAL APPROACH",
                        "Managers assign weighted scores.",
                        "VI. COMPARISON",
                        "The outputs differ for several employees.",
                        "VII. SUMMARY AND CONCLUSIONS",
                        "The study summarizes the observed differences.",
                    ]
                ),
            }
        ],
    }

    units = page_sentence_units(extracted)
    hints_by_text = {unit["text"]: unit["section_hint"] for unit in units}

    assert hints_by_text["Prior studies compared review techniques."] == "Literature Review"
    assert hints_by_text["The dataset contains employee records."] == "Methodology"
    assert hints_by_text["The learned model estimates performance."] == "Methodology"
    assert hints_by_text["Managers assign weighted scores."] == "Methodology"
    assert hints_by_text["The outputs differ for several employees."] == "Discussion"
    assert hints_by_text["The study summarizes the observed differences."] == "Conclusion"


def test_strong_unmapped_heading_resets_state_to_unknown() -> None:
    extracted = {
        "paper_id": "reset-section",
        "pages": [
            {
                "page_number": 1,
                "text": "\n".join(
                    [
                        "II. RELATED WORK",
                        "Prior studies are reviewed.",
                        "III. DOMAIN-SPECIFIC CONSIDERATIONS",
                        "This evidence cannot be assigned to a canonical section.",
                    ]
                ),
            }
        ],
    }

    units = page_sentence_units(extracted)
    target = next(unit for unit in units if unit["text"].startswith("This evidence"))

    assert detect_section_boundary("III. DOMAIN-SPECIFIC CONSIDERATIONS") == (True, None)
    assert target["section_hint"] == "Unknown"


def test_strong_uppercase_unmapped_heading_resets_state_to_unknown() -> None:
    assert detect_section_boundary("SYSTEM ARCHITECTURE") == (True, None)


@pytest.mark.parametrize(
    "line",
    [
        "1) Mean: For t = 1 . . . T, note that",
        "2.1 births per woman, marking a decisive break from earlier years.",
        "TABLE II",
        "Fig. 8.",
        "N(N + 1) = 42",
        "2017.",
        "D.",
        "2025 International Conference on Decision Aid Sciences and Applications (DASA)",
        "Data-Driven Output",
        "limitations. We begin by exploring the progression from traditional methods.",
        "introduction. Comput. Optim. Appl. 1 (1), 7-66.",
    ],
)
def test_formula_table_numeric_and_lowercase_prose_are_not_major_headings(line: str) -> None:
    assert is_strong_section_heading(line) is False
    assert detect_section_heading(line) is None


def test_front_and_back_matter_reset_abstract_and_conclusion_leakage() -> None:
    extracted = {
        "paper_id": "matter-boundaries",
        "pages": [
            {
                "page_number": 1,
                "text": "Abstract\nA short summary.\nKeywords\nretrieval, ranking\nCOPYRIGHT MATERIAL\nPublisher material.",
            },
            {
                "page_number": 2,
                "text": "Conclusion\nThe study concludes.\nAbbreviations\nIR information retrieval\nReferences\n[1] A source.",
            },
        ],
    }

    units = page_sentence_units(extracted)
    hints_by_text = {unit["text"]: unit["section_hint"] for unit in units}

    assert hints_by_text["A short summary."] == "Abstract"
    assert hints_by_text["retrieval, ranking"] == "Unknown"
    assert hints_by_text["Publisher material."] == "Unknown"
    assert hints_by_text["The study concludes."] == "Conclusion"
    assert hints_by_text["IR information retrieval"] == "Unknown"
    assert hints_by_text["[1] A source."] == "References"


def test_interleaved_abstract_does_not_override_substantive_body_section() -> None:
    extracted = {
        "paper_id": "two-column-order",
        "pages": [
            {
                "page_number": 1,
                "text": "II. RELATED WORK\nPrior classifiers are compared.\nAbstract—The extraction placed this column late.\nMore comparison text follows.",
            }
        ],
    }

    units = page_sentence_units(extracted)
    hints_by_text = {unit["text"]: unit["section_hint"] for unit in units}

    assert hints_by_text["More comparison text follows."] == "Literature Review"
