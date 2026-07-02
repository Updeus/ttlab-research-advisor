import type { Paper, Stats } from "../types/paper";
import { StatusBadge } from "../components/StatusBadge";

type DashboardProps = {
  stats: Stats | null;
  papers: Paper[];
};

export function Dashboard({ stats, papers }: DashboardProps) {
  const withPdf = stats?.with_pdf_url ?? papers.filter((paper) => paper.pdf_url).length;
  const missingPdf = stats?.missing_pdf ?? papers.filter((paper) => paper.pdf_text_status === "missing_pdf").length;

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
          <span className="metric__label">Missing PDFs</span>
          <strong>{missingPdf}</strong>
        </article>
        <article className="metric">
          <span className="metric__label">Evaluation</span>
          <strong>{stats?.evaluation_status?.replaceAll("_", " ") ?? "not started"}</strong>
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
