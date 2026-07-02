import { useMemo, useState } from "react";

import { StatusBadge } from "../components/StatusBadge";
import type { Paper } from "../types/paper";

type PaperBrowserProps = {
  papers: Paper[];
  onSelectPaper: (paper: Paper) => void;
};

export function PaperBrowser({ papers, onSelectPaper }: PaperBrowserProps) {
  const [query, setQuery] = useState("");
  const filtered = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) {
      return papers;
    }
    return papers.filter((paper) => {
      const haystack = [paper.title, paper.venue, paper.publication_date_raw, paper.authors.join(" ")]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return haystack.includes(normalized);
    });
  }, [papers, query]);

  return (
    <section className="page-section">
      <div className="section-heading section-heading--with-search">
        <h2>Paper Browser</h2>
        <input
          aria-label="Search papers"
          placeholder="Search title, author, venue"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      </div>
      <div className="paper-list">
        {filtered.map((paper) => (
          <article className="paper-card" key={paper.paper_id}>
            <div className="paper-card__body">
              <div className="paper-card__meta">
                <span>{paper.year ?? paper.publication_date_raw ?? "Date needs review"}</span>
                {paper.venue ? <span>{paper.venue}</span> : <span>Venue needs review</span>}
              </div>
              <h3>{paper.title}</h3>
              <p>{paper.authors.join(", ") || "Authors need review"}</p>
              <p className="paper-card__status">
                {paper.local_pdf_path ? "Downloaded" : "Not downloaded"} · {paper.page_count ?? 0} pages ·{" "}
                {paper.chunk_count} chunks
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
                <button className="link-button" onClick={() => onSelectPaper(paper)}>
                  Details
                </button>
              </div>
            </div>
            <div className="paper-card__badges">
              <StatusBadge
                label={paper.pdf_text_status}
                tone={paper.pdf_text_status === "missing_pdf" ? "warn" : "good"}
              />
              <StatusBadge label={paper.review_status} tone="neutral" />
            </div>
          </article>
        ))}
        {filtered.length === 0 ? <p className="empty-state">No papers match this search.</p> : null}
      </div>
    </section>
  );
}
