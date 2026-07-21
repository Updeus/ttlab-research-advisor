import { render, screen } from "@testing-library/react";

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
