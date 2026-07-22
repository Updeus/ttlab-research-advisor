import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { StatusBadge } from "../components/StatusBadge";
import { EmptyState } from "../components/UiPrimitives";
import type { Paper } from "../types/paper";
import { isSearchablePublicPaper } from "../utils/publication";

type PaperBrowserProps = {
  papers: Paper[];
};

const PAGE_SIZE = 20;

export function PaperBrowser({ papers }: PaperBrowserProps) {
  const [searchParams, setSearchParams] = useSearchParams();
  const [page, setPage] = useState(1);
  const query = searchParams.get("q") ?? "";
  const year = searchParams.get("year") ?? "";
  const author = searchParams.get("author") ?? "";
  const topic = searchParams.get("topic") ?? "";
  const venue = searchParams.get("venue") ?? "";

  const facets = useMemo(() => ({
    years: uniqueSorted(papers.map((paper) => paper.year === null ? "" : String(paper.year)), (left, right) => Number(right) - Number(left)),
    authors: uniqueSorted(papers.flatMap((paper) => paper.authors)),
    topics: uniqueSorted(papers.flatMap((paper) => paper.topics)),
    venues: uniqueSorted(papers.map((paper) => paper.venue ?? "")),
  }), [papers]);

  const filtered = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return papers.filter((paper) => {
      if (year && String(paper.year ?? "") !== year) return false;
      if (author && !paper.authors.includes(author)) return false;
      if (topic && !paper.topics.includes(topic)) return false;
      if (venue && paper.venue !== venue) return false;
      if (!normalized) return true;
      const haystack = [paper.title, paper.venue, paper.publication_date_raw, paper.year, paper.authors.join(" "), paper.topics.join(" ")]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return haystack.includes(normalized);
    });
  }, [author, papers, query, topic, venue, year]);
  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const currentPage = Math.min(page, totalPages);
  const firstIndex = (currentPage - 1) * PAGE_SIZE;
  const visible = filtered.slice(firstIndex, firstIndex + PAGE_SIZE);

  useEffect(() => {
    setPage(1);
  }, [author, papers, query, topic, venue, year]);

  function updateFilter(name: "q" | "year" | "author" | "topic" | "venue", value: string, replace = false) {
    const next = new URLSearchParams(searchParams);
    if (value) next.set(name, value);
    else next.delete(name);
    setSearchParams(next, { replace });
  }

  const hasFilters = Boolean(query || year || author || topic || venue);
  const searchablePaperCount = papers.filter(isSearchablePublicPaper).length;

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
          placeholder="Search title, author, topic, venue"
          value={query}
          onChange={(event) => updateFilter("q", event.target.value, true)}
        />
      </div>
      <p className="notice">
        This is the approved public metadata catalogue. {searchablePaperCount} of {papers.length} papers are also in the searchable full-text corpus.
        Metadata-only papers remain discoverable here but are excluded from Search, Ask TTLAB, and the Thesis Extension Finder.
      </p>
      <fieldset className="finder-grid finder-grid--compact paper-filters">
        <legend className="sr-only">Paper filters</legend>
        <FacetSelect label="Year" value={year} options={facets.years} onChange={(value) => updateFilter("year", value)} />
        <FacetSelect label="Author" value={author} options={facets.authors} onChange={(value) => updateFilter("author", value)} />
        <FacetSelect label="Topic" value={topic} options={facets.topics} onChange={(value) => updateFilter("topic", value)} />
        <FacetSelect label="Venue" value={venue} options={facets.venues} onChange={(value) => updateFilter("venue", value)} />
      </fieldset>
      {hasFilters ? (
        <button className="action-button action-button--ghost" type="button" onClick={() => setSearchParams(new URLSearchParams())}>
          Clear paper filters
        </button>
      ) : null}
      <div className="paper-list">
        {!papers.length ? (
          <EmptyState
            title="No papers are approved for public display yet"
            body="The public catalogue stays empty until a reviewer approves the metadata and confirms publication and rights settings. Local review records remain available only in the protected Admin preview."
          />
        ) : null}
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
                Access: {paper.public_access_level?.replaceAll("_", " ") ?? "metadata only"} · Text status: {paper.pdf_text_status.replaceAll("_", " ")} · {paper.page_count ?? "unknown"} pages ·{" "}
                {isSearchablePublicPaper(paper) ? `${paper.chunk_count} searchable public chunks` : "not in the searchable corpus"}
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
              <StatusBadge label={paper.public_access_level ?? "metadata_only"} />
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

function FacetSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: string[];
  onChange: (value: string) => void;
}) {
  return (
    <label>
      <span>{label}</span>
      <select aria-label={`Filter by ${label.toLowerCase()}`} value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="">All {label.toLowerCase()}s</option>
        {options.map((option) => <option key={option} value={option}>{option}</option>)}
      </select>
    </label>
  );
}

function uniqueSorted(values: string[], compare: (left: string, right: string) => number = (left, right) => left.localeCompare(right)): string[] {
  return [...new Set(values.filter(Boolean))].sort(compare);
}
