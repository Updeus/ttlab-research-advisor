import { useEffect, useState } from "react";

import { askTtlab, fetchAskDiagnostics } from "../api/client";
import type { AskDiagnostics, AskResponse, Paper, SearchMode } from "../types/paper";

type AskPageProps = {
  papers: Paper[];
  onSelectPaper: (paperId: string) => void;
};

export function AskPage({ papers, onSelectPaper }: AskPageProps) {
  const [question, setQuestion] = useState("Which TTLAB papers discuss RAG?");
  const [audience, setAudience] = useState("general");
  const [mode, setMode] = useState<SearchMode>("hybrid");
  const [topK, setTopK] = useState(5);
  const [response, setResponse] = useState<AskResponse | null>(null);
  const [diagnostics, setDiagnostics] = useState<AskDiagnostics | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchAskDiagnostics()
      .then(setDiagnostics)
      .catch(() => setDiagnostics(null));
  }, []);

  function submitQuestion() {
    const trimmed = question.trim();
    if (!trimmed) {
      return;
    }
    setLoading(true);
    setError(null);
    askTtlab({
      question: trimmed,
      mode,
      top_k: topK,
      audience,
      max_words: 250,
      provider: "auto",
    })
      .then(setResponse)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Ask TTLAB failed."))
      .finally(() => setLoading(false));
  }

  return (
    <section className="page-section">
      <div className="section-heading">
        <h2>Ask TTLAB</h2>
      </div>

      <div className="ask-panel">
        <textarea
          aria-label="Question"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          rows={4}
        />
        <div className="ask-controls">
          <select aria-label="Audience" value={audience} onChange={(event) => setAudience(event.target.value)}>
            <option value="general">General/public</option>
            <option value="student">Student</option>
            <option value="researcher">Researcher</option>
            <option value="industry">Industry</option>
          </select>
          <select aria-label="Retrieval mode" value={mode} onChange={(event) => setMode(event.target.value as SearchMode)}>
            <option value="keyword">Keyword</option>
            <option value="semantic">Semantic</option>
            <option value="hybrid">Hybrid</option>
          </select>
          <select aria-label="Top K" value={topK} onChange={(event) => setTopK(Number(event.target.value))}>
            <option value={3}>Top 3</option>
            <option value={5}>Top 5</option>
            <option value={8}>Top 8</option>
          </select>
          <button onClick={submitQuestion}>Ask</button>
        </div>
      </div>

      {diagnostics ? (
        <div className="search-diagnostics">
          <span>{diagnostics.searchable_chunks} searchable chunks</span>
          <span>{diagnostics.total_stored_answers} stored answers</span>
          <span>{diagnostics.default_provider.replaceAll("_", " ")}</span>
        </div>
      ) : null}

      {loading ? <p className="notice">Asking indexed TTLAB paper chunks...</p> : null}
      {error ? <p className="notice notice--error">{error}</p> : null}

      {response ? (
        <div className="answer-layout">
          <article className="answer-card">
            <div className="paper-card__meta">
              <span className={`grounding grounding--${response.grounding_status}`}>{response.grounding_status}</span>
              <span>{response.provider.replaceAll("_", " ")}</span>
              <span>{response.retrieval_mode}</span>
            </div>
            <p className="notice notice--warning">
              This answer is generated from indexed TTLAB paper chunks and should be checked against the cited sources.
            </p>
            <h3>Answer</h3>
            <p>{response.answer}</p>
          </article>

          {response.warnings.length ? (
            <p className="notice notice--warning">{response.warnings.join(" ")}</p>
          ) : null}

          <div className="section-heading">
            <h2>Citations</h2>
          </div>
          <div className="paper-list">
            {response.citations.map((citation) => {
              const paper = papers.find((item) => item.paper_id === citation.paper_id);
              return (
                <article className="citation-card" key={citation.chunk_id}>
                  <div className="paper-card__meta">
                    <span>{citation.section ?? "Unknown"}</span>
                    <span>Pages {citation.page_start ?? "?"}-{citation.page_end ?? "?"}</span>
                    <span>Score {citation.score.toFixed(3)}</span>
                  </div>
                  <h3>{citation.title}</h3>
                  <p className="paper-card__status">
                    {citation.authors.join(", ") || "Authors need review"} {citation.year ? `· ${citation.year}` : ""}
                  </p>
                  <p>{citation.snippet}</p>
                  <div className="paper-card__links">
                    {citation.pdf_url ? <a href={citation.pdf_url} target="_blank" rel="noreferrer">PDF</a> : null}
                    {citation.source_url ? <a href={citation.source_url} target="_blank" rel="noreferrer">TTLAB post</a> : null}
                    {paper ? <button className="link-button" onClick={() => onSelectPaper(citation.paper_id)}>Paper detail</button> : null}
                  </div>
                </article>
              );
            })}
            {response.citations.length === 0 ? <p className="empty-state">No citations were available for this answer.</p> : null}
          </div>

          <details className="retrieved-details">
            <summary>Retrieved chunks ({response.retrieved_chunks.length})</summary>
            <div className="paper-list">
              {response.retrieved_chunks.map((chunk) => (
                <article className="chunk-preview" key={chunk.chunk_id}>
                  <div className="paper-card__meta">
                    <span>{chunk.section ?? "Unknown"}</span>
                    <span>Pages {chunk.page_start ?? "?"}-{chunk.page_end ?? "?"}</span>
                    <span>Score {(chunk.scores.combined ?? 0).toFixed(3)}</span>
                  </div>
                  <h3>{chunk.title}</h3>
                  <p>{chunk.snippet}</p>
                </article>
              ))}
            </div>
          </details>
        </div>
      ) : null}
    </section>
  );
}
