import { useEffect, useState } from "react";

import { fetchSearchDiagnostics, searchChunks } from "../api/client";
import type { Paper, SearchDiagnostics, SearchMode, SearchResponse } from "../types/paper";

type SearchPageProps = {
  papers: Paper[];
  onSelectPaper: (paperId: string) => void;
};

export function SearchPage({ papers, onSelectPaper }: SearchPageProps) {
  const [query, setQuery] = useState("RAG academic research");
  const [mode, setMode] = useState<SearchMode>("hybrid");
  const [limit, setLimit] = useState(10);
  const [response, setResponse] = useState<SearchResponse | null>(null);
  const [diagnostics, setDiagnostics] = useState<SearchDiagnostics | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    fetchSearchDiagnostics()
      .then(setDiagnostics)
      .catch(() => setDiagnostics(null));
  }, []);

  function runSearch() {
    const trimmed = query.trim();
    if (!trimmed) {
      return;
    }
    setLoading(true);
    setError(null);
    searchChunks(trimmed, mode, limit)
      .then(setResponse)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Search failed."))
      .finally(() => setLoading(false));
  }

  return (
    <section className="page-section">
      <div className="section-heading">
        <h2>Search Source Chunks</h2>
      </div>

      <div className="search-toolbar">
        <input
          aria-label="Search source chunks"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              runSearch();
            }
          }}
        />
        <select aria-label="Search mode" value={mode} onChange={(event) => setMode(event.target.value as SearchMode)}>
          <option value="keyword">Keyword</option>
          <option value="semantic">Semantic</option>
          <option value="hybrid">Hybrid</option>
        </select>
        <select aria-label="Result limit" value={limit} onChange={(event) => setLimit(Number(event.target.value))}>
          <option value={5}>5</option>
          <option value={10}>10</option>
          <option value={20}>20</option>
        </select>
        <button onClick={runSearch}>Search</button>
      </div>

      {diagnostics ? (
        <div className="search-diagnostics">
          <span>{diagnostics.searchable_chunks} searchable chunks</span>
          <span>{diagnostics.chunks_indexed_for_keyword_search} keyword indexed</span>
          <span>{diagnostics.chunks_indexed_for_semantic_search} semantic indexed</span>
          <span>{diagnostics.embedding_provider} · {diagnostics.index_status}</span>
        </div>
      ) : null}

      {loading ? <p className="notice">Searching chunks...</p> : null}
      {error ? <p className="notice notice--error">{error}</p> : null}
      {response?.warnings.length ? (
        <p className="notice notice--warning">{response.warnings.join(" ")}</p>
      ) : null}

      <div className="paper-list">
        {response?.results.map((result) => {
          const paper = papers.find((item) => item.paper_id === result.paper_id);
          return (
            <article className="search-result" key={result.chunk_id}>
              <div className="paper-card__meta">
                <span>Rank {result.rank}</span>
                <span>{result.section ?? "Unknown"}</span>
                <span>Pages {result.page_start ?? "?"}-{result.page_end ?? "?"}</span>
                <span>Score {result.scores.combined.toFixed(3)}</span>
              </div>
              <h3>{result.paper_title}</h3>
              <p className="paper-card__status">{result.authors.join(", ") || "Authors need review"} {result.year ? `· ${result.year}` : ""}</p>
              <p>{result.snippet}</p>
              <div className="paper-card__links">
                {result.source.pdf_url ? (
                  <a href={result.source.pdf_url} target="_blank" rel="noreferrer">
                    PDF
                  </a>
                ) : null}
                {result.source.post_url ? (
                  <a href={result.source.post_url} target="_blank" rel="noreferrer">
                    TTLAB post
                  </a>
                ) : null}
                {paper ? (
                  <button className="link-button" onClick={() => onSelectPaper(result.paper_id)}>
                    Paper detail
                  </button>
                ) : null}
              </div>
            </article>
          );
        })}
        {response && response.results.length === 0 ? <p className="empty-state">No source chunks matched this search.</p> : null}
      </div>
    </section>
  );
}
