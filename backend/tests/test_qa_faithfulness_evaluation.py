from app.evaluation.qa_faithfulness_eval import calculate_faithfulness_metrics, segment_atomic_claims


def test_claim_segmenter_ignores_paper_bibliography_markers_and_splits_authorship() -> None:
    chunk_id = "paper-chunk-0001"
    result = segment_atomic_claims(
        "- Pat Researcher: appears on First Paper; Second Paper. [12] " f"[{chunk_id}]",
        case_id="qa-silver-001",
        source_map={chunk_id: chunk_id},
    )

    assert [claim["text"] for claim in result["claims"]] == [
        'Pat Researcher authored or co-authored "First Paper"',
        'Pat Researcher authored or co-authored "Second Paper"',
    ]
    assert all(claim["inline_source_ids"] == [chunk_id] for claim in result["claims"])


def test_claim_segmenter_detects_explicit_abstention() -> None:
    result = segment_atomic_claims(
        "I could not answer this from the indexed TTLAB papers.",
        case_id="qa-silver-050",
    )

    assert result["did_abstain"] is True
    assert result["claims"] == []


def test_faithfulness_metrics_keep_support_coverage_and_abstention_distinct() -> None:
    rows = [
        _row(
            "qa-silver-001",
            answerability="answerable",
            did_abstain=False,
            support="supported",
            citation="correct",
            point="covered",
        ),
        _row(
            "qa-silver-002",
            answerability="answerable",
            did_abstain=False,
            support="supported",
            citation="partially_correct",
            point="not_covered",
        ),
        _row(
            "qa-silver-003",
            answerability="unanswerable",
            did_abstain=False,
            support="supported",
            citation="correct",
            point=None,
        ),
    ]

    result = calculate_faithfulness_metrics(rows)

    assert result["metrics"]["supported_claim_rate"] == 1.0
    assert result["metrics"]["citation_precision_correctness"] == 0.666667
    assert result["metrics"]["citation_completeness"] == 1.0
    assert result["metrics"]["answer_point_coverage"] == 0.5
    assert result["metrics"]["abstention_accuracy"] == 0.666667
    assert result["metrics"]["unanswerable_abstention_rate"] == 0.0


def _row(
    case_id: str,
    *,
    answerability: str,
    did_abstain: bool,
    support: str,
    citation: str,
    point: str | None,
) -> dict:
    claim = {
        "claim_id": f"{case_id}-claim-001",
        "checkable_corpus_claim": True,
        "support_label": support,
        "inline_source_ids": ["chunk-1"],
        "citation_judgments": [
            {"source_id": "chunk-1", "citation_label": citation},
        ],
        "unsupported_general_knowledge": False,
        "error_codes": [],
    }
    point_rows = [] if point is None else [{"answer_point_id": f"{case_id}-point-01", "coverage_label": point}]
    review = {
        "did_abstain": did_abstain,
        "claim_judgments": [claim],
        "answer_point_judgments": point_rows,
    }
    return {
        "qa_case_id": case_id,
        "category": "test",
        "answerability": answerability,
        "did_abstain": did_abstain,
        "returned_citation_ids": ["chunk-1"],
        "adjudicated_claims": [claim],
        "adjudicated_answer_points": point_rows,
        "case_error_codes": [],
        "creation_review": review,
        "verification_review": review,
    }
