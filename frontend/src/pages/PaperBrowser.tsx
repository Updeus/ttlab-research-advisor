import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { StatusBadge } from "../components/StatusBadge";
import { EmptyState } from "../components/UiPrimitives";
import type { Paper } from "../types/paper";

type PaperBrowserProps = {
  papers: Paper[];
};

const PAGE_SIZE = 20;

export function PaperBrowser({ papers }: PaperBrowserProps) {
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const filtered = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) {
      return papers;
    }
    return papers.filter((paper) => {
      const haystack = [paper.title, paper.venue, paper.publication_date_raw, paper.year, paper.authors.join(" ")]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return haystack.includes(normalized);
    });
  }, [papers, query]);
  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const currentPage = Math.min(page, totalPages);
  const firstIndex = (currentPage - 1) * PAGE_SIZE;
  const visible = filtered.slice(firstIndex, firstIndex + PAGE_SIZE);

  useEffect(() => {
    setPage(1);
  }, [query, papers]);

  return (
    <section className="page-section">
      <div className="section-heading section-heading--with-search">
        <div>
          <h2>Paper Browser</h2>
          <p className="section-kicker">
            {filtered.length} of {papers.length} papers match
            {filtered.length ? ` · showing ${firstIndex + 1}-${Math.min(firstIndex + PAGE_SIZE, filtered.length)}` : ""}
          </p>
        </div>
        <input
          aria-label="Search papers"
          placeholder="Search title, author, venue"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      </div>
      <div className="paper-list">
        {!papers.length ? <EmptyState title="No publication records are available" body="Import or restore a public paper snapshot before browsing." /> : null}
        {visible.map((paper) => (
          <article className="paper-card" key={paper.paper_id}>
            <div className="paper-card__body">
              <div className="paper-card__meta">
                <span>{paper.year ?? paper.publication_date_raw ?? "Date needs review"}</span>
                {paper.venue ? <span>{paper.venue}</span> : <span>Venue needs review</span>}
              </div>
              <h3>{paper.title}</h3>
              <p>{paper.authors.join(", ") || "Authors need review"}</p>
              <p className="paper-card__status">
                Text status: {paper.pdf_text_status.replaceAll("_", " ")} · {paper.page_count ?? "unknown"} pages ·{" "}
                {paper.chunk_count} public chunks
              </p>
              <div className="paper-card__links">
                {paper.source_url ? (
                  <a href={paper.source_url} target="_blank" rel="noreferrer">
                    Source
                  </a>
                ) : null}
                {paper.pdf_url ? (
                  <a href={paper.pdf_url} target="_blank" rel="noreferrer">
                    PDF
                  </a>
                ) : null}
                {paper.post_url ? (
                  <a href={paper.post_url} target="_blank" rel="noreferrer">
                    TTLAB post
                  </a>
                ) : null}
                <Link className="link-button" to={`/papers/${encodeURIComponent(paper.paper_id)}`}>
                  Details
                </Link>
              </div>
            </div>
            <div className="paper-card__badges">
              <StatusBadge label={paper.pdf_text_status} />
              <StatusBadge label={paper.review_status} />
            </div>
          </article>
        ))}
        {filtered.length === 0 ? (
          <EmptyState
            title="No papers match this search"
            body="Search by title, author, venue, year, or a broader phrase from the publication metadata."
          />
        ) : null}
      </div>
      {totalPages > 1 ? (
        <nav className="pagination" aria-label="Paper browser pages">
          <button
            className="action-button action-button--ghost"
            type="button"
            disabled={currentPage === 1}
            onClick={() => setPage((value) => Math.max(1, value - 1))}
          >
            Previous page
          </button>
          <span aria-live="polite">Page {currentPage} of {totalPages}</span>
          <button
            className="action-button action-button--ghost"
            type="button"
            disabled={currentPage === totalPages}
            onClick={() => setPage((value) => Math.min(totalPages, value + 1))}
          >
            Next page
          </button>
        </nav>
      ) : null}
    </section>
  );
}
