import { useEffect, useRef, useState } from "react";

import { fetchSearchDiagnostics, isAbortError, searchChunks } from "../api/client";
import { EmptyState, InlineProgress, ListSkeleton, SearchActionButton } from "../components/UiPrimitives";
import type { ToastTone } from "../components/UiPrimitives";
import type { Paper, SearchDiagnostics, SearchMode, SearchResponse } from "../types/paper";

type SearchPageProps = {
  papers: Paper[];
  onSelectPaper: (paperId: string) => void;
  onNotify?: (message: string, tone?: ToastTone) => void;
};

type SubmittedSearch = {
  query: string;
  mode: SearchMode;
  limit: number;
};

type SearchResult = {
  request: SubmittedSearch;
  response: SearchResponse;
};

export function SearchPage({ papers, onSelectPaper, onNotify }: SearchPageProps) {
  const [query, setQuery] = useState("RAG academic research");
  const [mode, setMode] = useState<SearchMode>("keyword");
  const [limit, setLimit] = useState(10);
  const [result, setResult] = useState<SearchResult | null>(null);
  const [failedRequest, setFailedRequest] = useState<SubmittedSearch | null>(null);
  const [diagnostics, setDiagnostics] = useState<SearchDiagnostics | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [diagnosticsError, setDiagnosticsError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const requestSequence = useRef(0);
  const requestController = useRef<AbortController | null>(null);

  function loadDiagnostics() {
    setDiagnosticsError(null);
    fetchSearchDiagnostics()
      .then(setDiagnostics)
      .catch((err: unknown) => {
        setDiagnostics(null);
        setDiagnosticsError(err instanceof Error ? err.message : "Index diagnostics are unavailable.");
      });
  }

  useEffect(() => {
    loadDiagnostics();
  }, []);

  useEffect(() => () => requestController.current?.abort(), []);

  function runSearch(requestOverride?: SubmittedSearch) {
    const submittedRequest: SubmittedSearch = requestOverride ?? {
      query: query.trim(),
      mode,
      limit,
    };
    if (!submittedRequest.query) {
      return;
    }

    requestController.current?.abort();
    const controller = new AbortController();
    requestController.current = controller;
    const sequence = ++requestSequence.current;
    setLoading(true);
    setError(null);
    setFailedRequest(null);
    searchChunks(submittedRequest.query, submittedRequest.mode, submittedRequest.limit, controller.signal)
      .then((response) => {
        if (sequence !== requestSequence.current) return;
        setResult({ request: submittedRequest, response });
        onNotify?.(`Search returned ${response.result_count} source chunks.`, "success");
      })
      .catch((err: unknown) => {
        if (sequence !== requestSequence.current || isAbortError(err)) return;
        const message = err instanceof Error ? err.message : "Search failed.";
        setError(message);
        setFailedRequest(submittedRequest);
        onNotify?.(message, "error");
      })
      .finally(() => {
        if (sequence === requestSequence.current) setLoading(false);
      });
  }

  const response = result?.response ?? null;

  return (
    <section className="page-section">
      <div className="section-heading">
        <h2>Search Source Chunks</h2>
      </div>
      <p className="notice">Search runs only across approved public papers with cleared rights, searchable access, and eligible extracted text. Metadata-only catalogue records are excluded.</p>

      <form className="search-toolbar" aria-busy={loading} onSubmit={(event) => { event.preventDefault(); runSearch(); }}>
        <input
          aria-label="Search source chunks"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        <select aria-label="Search mode" value={mode} onChange={(event) => setMode(event.target.value as SearchMode)}>
          <option value="keyword">Keyword</option>
          <option value="feature_hashing">Feature-hashing baseline</option>
          <option value="dense">Dense semantic (learned model)</option>
          <option value="hybrid">Hybrid (experimental; not validated as better)</option>
        </select>
        <select aria-label="Result limit" value={limit} onChange={(event) => setLimit(Number(event.target.value))}>
          <option value={5}>5</option>
          <option value={10}>10</option>
          <option value={20}>20</option>
        </select>
        <SearchActionButton type="submit" busy={loading} disabled={!query.trim()} />
      </form>

      {diagnostics ? (
        <section className="search-diagnostics" aria-label="Current index snapshot">
          <span>{diagnostics.searchable_chunks} eligible searchable chunks</span>
          <span>Keyword: {diagnostics.chunks_indexed_for_keyword_search} · {diagnostics.keyword?.status ?? "status unavailable"}</span>
          <span>Feature hashing: {diagnostics.chunks_indexed_for_feature_hashing} · {diagnostics.feature_hashing.status}</span>
          <span>Dense semantic: {diagnostics.chunks_indexed_for_dense_search} · {diagnostics.dense.status}</span>
          <span>Feature-hashing snapshot: {formatTimestamp(diagnostics.feature_hashing.last_indexed_at)}</span>
        </section>
      ) : null}
      {diagnostics && [diagnostics.keyword?.status, diagnostics.feature_hashing.status].some((status) => status && !isReadyIndexStatus(status)) ? (
        <p className="notice notice--warning" role="status">A required search index is not ready for the current eligible corpus. Results may fail until an administrator rebuilds it.</p>
      ) : null}
      {diagnostics && !isReadyIndexStatus(diagnostics.dense.status) ? (
        <p className="notice" role="status">Dense semantic search is unavailable for this snapshot. Keyword and feature-hashing modes remain distinct alternatives.</p>
      ) : null}
      {diagnosticsError ? (
        <div className="notice notice--warning" role="status">
          <p>Index freshness could not be verified: {diagnosticsError}</p>
          <button className="action-button" onClick={loadDiagnostics}>Retry diagnostics</button>
        </div>
      ) : null}

      {loading && response ? <InlineProgress label="Updating results from indexed chunks..." /> : null}
      {error ? (
        <div className="notice notice--error" role="alert">
          <p>{error}</p>
          <button className="action-button" onClick={() => runSearch(failedRequest ?? undefined)}>Retry search</button>
        </div>
      ) : null}
      {response?.warnings.length ? (
        <p className="notice notice--warning">{response.warnings.join(" ")}</p>
      ) : null}

      {loading && !response ? <ListSkeleton count={limit > 10 ? 5 : 3} lines={3} /> : null}
      {result ? (
        <p className="paper-card__status" aria-live="polite">
          Results for “{result.request.query}” · {result.request.mode.replaceAll("_", " ")} · up to {result.request.limit}
        </p>
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
                <span>Chunk {result.chunk_id}</span>
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
        {response && response.results.length === 0 ? (
          <EmptyState
            title="No approved public source chunks matched this search"
            body="Try a broader phrase or another retrieval mode. Search includes only papers whose publication, rights, and searchable-access reviews have passed."
          />
        ) : null}
      </div>
    </section>
  );
}

function isReadyIndexStatus(status: string | null | undefined): boolean {
  return status === "ready" || status === "public_projection_ready";
}

function formatTimestamp(value: string | null | undefined): string {
  return value ? new Date(value).toLocaleString() : "not built";
}
