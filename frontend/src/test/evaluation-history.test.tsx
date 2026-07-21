import { render, screen, within } from "@testing-library/react";

import { EvaluationDashboardPage } from "../pages/EvaluationDashboardPage";
import { json } from "./fixtures";

describe("evaluation provenance state", () => {
  it("keeps negative historical metrics visible while warning that they are not current", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(await json({
      evaluation_label: "AI-reviewed silver offline evaluation; no recruited human participants",
      evaluation_status: "historical",
      freshness: {
        status: "historical",
        notice: "Historical results are retained evidence and are not presented as current runtime evaluation.",
      },
      retrieval: section({ question_count: 50, recall_at_3: 0.4, recall_at_5: 0.5, mrr: 0.3 }),
      qa: section({
        question_count: 50,
        answer_count: 50,
        cited_gold_paper_count: 0,
        citation_count: 25,
        claim_count: 400,
        citation_correctness: 0.625,
        grounding_counts: { supported: 398, partial: 2, unsupported: 0 },
      }),
      extension: section({
        case_count: 28,
        recommendation_count: 84,
        citation_coverage: 1,
        grounding_counts: {},
        warnings_count: 84,
        evidence_only_relevance: 0.631,
        full_finder_relevance: 0.655,
        relevance_difference: 0.0238,
        relevance_difference_ci: [-0.0238, 0.0714],
      }),
      artifact: section({
        case_count: 48,
        artifact_count: 14,
        citation_coverage: null,
        grounding_counts: {},
        warnings_count: 0,
        sections_with_explicit_support: 0,
        sections_inferred: 0,
        sections_not_found: 0,
      }),
      human_review_templates: {},
      overall_quality: {},
      result_files: {},
    }));

    render(<EvaluationDashboardPage />);

    expect(await screen.findByText("Historical evaluation snapshot.")).toBeInTheDocument();
    expect(screen.getAllByText("historical")).toHaveLength(4);
    expect(screen.getByText("Citation correctness")).toBeInTheDocument();
    expect(screen.getByText("0.625")).toBeInTheDocument();
    expect(screen.getByText("Full minus evidence-only")).toBeInTheDocument();
    expect(screen.getByText("0.024")).toBeInTheDocument();
    expect(screen.queryByText("Result file not run yet")).not.toBeInTheDocument();
  });

  it("renders identity-valid v2 evidence as current without relabeling retained v1 cards", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(await json({
      evaluation_label: "AI-reviewed silver offline evaluation; no recruited human participants",
      evaluation_status: "current",
      freshness: {
        status: "current",
        notice: "Frozen v2 identities validate.",
        peer_review_remediation_v2: {
          status: "current",
          checks: { code: "match", corpus: "match", configuration: "match", release: "match", manifest: "match" },
          freshness_contract: "frozen_inputs_and_outputs_v2",
        },
      },
      peer_review_remediation_v2: {
        status: "completed",
        evaluation_id: "peer-review-remediation-v2",
        evidence_tier: "ai_silver",
        reviewer_type: "ai",
        human_validation: false,
        entailment_claimed: false,
        technical_scope_only: true,
        public_projection_exercised: false,
        claim_boundary: "AI-silver technical-corpus evidence; no human usefulness or semantic-entailment claim.",
        qa_test: {
          case_count: 12,
          metrics: {
            answerability_precision: 0.75,
            answerability_recall: 0.5,
            false_positive_rate: 0.25,
            exact_gold_locator_citation_precision: 0.625,
            citation_completeness: 0.8,
            answer_point_coverage: 0.7,
          },
        },
        finder_test: {
          profile_count: 5,
          metrics: {
            evidence_only_hit_at_3: 0.6,
            full_finder_hit_at_3: 0.4,
            paired_hit_at_3_delta: -0.2,
            evidence_only_mrr: 0.55,
            full_finder_mrr: 0.45,
            source_fact_suggestion_separation_rate: 1,
            full_profile_constraint_contract_fidelity_rate: 0.8,
          },
        },
        topics_test: {
          case_count: 8,
          label_scope: "positive_only_not_exhaustive_closed_world",
          known_positive_micro: { matched: 6, missed: 2, recall: 0.75 },
          known_positive_case_coverage_rate: 0.625,
          unadjudicated_predictions: {
            count: 11,
            total_predictions: 19,
            share: 0.579,
            false_positive_interpretation_permitted: false,
          },
        },
        ocr: {
          status: "completed",
          metrics: {
            ocr_status: "completed",
            character_error_rate: 0.01,
            word_error_rate: 0.02,
            normalized_exact_match: false,
            repeat_run_text_identical: true,
          },
          claim_boundary: "Synthetic fixture only; not corpus OCR accuracy.",
        },
      },
      retrieval: section({ question_count: 50, recall_at_3: 0.4, recall_at_5: 0.5, mrr: 0.3 }),
      qa: section({ question_count: 50, answer_count: 50, cited_gold_paper_count: 0, citation_count: 25, grounding_counts: {} }),
      extension: section({ case_count: 28, recommendation_count: 84, citation_coverage: 1, grounding_counts: {}, warnings_count: 84 }),
      artifact: section({ case_count: 48, artifact_count: 14, citation_coverage: null, grounding_counts: {}, warnings_count: 0, sections_with_explicit_support: 0, sections_inferred: 0, sections_not_found: 0 }),
      human_review_templates: {},
      overall_quality: {},
      result_files: {},
    }));

    render(<EvaluationDashboardPage />);

    const v2 = await screen.findByRole("region", { name: "Peer-review remediation v2 evidence" });
    expect(within(v2).getByText("Identity-validated current AI-reviewed silver package.")).toBeInTheDocument();
    expect(v2).toHaveAttribute("data-evaluation-v2-status", "current");
    expect(within(v2).getByText("Technical corpus only")).toBeInTheDocument();
    expect(within(v2).getByText("Public projection not exercised")).toBeInTheDocument();
    expect(within(v2).getByText("No human validation")).toBeInTheDocument();
    expect(within(v2).getByText("-0.200")).toBeInTheDocument();
    const topicCard = screen.getByRole("heading", { name: "Topic assignment (held out)" }).closest("article");
    expect(topicCard).not.toBeNull();
    expect(within(topicCard!).getByText("Known-positive micro recall")).toBeInTheDocument();
    expect(within(topicCard!).getByText("0.750")).toBeInTheDocument();
    expect(within(topicCard!).getByText("Known-positive case coverage")).toBeInTheDocument();
    expect(within(topicCard!).getByText("Unadjudicated predictions")).toBeInTheDocument();
    expect(within(topicCard!).getByText("11")).toBeInTheDocument();
    expect(within(topicCard!).getByText("Unlisted predictions are unadjudicated, not false positives.")).toBeInTheDocument();
    expect(within(topicCard!).queryByText("Micro precision")).not.toBeInTheDocument();
    expect(within(topicCard!).queryByText("Micro F1")).not.toBeInTheDocument();
    expect(within(topicCard!).queryByText("Exact-match rate")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Historical v1 evidence" })).toBeInTheDocument();
    expect(screen.getAllByText("historical")).toHaveLength(4);
    expect(screen.queryByText("Historical evaluation snapshot.")).not.toBeInTheDocument();
  });

  it("refuses a current label when a required v2 identity check fails", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(await json({
      evaluation_label: "AI-reviewed silver offline evaluation; no recruited human participants",
      evaluation_status: "current",
      freshness: {
        status: "current",
        notice: "The package reported current, but a required output identity does not match.",
        peer_review_remediation_v2: {
          status: "current",
          checks: { code: "match", corpus: "match", configuration: "match", release: "mismatch", manifest: "match" },
          freshness_contract: "frozen_inputs_and_outputs_v2",
        },
      },
      peer_review_remediation_v2: {
        status: "completed",
        evaluation_id: "peer-review-remediation-v2",
        evidence_tier: "ai_silver",
        reviewer_type: "ai",
        human_validation: false,
        entailment_claimed: false,
        technical_scope_only: true,
        public_projection_exercised: false,
        qa_test: { case_count: 1, metrics: {} },
        topics_test: {
          case_count: 1,
          label_scope: "positive_only_not_exhaustive_closed_world",
          known_positive_micro: { matched: 1, missed: 0, recall: 1 },
          known_positive_case_coverage_rate: 1,
          unadjudicated_predictions: {
            count: 1,
            total_predictions: 2,
            share: 0.5,
            false_positive_interpretation_permitted: false,
          },
        },
      },
      retrieval: section({ question_count: 1, recall_at_3: 0, recall_at_5: 0, mrr: 0 }),
      qa: section({ question_count: 1, answer_count: 1, cited_gold_paper_count: 0, citation_count: 0, grounding_counts: {} }),
      extension: section({ case_count: 1, recommendation_count: 1, citation_coverage: 0, grounding_counts: {}, warnings_count: 1 }),
      artifact: section({ case_count: 1, artifact_count: 1, citation_coverage: 0, grounding_counts: {}, warnings_count: 1, sections_with_explicit_support: 0, sections_inferred: 0, sections_not_found: 1 }),
      human_review_templates: {},
      overall_quality: {},
      result_files: {},
    }));

    render(<EvaluationDashboardPage />);

    const v2 = await screen.findByRole("region", { name: "Peer-review remediation v2 evidence" });
    expect(within(v2).getByText("Completed v2 package is not current.")).toBeInTheDocument();
    expect(within(v2).getByText("The required frozen identity checks or freshness contract are incomplete or mismatched.")).toBeInTheDocument();
    expect(v2).toHaveAttribute("data-evaluation-v2-status", "identity_invalid");
    expect(within(v2).queryByText("Identity-validated current AI-reviewed silver package.")).not.toBeInTheDocument();
    expect(screen.queryByText("Evaluation evidence is not current.")).not.toBeInTheDocument();
  });
});

function section(values: Record<string, unknown>) {
  return {
    status: "historical",
    freshness_status: "historical",
    result_file_exists: true,
    path: "artifacts/historical.json",
    last_run_timestamp: "2026-01-01T00:00:00Z",
    ...values,
  };
}
