import { useEffect, useState } from "react";
import type { ReactNode } from "react";

import { fetchEvaluationDashboard } from "../api/client";
import { EmptyState, ListSkeleton } from "../components/UiPrimitives";
import type {
  EvaluationDashboard,
  EvaluationSectionStatus,
  EvaluationV2Freshness,
  EvaluationV2Package,
} from "../types/paper";

export function EvaluationDashboardPage() {
  const [dashboard, setDashboard] = useState<EvaluationDashboard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  function loadDashboard() {
    setLoading(true);
    setError(null);
    fetchEvaluationDashboard()
      .then(setDashboard)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Unable to load evaluation dashboard."))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    loadDashboard();
  }, []);

  if (error) {
    return (
      <section className="page-section">
        <div className="notice notice--error" role="alert">
          <p>{error}</p>
          <button className="action-button" onClick={loadDashboard}>Retry evaluation dashboard</button>
        </div>
      </section>
    );
  }

  if (loading && !dashboard) {
    return (
      <section className="page-section">
        <div className="evaluation-grid" aria-label="Loading evaluation dashboard" aria-busy="true">
          <ListSkeleton count={2} lines={4} />
          <ListSkeleton count={2} lines={4} />
        </div>
      </section>
    );
  }

  if (!dashboard) {
    return <section className="page-section"><EmptyState title="No evaluation dashboard response" body="The service returned no evaluation state." /></section>;
  }

  const overallFreshness = dashboard.freshness?.status ?? dashboard.evaluation_status;
  const historicalOverall = overallFreshness === "historical";
  const nonCurrentOverall = Boolean(overallFreshness && overallFreshness !== "current");

  return (
    <section className="page-section" aria-labelledby="evaluation-title" data-manuscript-capture="evaluation">
      <h2 id="evaluation-title" className="sr-only">Evaluation dashboard</h2>
      <p className="notice notice--warning">
        {dashboard.evaluation_label ?? "Evaluation results are only as valid as their reviewed cases. Missing result files are shown as not run."}
      </p>
      {nonCurrentOverall ? (
        <div className="notice notice--warning" role="status">
          <strong>{historicalOverall ? "Historical evaluation snapshot." : "Evaluation evidence is not current."}</strong>{" "}
          {dashboard.freshness?.notice ?? "The retained results do not match the current code, corpus, or configuration identity."}
          <p>Negative and null findings remain visible below, but these values must not be described as a current runtime measurement.</p>
        </div>
      ) : null}

      <V2EvidencePackage
        evidence={dashboard.peer_review_remediation_v2}
        freshness={dashboard.freshness?.peer_review_remediation_v2}
      />

      <section className="evaluation-history" aria-labelledby="evaluation-v1-title">
        <div className="section-heading section-heading--compact">
          <div>
            <p className="eyebrow">Retained comparison record</p>
            <h2 id="evaluation-v1-title">Historical v1 evidence</h2>
          </div>
        </div>
        <p className="notice notice--warning">
          Each card below keeps its own provenance status. A current v2 package does not make these retained v1 measurements current.
        </p>

        <div className="evaluation-grid">
        <EvaluationCard title="Retrieval Evaluation" section={dashboard.retrieval}>
          <MetricRow label="Questions" value={dashboard.retrieval.question_count} />
          {dashboard.retrieval.development_count !== undefined && <MetricRow label="Development / held-out" value={`${dashboard.retrieval.development_count} / ${dashboard.retrieval.test_count}`} />}
          {dashboard.retrieval.reported_mode && <MetricRow label="Displayed baseline" value={dashboard.retrieval.reported_mode} />}
          <MetricRow label="Recall@3" value={formatMetric(dashboard.retrieval.recall_at_3)} />
          <MetricRow label="Recall@5" value={formatMetric(dashboard.retrieval.recall_at_5)} />
          {dashboard.retrieval.recall_at_10 !== undefined && <MetricRow label="Recall@10" value={formatMetric(dashboard.retrieval.recall_at_10 ?? null)} />}
          <MetricRow label="MRR" value={formatMetric(dashboard.retrieval.mrr)} />
          {dashboard.retrieval.ndcg_at_10 !== undefined && <MetricRow label="nDCG@10" value={formatMetric(dashboard.retrieval.ndcg_at_10 ?? null)} />}
          {dashboard.retrieval.tuned_hybrid_recall_at_10 !== undefined && <MetricRow label="Tuned hybrid Recall@10" value={formatMetric(dashboard.retrieval.tuned_hybrid_recall_at_10)} />}
          {dashboard.retrieval.unanswerable_false_positive_rate !== undefined && <MetricRow label="Unanswerable false-positive rate" value={formatMetric(dashboard.retrieval.unanswerable_false_positive_rate)} />}
          {dashboard.retrieval.statistical_conclusion && <MetricRow label="Paired comparison" value={dashboard.retrieval.statistical_conclusion} />}
        </EvaluationCard>

        <EvaluationCard title="Ask / QA Evaluation" section={dashboard.qa}>
          <MetricRow label="Questions" value={dashboard.qa.question_count} />
          <MetricRow label="Answers" value={dashboard.qa.answer_count} />
          {dashboard.qa.claim_count !== undefined ? (
            <>
              <MetricRow label="Checkable claims" value={dashboard.qa.claim_count} />
              <MetricRow label="Supported-claim rate" value={formatMetric(dashboard.qa.supported_claim_rate ?? null)} />
              <MetricRow label="Citation correctness" value={formatMetric(dashboard.qa.citation_correctness ?? null)} />
              <MetricRow label="Citation completeness" value={formatMetric(dashboard.qa.citation_completeness ?? null)} />
              <MetricRow label="Answer-point coverage" value={formatMetric(dashboard.qa.answer_point_coverage ?? null)} />
              <MetricRow label="Unanswerable abstention" value={formatMetric(dashboard.qa.unanswerable_abstention_rate ?? null)} />
              <MetricRow label="Reviewer type" value={dashboard.qa.reviewer_type ?? "not recorded"} />
            </>
          ) : (
            <>
              <MetricRow label="Cited gold papers" value={dashboard.qa.cited_gold_paper_count} />
              <MetricRow label="Citations" value={dashboard.qa.citation_count} />
              <GroundingRows counts={dashboard.qa.grounding_counts} />
            </>
          )}
        </EvaluationCard>

        <EvaluationCard title="Thesis Extension Evaluation" section={dashboard.extension}>
          <MetricRow label="Cases" value={dashboard.extension.case_count} />
          <MetricRow label="Reviewed recommendations" value={dashboard.extension.recommendation_count} />
          {dashboard.extension.evidence_only_relevance !== undefined ? (
            <>
              <MetricRow label="Evidence-only relevance" value={formatMetric(dashboard.extension.evidence_only_relevance)} />
              <MetricRow label="Full-finder relevance" value={formatMetric(dashboard.extension.full_finder_relevance ?? null)} />
              <MetricRow label="Full minus evidence-only" value={formatMetric(dashboard.extension.relevance_difference ?? null)} />
              <MetricRow label="Difference 95% CI" value={formatInterval(dashboard.extension.relevance_difference_ci)} />
              <MetricRow label="Reviewer type" value={dashboard.extension.reviewer_type ?? "not recorded"} />
              {dashboard.extension.proxy_notice && <MetricRow label="Validation boundary" value={dashboard.extension.proxy_notice} />}
            </>
          ) : (
            <>
              <MetricRow label="Citation coverage" value={formatMetric(dashboard.extension.citation_coverage)} />
              <MetricRow label="Warnings" value={dashboard.extension.warnings_count} />
              <GroundingRows counts={dashboard.extension.grounding_counts} />
            </>
          )}
        </EvaluationCard>

        <EvaluationCard title="Generated-output AI Review" section={dashboard.artifact}>
          {dashboard.artifact.review_event_count !== undefined ? (
            <>
              <MetricRow label="Inspected outputs" value={dashboard.artifact.case_count} />
              <MetricRow label="Append-only review events" value={dashboard.artifact.review_event_count} />
              <MetricRow label="AI-reviewed outputs" value={dashboard.artifact.ai_reviewed_count ?? 0} />
              <MetricRow label="Needs reprocessing" value={dashboard.artifact.needs_reprocess_count ?? 0} />
              <MetricRow label="Evidence locators checked" value={dashboard.artifact.citation_evidence_locator_count ?? 0} />
              <MetricRow label="Reviewer type" value={dashboard.artifact.reviewer_type ?? "not recorded"} />
              {dashboard.artifact.review_notice && <MetricRow label="Review boundary" value={dashboard.artifact.review_notice} />}
            </>
          ) : (
            <>
              <MetricRow label="Cases" value={dashboard.artifact.case_count} />
              <MetricRow label="Artifacts" value={dashboard.artifact.artifact_count} />
              <MetricRow label="Citation coverage" value={formatMetric(dashboard.artifact.citation_coverage)} />
              <MetricRow label="Explicit sections" value={dashboard.artifact.sections_with_explicit_support} />
              <MetricRow label="Inferred sections" value={dashboard.artifact.sections_inferred} />
              <MetricRow label="Not found sections" value={dashboard.artifact.sections_not_found} />
              <GroundingRows counts={dashboard.artifact.grounding_counts} />
            </>
          )}
        </EvaluationCard>
        </div>
      </section>

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

function V2EvidencePackage({
  evidence,
  freshness,
}: {
  evidence: EvaluationV2Package | undefined;
  freshness: EvaluationV2Freshness | undefined;
}) {
  const boundaryValid = Boolean(
    evidence
    && evidence.evidence_tier === "ai_silver"
    && evidence.reviewer_type === "ai"
    && evidence.human_validation === false
    && evidence.entailment_claimed === false
    && evidence.technical_scope_only === true
    && evidence.public_projection_exercised === false,
  );
  const identityChecksValid = ["code", "corpus", "configuration", "release", "manifest"]
    .every((key) => freshness?.checks?.[key] === "match");
  const identityContractValid = freshness?.freshness_contract === "frozen_inputs_and_outputs_v2";
  const topicSummaryValid = Boolean(
    evidence?.topics_test?.label_scope === "positive_only_not_exhaustive_closed_world"
    && typeof evidence.topics_test.known_positive_micro?.recall === "number"
    && typeof evidence.topics_test.known_positive_case_coverage_rate === "number"
    && typeof evidence.topics_test.unadjudicated_predictions?.count === "number"
    && typeof evidence.topics_test.unadjudicated_predictions?.share === "number"
    && evidence.topics_test.unadjudicated_predictions?.false_positive_interpretation_permitted === false,
  );
  const completed = evidence?.status === "completed";
  const identityCurrent = completed
    && freshness?.status === "current"
    && identityChecksValid
    && identityContractValid
    && topicSummaryValid
    && boundaryValid;
  const presentationStatus = identityCurrent
    ? "current"
    : completed && freshness?.status === "current"
      ? "identity_invalid"
      : freshness?.status ?? evidence?.status ?? "not_run";
  const qaMetrics = evidence?.qa_test?.metrics;
  const finderMetrics = evidence?.finder_test?.metrics;
  const topicKnownPositive = evidence?.topics_test?.known_positive_micro;
  const unadjudicatedTopics = evidence?.topics_test?.unadjudicated_predictions;
  const ocrMetrics = evidence?.ocr?.metrics;

  return (
    <section
      className="evaluation-v2-panel"
      aria-labelledby="evaluation-v2-title"
      data-evaluation-v2-status={presentationStatus}
    >
      <div className="section-heading section-heading--compact">
        <div>
          <p className="eyebrow">Primary current-evidence contract</p>
          <h2 id="evaluation-v2-title">Peer-review remediation v2 evidence</h2>
        </div>
        <span className={`grounding ${identityCurrent ? "grounding--grounded" : "grounding--partial"}`}>
          {identityCurrent ? "current · identity validated" : (freshness?.status ?? evidence?.status ?? "not run").replaceAll("_", " ")}
        </span>
      </div>

      {identityCurrent ? (
        <p className="notice notice--success" role="status">
          <strong>Identity-validated current AI-reviewed silver package.</strong>{" "}
          The frozen code, corpus, configuration, output, and release identities match. This remains technical-corpus AI-silver evidence, not human validation.
        </p>
      ) : completed ? (
        <p className="notice notice--warning" role="status">
          <strong>Completed v2 package is not current.</strong>{" "}
          {!boundaryValid
            ? "The declared AI-silver, non-human, non-entailment, technical-scope boundary is incomplete or inconsistent."
            : !topicSummaryValid
              ? "The topic summary does not declare the finalized positive-only label scope and unadjudicated-prediction boundary."
            : freshness?.status === "current" && (!identityChecksValid || !identityContractValid)
              ? "The required frozen identity checks or freshness contract are incomplete or mismatched."
              : `Identity freshness is ${freshness?.status ?? "unavailable"}; retained metrics must not be presented as current.`}
        </p>
      ) : (
        <p className="notice notice--warning" role="status">
          <strong>Current v2 evidence is not available.</strong>{" "}
          Run and validate the frozen remediation-v2 protocol before interpreting this panel as current evidence.
        </p>
      )}

      {evidence?.claim_boundary ? <p className="paper-card__status">{evidence.claim_boundary}</p> : null}
      <div className="paper-card__badges paper-card__badges--left" aria-label="v2 evidence boundaries">
        <span>{evidence?.evidence_tier === "ai_silver" ? "AI-reviewed silver" : "Evidence tier unavailable"}</span>
        <span>{evidence?.technical_scope_only === true ? "Technical corpus only" : "Scope boundary unavailable"}</span>
        <span>{evidence?.public_projection_exercised === true ? "Public projection exercised" : evidence?.public_projection_exercised === false ? "Public projection not exercised" : "Public-projection boundary unavailable"}</span>
        <span>{evidence?.human_validation === true ? "Human validation claimed" : evidence?.human_validation === false ? "No human validation" : "Human-validation boundary unavailable"}</span>
        <span>{evidence?.entailment_claimed === true ? "Entailment claimed" : evidence?.entailment_claimed === false ? "No entailment claim" : "Entailment boundary unavailable"}</span>
      </div>

      {completed ? (
        <div className="evaluation-grid evaluation-grid--v2">
          <V2MetricCard title="Selective Ask / QA (held out)" available={Boolean(evidence?.qa_test)}>
            <MetricRow label="Cases" value={evidence?.qa_test?.case_count ?? "not available"} />
            <MetricRow label="Answerability precision" value={formatOptionalMetric(qaMetrics?.answerability_precision)} />
            <MetricRow label="Answerability recall" value={formatOptionalMetric(qaMetrics?.answerability_recall)} />
            <MetricRow label="False-positive rate" value={formatOptionalMetric(qaMetrics?.false_positive_rate)} />
            <MetricRow label="Exact gold-locator citation precision" value={formatOptionalMetric(qaMetrics?.exact_gold_locator_citation_precision)} />
            <MetricRow label="Citation completeness" value={formatOptionalMetric(qaMetrics?.citation_completeness)} />
            <MetricRow label="Answer-point coverage" value={formatOptionalMetric(qaMetrics?.answer_point_coverage)} />
          </V2MetricCard>

          <V2MetricCard title="Thesis Extension Finder proxy (held out)" available={Boolean(evidence?.finder_test)}>
            <MetricRow label="Synthetic profiles" value={evidence?.finder_test?.profile_count ?? "not available"} />
            <MetricRow label="Evidence-only Hit@3" value={formatOptionalMetric(finderMetrics?.evidence_only_hit_at_3)} />
            <MetricRow label="Full Finder Hit@3" value={formatOptionalMetric(finderMetrics?.full_finder_hit_at_3)} />
            <MetricRow label="Paired Hit@3 delta" value={formatSignedMetric(finderMetrics?.paired_hit_at_3_delta)} />
            <MetricRow label="Evidence-only MRR" value={formatOptionalMetric(finderMetrics?.evidence_only_mrr)} />
            <MetricRow label="Full Finder MRR" value={formatOptionalMetric(finderMetrics?.full_finder_mrr)} />
            <MetricRow label="Fact/suggestion separation" value={formatOptionalMetric(finderMetrics?.source_fact_suggestion_separation_rate)} />
            <MetricRow label="Profile-contract fidelity" value={formatOptionalMetric(finderMetrics?.full_profile_constraint_contract_fidelity_rate)} />
          </V2MetricCard>

          <V2MetricCard title="Topic assignment (held out)" available={Boolean(evidence?.topics_test)}>
            <MetricRow label="Cases" value={evidence?.topics_test?.case_count ?? "not available"} />
            <MetricRow label="Label scope" value={evidence?.topics_test?.label_scope === "positive_only_not_exhaustive_closed_world" ? "Positive-only; label set is not exhaustive" : "not available"} />
            <MetricRow label="Known-positive labels matched / missed" value={formatCountPair(topicKnownPositive?.matched, topicKnownPositive?.missed)} />
            <MetricRow label="Known-positive micro recall" value={formatOptionalMetric(topicKnownPositive?.recall)} />
            <MetricRow label="Known-positive case coverage" value={formatOptionalMetric(evidence?.topics_test?.known_positive_case_coverage_rate)} />
            <MetricRow label="Unadjudicated predictions" value={unadjudicatedTopics?.count ?? "not available"} />
            <MetricRow label="Unadjudicated prediction share" value={formatOptionalMetric(unadjudicatedTopics?.share)} />
            <MetricRow
              label="Interpretation boundary"
              value={unadjudicatedTopics?.false_positive_interpretation_permitted === false
                ? "Unlisted predictions are unadjudicated, not false positives."
                : "not available"}
            />
          </V2MetricCard>

          <V2MetricCard title="Synthetic scanned-PDF OCR fixture" available={Boolean(evidence?.ocr)}>
            <MetricRow label="Run status" value={evidence?.ocr?.status?.replaceAll("_", " ") ?? "not available"} />
            <MetricRow label="OCR status" value={ocrMetrics?.ocr_status?.replaceAll("_", " ") ?? "not available"} />
            <MetricRow label="Character error rate" value={formatOptionalMetric(ocrMetrics?.character_error_rate)} />
            <MetricRow label="Word error rate" value={formatOptionalMetric(ocrMetrics?.word_error_rate)} />
            <MetricRow label="Normalized exact match" value={formatBoolean(ocrMetrics?.normalized_exact_match)} />
            <MetricRow label="Repeat-run text identical" value={formatBoolean(ocrMetrics?.repeat_run_text_identical)} />
            {evidence?.ocr?.claim_boundary ? <MetricRow label="Boundary" value={evidence.ocr.claim_boundary} /> : null}
          </V2MetricCard>
        </div>
      ) : null}
    </section>
  );
}

function V2MetricCard({
  title,
  available,
  children,
}: {
  title: string;
  available: boolean;
  children: ReactNode;
}) {
  return (
    <article className="admin-card">
      <div className="paper-card__meta"><span>{available ? "v2 held-out summary" : "summary unavailable"}</span></div>
      <h3>{title}</h3>
      {available ? <div className="status-table">{children}</div> : <EmptyState title="Metric summary unavailable" body="The v2 package exists, but this result summary is missing or invalid." />}
    </article>
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
  const metricsAvailable = section.status === "available" || section.status === "historical";
  return (
    <article className="admin-card">
      <div className="paper-card__meta">
        <span className={`grounding ${section.status === "available" ? "grounding--grounded" : "grounding--partial"}`}>
          {section.status.replaceAll("_", " ")}
        </span>
        <span>{section.last_run_timestamp ? `Last run ${new Date(section.last_run_timestamp).toLocaleString()}` : "No run timestamp"}</span>
      </div>
      <h2>{title}</h2>
      {metricsAvailable ? (
        <>
          {section.status === "historical" ? (
            <p className="notice notice--warning">Retained evidence only: the recorded provenance does not match the current runtime identity.</p>
          ) : null}
          <div className="status-table">{children}</div>
        </>
      ) : section.status === "invalid" ? (
        <EmptyState
          title="Evaluation result is invalid"
          body={typeof section.error === "string" ? section.error : "The result file exists but failed schema or parse validation. Re-run and validate it before interpreting any metric."}
        />
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

function formatOptionalMetric(value: number | null | undefined): string {
  return value === null || value === undefined ? "not available" : value.toFixed(3);
}

function formatSignedMetric(value: number | null | undefined): string {
  if (value === null || value === undefined) return "not available";
  return `${value >= 0 ? "+" : ""}${value.toFixed(3)}`;
}

function formatBoolean(value: boolean | undefined): string {
  return value === undefined ? "not available" : value ? "yes" : "no";
}

function formatCountPair(matched: number | undefined, missed: number | undefined): string {
  return matched === undefined || missed === undefined ? "not available" : `${matched} / ${missed}`;
}

function formatInterval(value: [number, number] | undefined): string {
  return value ? `[${value[0].toFixed(3)}, ${value[1].toFixed(3)}]` : "not run";
}
