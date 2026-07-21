import type { Paper, Stats } from "../types/paper";
import { StatusBadge } from "../components/StatusBadge";
import { EmptyState } from "../components/UiPrimitives";

type DashboardProps = {
  stats: Stats | null;
  papers: Paper[];
};

type MetricItem = {
  label: string;
  value: string | number;
  note?: string;
  tone?: "primary" | "neutral" | "warning";
};

export function Dashboard({ stats, papers }: DashboardProps) {
  const withPdf = stats?.with_pdf_url ?? papers.filter((paper) => paper.pdf_url).length;
  const primaryMetrics: MetricItem[] = [
    { label: "Published papers", value: stats?.papers ?? papers.length, note: "approved public catalogue", tone: "primary" },
    { label: "Extracted PDFs", value: stats?.extracted_pdfs ?? papers.filter((paper) => paper.pdf_text_status === "extracted").length, note: "full papers with text" },
    { label: "Searchable chunks", value: stats?.searchable_chunks ?? stats?.total_chunks ?? 0, note: "indexed source passages" },
    { label: "Topics", value: stats?.topic_count ?? 0, note: `${stats?.author_count ?? 0} authors indexed` },
  ];
  const ingestionMetrics: MetricItem[] = [
    { label: "Direct PDFs found", value: withPdf },
    { label: "Downloaded PDFs", value: stats?.downloaded_pdfs ?? "Unavailable" },
    { label: "Failed or no text", value: (stats?.extraction_failed ?? 0) + (stats?.no_text_pdfs ?? 0), tone: "warning" },
    { label: "Missing PDFs", value: stats?.missing_pdf ?? 0, tone: "warning" },
  ];
  const intelligenceMetrics: MetricItem[] = [
    { label: "Keyword indexed", value: stats?.keyword_indexed_chunks ?? 0 },
    { label: "Feature-hashing baseline", value: stats?.feature_hashing_indexed_chunks ?? stats?.semantic_indexed_chunks ?? 0, note: stats?.feature_hashing_index_status ?? "status unavailable" },
    { label: "Dense semantic", value: stats?.dense_indexed_chunks ?? 0, note: stats?.dense_index_status ?? "status unavailable" },
    { label: "Ask answers", value: stats?.total_ask_answers ?? "Not published" },
    { label: "Extension ideas", value: stats?.total_extension_ideas ?? "Not published" },
    { label: "Papers with artifacts", value: stats?.papers_with_artifacts ?? "Not published" },
    { label: "Podcast scripts", value: stats?.podcast_scripts_generated ?? "Not published" },
  ];
  const reviewMetrics: MetricItem[] = [
    { label: "Admin review queue", value: "Protected", note: "Open Admin Review with reviewer access" },
    { label: "Artifacts needing review", value: "Protected", note: "Not exposed by public statistics" },
    { label: "Review events", value: "Protected", note: "Append-only history is reviewer-only" },
    { label: "Evaluation state", value: stats?.evaluation_status === "available" ? `${Object.values(stats.evaluation_files_present).filter(Boolean).length} result files` : "Not run", note: stats?.evaluation_last_run_at ? `Last run ${new Date(stats.evaluation_last_run_at).toLocaleString()}` : "No evaluated timestamp" },
  ];

  return (
    <section className="page-section" aria-labelledby="dashboard-title">
      <h2 id="dashboard-title" className="sr-only">Research intelligence dashboard</h2>
      {stats && (!isReadyIndexStatus(stats.feature_hashing_index_status) || stats.keyword_indexed_chunks !== stats.searchable_chunks) ? (
        <p className="notice notice--warning" role="status">The search snapshot is incomplete or stale for the currently eligible corpus. Index counts below are diagnostics, not retrieval-quality measurements.</p>
      ) : null}
      <div className="dashboard-hero">
        {primaryMetrics.map((metric) => (
          <MetricCard key={metric.label} metric={metric} large />
        ))}
      </div>

      <div className="dashboard-groups">
        <MetricGroup title="Ingestion Readiness" metrics={ingestionMetrics} />
        <MetricGroup title="Research Intelligence" metrics={intelligenceMetrics} />
        <MetricGroup title="Review & Evaluation" metrics={reviewMetrics} />
      </div>

      <div className="dashboard-lower">
        <section>
          <div className="section-heading section-heading--compact">
            <h2>Recent Papers</h2>
          </div>
          <div className="paper-list paper-list--compact">
            {(stats?.recent_papers ?? papers.slice(0, 5)).map((paper) => (
              <article className="paper-row" key={paper.paper_id}>
                <div>
                  <h3>{paper.title}</h3>
                  <p>{paper.authors.join(", ") || "Authors need review"}</p>
                </div>
                <StatusBadge label={paper.pdf_text_status} />
              </article>
            ))}
            {!(stats?.recent_papers ?? papers.slice(0, 5)).length ? (
              <EmptyState title="No papers are approved for public display yet" body="Publication and rights review must pass before a record appears here." />
            ) : null}
          </div>
        </section>

        <section>
          <div className="section-heading section-heading--compact">
            <h2>Top Topics</h2>
          </div>
          <div className="admin-card">
            {stats?.top_topics?.length ? (
              <div className="status-table">
                {stats.top_topics.slice(0, 8).map(([topic, count]) => (
                  <p key={topic}>
                    <span>{topic}</span>
                    <strong>{count}</strong>
                  </p>
                ))}
              </div>
            ) : (
              <EmptyState title="No approved public topic summary yet" body="Topic counts remain empty until public paper records are approved and searchable." />
            )}
          </div>
        </section>
      </div>
    </section>
  );
}

function isReadyIndexStatus(status: string | null | undefined): boolean {
  return status === "ready" || status === "public_projection_ready";
}

function MetricGroup({ title, metrics }: { title: string; metrics: MetricItem[] }) {
  return (
    <section className="metric-group">
      <h2>{title}</h2>
      <div className="metric-group__grid">
        {metrics.map((metric) => (
          <MetricCard key={metric.label} metric={metric} />
        ))}
      </div>
    </section>
  );
}

function MetricCard({ metric, large = false }: { metric: MetricItem; large?: boolean }) {
  const compactValue = typeof metric.value === "string" && metric.value.length > 6;
  return (
    <article className={`metric ${large ? "metric--large" : "metric--compact"} ${metric.tone ? `metric--${metric.tone}` : ""}`}>
      <span className="metric__label">{metric.label}</span>
      <strong className={compactValue ? "metric__small" : undefined}>{metric.value}</strong>
      {metric.note ? <span className="metric__note">{metric.note}</span> : null}
    </article>
  );
}
