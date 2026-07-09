import { useEffect, useState } from "react";
import type { ReactNode } from "react";

import { fetchEvaluationDashboard } from "../api/client";
import { EmptyState, ListSkeleton } from "../components/UiPrimitives";
import type { EvaluationDashboard, EvaluationSectionStatus } from "../types/paper";

export function EvaluationDashboardPage() {
  const [dashboard, setDashboard] = useState<EvaluationDashboard | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchEvaluationDashboard()
      .then(setDashboard)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Unable to load evaluation dashboard."));
  }, []);

  if (error) {
    return (
      <section className="page-section">
        <p className="notice notice--error">{error}</p>
      </section>
    );
  }

  if (!dashboard) {
    return (
      <section className="page-section">
        <div className="evaluation-grid" aria-label="Loading evaluation dashboard" aria-busy="true">
          <ListSkeleton count={2} lines={4} />
          <ListSkeleton count={2} lines={4} />
        </div>
      </section>
    );
  }

  return (
    <section className="page-section">
      <p className="notice notice--warning">
        Evaluation results are only as valid as the reviewed gold/test cases. Missing result files are shown as not run.
      </p>

      <div className="evaluation-grid">
        <EvaluationCard title="Retrieval Evaluation" section={dashboard.retrieval}>
          <MetricRow label="Questions" value={dashboard.retrieval.question_count} />
          <MetricRow label="Recall@3" value={formatMetric(dashboard.retrieval.recall_at_3)} />
          <MetricRow label="Recall@5" value={formatMetric(dashboard.retrieval.recall_at_5)} />
          <MetricRow label="MRR" value={formatMetric(dashboard.retrieval.mrr)} />
        </EvaluationCard>

        <EvaluationCard title="Ask / QA Evaluation" section={dashboard.qa}>
          <MetricRow label="Questions" value={dashboard.qa.question_count} />
          <MetricRow label="Answers" value={dashboard.qa.answer_count} />
          <MetricRow label="Cited gold papers" value={dashboard.qa.cited_gold_paper_count} />
          <MetricRow label="Citations" value={dashboard.qa.citation_count} />
          <GroundingRows counts={dashboard.qa.grounding_counts} />
        </EvaluationCard>

        <EvaluationCard title="Thesis Extension Evaluation" section={dashboard.extension}>
          <MetricRow label="Cases" value={dashboard.extension.case_count} />
          <MetricRow label="Recommendations" value={dashboard.extension.recommendation_count} />
          <MetricRow label="Citation coverage" value={formatMetric(dashboard.extension.citation_coverage)} />
          <MetricRow label="Warnings" value={dashboard.extension.warnings_count} />
          <GroundingRows counts={dashboard.extension.grounding_counts} />
        </EvaluationCard>

        <EvaluationCard title="Artifact Evaluation" section={dashboard.artifact}>
          <MetricRow label="Cases" value={dashboard.artifact.case_count} />
          <MetricRow label="Artifacts" value={dashboard.artifact.artifact_count} />
          <MetricRow label="Citation coverage" value={formatMetric(dashboard.artifact.citation_coverage)} />
          <MetricRow label="Explicit sections" value={dashboard.artifact.sections_with_explicit_support} />
          <MetricRow label="Inferred sections" value={dashboard.artifact.sections_inferred} />
          <MetricRow label="Not found sections" value={dashboard.artifact.sections_not_found} />
          <GroundingRows counts={dashboard.artifact.grounding_counts} />
        </EvaluationCard>
      </div>

      <div className="admin-grid">
        <article className="admin-card">
          <h2>Human Review Templates</h2>
          <div className="status-table">
            {Object.entries(dashboard.human_review_templates).map(([key, value]) => (
              <p key={key}>
                <span>{key.replaceAll("_", " ")}</span>
                <strong>{value ? "available" : "missing"}</strong>
              </p>
            ))}
          </div>
        </article>
        <article className="admin-card">
          <h2>Overall Quality Summary</h2>
          <div className="status-table">
            {Object.entries(dashboard.overall_quality).map(([key, value]) => (
              <p key={key}>
                <span>{key.replaceAll("_", " ")}</span>
                <strong>{value}</strong>
              </p>
            ))}
          </div>
        </article>
      </div>
    </section>
  );
}

function EvaluationCard({
  title,
  section,
  children,
}: {
  title: string;
  section: EvaluationSectionStatus;
  children: ReactNode;
}) {
  return (
    <article className="admin-card">
      <div className="paper-card__meta">
        <span className={`grounding ${section.status === "available" ? "grounding--grounded" : "grounding--partial"}`}>
          {section.status.replaceAll("_", " ")}
        </span>
        <span>{section.last_run_timestamp ? `Last run ${new Date(section.last_run_timestamp).toLocaleString()}` : "No run timestamp"}</span>
      </div>
      <h2>{title}</h2>
      {section.status === "available" ? (
        <div className="status-table">{children}</div>
      ) : (
        <EmptyState
          title="Result file not run yet"
          body="Run the matching evaluation CLI command when you have reviewed gold/test cases for this section."
        />
      )}
    </article>
  );
}

function MetricRow({ label, value }: { label: string; value: string | number }) {
  return (
    <p>
      <span>{label}</span>
      <strong>{value}</strong>
    </p>
  );
}

function GroundingRows({ counts }: { counts: Record<string, number> }) {
  return (
    <>
      {Object.entries(counts).map(([key, value]) => (
        <MetricRow key={key} label={key} value={value} />
      ))}
    </>
  );
}

function formatMetric(value: number | null): string {
  return value === null ? "not run" : value.toFixed(3);
}
