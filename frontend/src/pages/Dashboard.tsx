import type { Paper, Stats } from "../types/paper";
import { StatusBadge } from "../components/StatusBadge";

type DashboardProps = {
  stats: Stats | null;
  papers: Paper[];
};

export function Dashboard({ stats, papers }: DashboardProps) {
  const withPdf = stats?.with_pdf_url ?? papers.filter((paper) => paper.pdf_url).length;

  return (
    <section className="page-section">
      <div className="metrics-grid">
        <article className="metric">
          <span className="metric__label">Papers imported</span>
          <strong>{stats?.papers ?? papers.length}</strong>
        </article>
        <article className="metric">
          <span className="metric__label">Direct PDFs found</span>
          <strong>{withPdf}</strong>
        </article>
        <article className="metric">
          <span className="metric__label">Downloaded PDFs</span>
          <strong>{stats?.downloaded_pdfs ?? papers.filter((paper) => paper.local_pdf_path).length}</strong>
        </article>
        <article className="metric">
          <span className="metric__label">Extracted PDFs</span>
          <strong>{stats?.extracted_pdfs ?? papers.filter((paper) => paper.pdf_text_status === "extracted").length}</strong>
        </article>
        <article className="metric">
          <span className="metric__label">Failed or no text</span>
          <strong>{(stats?.extraction_failed ?? 0) + (stats?.no_text_pdfs ?? 0)}</strong>
        </article>
        <article className="metric">
          <span className="metric__label">Chunks</span>
          <strong>{stats?.total_chunks ?? papers.reduce((total, paper) => total + paper.chunk_count, 0)}</strong>
        </article>
        <article className="metric">
          <span className="metric__label">Topics</span>
          <strong>{stats?.topic_count ?? 0}</strong>
        </article>
        <article className="metric">
          <span className="metric__label">Authors</span>
          <strong>{stats?.author_count ?? 0}</strong>
        </article>
        <article className="metric">
          <span className="metric__label">Papers with topics</span>
          <strong>{stats?.papers_with_topics ?? 0}</strong>
        </article>
        <article className="metric">
          <span className="metric__label">Keyword indexed</span>
          <strong>{stats?.keyword_indexed_chunks ?? 0}</strong>
        </article>
        <article className="metric">
          <span className="metric__label">Semantic indexed</span>
          <strong>{stats?.semantic_indexed_chunks ?? 0}</strong>
        </article>
        <article className="metric">
          <span className="metric__label">Ask answers</span>
          <strong>{stats?.total_ask_answers ?? 0}</strong>
        </article>
        <article className="metric">
          <span className="metric__label">Ask provider</span>
          <strong className="metric__small">{stats?.default_ask_provider?.replaceAll("_", " ") ?? "offline"}</strong>
        </article>
        <article className="metric">
          <span className="metric__label">Extension runs</span>
          <strong>{stats?.total_extension_recommendation_runs ?? 0}</strong>
        </article>
        <article className="metric">
          <span className="metric__label">Extension ideas</span>
          <strong>{stats?.total_extension_ideas ?? 0}</strong>
        </article>
        <article className="metric">
          <span className="metric__label">Papers with artifacts</span>
          <strong>{stats?.papers_with_artifacts ?? 0}</strong>
        </article>
        <article className="metric">
          <span className="metric__label">Paper artifacts</span>
          <strong>{stats?.total_paper_artifacts ?? 0}</strong>
        </article>
        <article className="metric">
          <span className="metric__label">Podcast scripts</span>
          <strong>{stats?.podcast_scripts_generated ?? 0}</strong>
        </article>
        <article className="metric">
          <span className="metric__label">Artifacts needing review</span>
          <strong>{stats?.artifacts_needing_review ?? 0}</strong>
        </article>
        <article className="metric">
          <span className="metric__label">Admin review queue</span>
          <strong>{stats?.admin_review_queue_count ?? 0}</strong>
        </article>
        <article className="metric">
          <span className="metric__label">Review events</span>
          <strong>{stats?.total_review_events ?? 0}</strong>
        </article>
        <article className="metric">
          <span className="metric__label">Evaluation files</span>
          <strong>{Object.values(stats?.evaluation_files_present ?? {}).filter(Boolean).length}</strong>
        </article>
      </div>

      <div className="section-heading">
        <h2>Recent Papers</h2>
      </div>
      <div className="paper-list paper-list--compact">
        {(stats?.recent_papers ?? papers.slice(0, 5)).map((paper) => (
          <article className="paper-row" key={paper.paper_id}>
            <div>
              <h3>{paper.title}</h3>
              <p>{paper.authors.join(", ") || "Authors need review"}</p>
            </div>
            <StatusBadge
              label={paper.pdf_text_status}
              tone={paper.pdf_text_status === "missing_pdf" ? "warn" : "good"}
            />
          </article>
        ))}
      </div>
    </section>
  );
}
