import { useEffect, useState } from "react";
import { Send } from "lucide-react";

import { askTtlab, fetchAskDiagnostics, fetchLocalLlms } from "../api/client";
import { BusyButton, EmptyState, InlineProgress, ListSkeleton } from "../components/UiPrimitives";
import type { ToastTone } from "../components/UiPrimitives";
import type { AskDiagnostics, AskResponse, LocalLlmModel, LocalLlmStatus, Paper, SearchMode } from "../types/paper";

type AskPageProps = {
  papers: Paper[];
  onSelectPaper: (paperId: string) => void;
  onNotify?: (message: string, tone?: ToastTone) => void;
  initialPaperId?: string | null;
};

export function AskPage({ papers, onSelectPaper, onNotify, initialPaperId = null }: AskPageProps) {
  const [question, setQuestion] = useState("Which TTLAB papers discuss RAG?");
  const [audience, setAudience] = useState("general");
  const [mode, setMode] = useState<SearchMode>("hybrid");
  const [topK, setTopK] = useState(5);
  const [provider, setProvider] = useState("ollama");
  const [selectedModel, setSelectedModel] = useState("qwen3:4b-instruct-2507-q4_K_M");
  const [selectedPaperId, setSelectedPaperId] = useState(initialPaperId ?? "");
  const [response, setResponse] = useState<AskResponse | null>(null);
  const [diagnostics, setDiagnostics] = useState<AskDiagnostics | null>(null);
  const [llmStatus, setLlmStatus] = useState<LocalLlmStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);

  function loadStatus() {
    setStatusError(null);
    Promise.allSettled([fetchAskDiagnostics(), fetchLocalLlms()])
      .then(([askResult, llmResult]) => {
        if (askResult.status === "fulfilled") setDiagnostics(askResult.value);
        else setDiagnostics(null);
        if (llmResult.status === "fulfilled") {
          const llmRows = llmResult.value;
          setLlmStatus(llmRows);
        const preferred = llmRows.models.find((model) => model.installed && model.name === llmRows.default_model)
          ?? llmRows.models.find((model) => model.installed)
          ?? llmRows.models[0];
        if (preferred) {
          setSelectedModel(preferred.name);
        }
          if (!llmRows.available || !llmRows.models.some((model) => model.installed)) {
            setProvider("offline_extractive");
          }
        } else {
          setLlmStatus(null);
          setProvider("offline_extractive");
        }
        if (askResult.status === "rejected" || llmResult.status === "rejected") {
          setStatusError("Some Ask/provider diagnostics could not be loaded.");
        }
      });
  }

  useEffect(() => {
    loadStatus();
  }, []);

  useEffect(() => {
    if (initialPaperId) {
      setSelectedPaperId(initialPaperId);
      const paper = papers.find((item) => item.paper_id === initialPaperId);
      if (paper) {
        setQuestion(`What does "${paper.title}" say, and what are the strongest cited points?`);
      }
    }
  }, [initialPaperId, papers]);

  const installedModels = llmStatus?.models.filter((model) => model.installed) ?? [];
  const modelOptions = installedModels.length ? installedModels : (llmStatus?.models.length ? llmStatus.models : [fallbackModel(selectedModel)]);
  const selectedModelInfo = modelOptions.find((model) => model.name === selectedModel) ?? modelOptions[0];

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
        provider,
        model: provider === "ollama" ? selectedModel : null,
        paper_id: selectedPaperId || null,
      })
      .then((result) => {
        setResponse(result);
        onNotify?.(`Ask TTLAB answered with ${result.citations.length} citations.`, result.grounding_status === "unsupported" ? "warning" : "success");
      })
      .catch((err: unknown) => {
        const message = err instanceof Error ? err.message : "Ask TTLAB failed.";
        setError(message);
        onNotify?.(message, "error");
      })
      .finally(() => setLoading(false));
  }

  return (
    <section className="page-section">
      <div className="section-heading">
        <h2>Ask TTLAB</h2>
      </div>
      <p className="notice">
        Privacy: your question and paper scope are sent for this request only. The public endpoint does not save them to Ask history. Do not enter confidential or personal data.
      </p>

      <div className="ask-panel" aria-busy={loading}>
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
            <option value="feature_hashing">Feature-hashing baseline</option>
            <option value="dense">Dense semantic (learned model)</option>
            <option value="hybrid">Hybrid</option>
          </select>
          <select aria-label="Top K" value={topK} onChange={(event) => setTopK(Number(event.target.value))}>
            <option value={3}>Top 3</option>
            <option value={5}>Top 5</option>
            <option value={8}>Top 8</option>
          </select>
          <select aria-label="Paper scope" value={selectedPaperId} onChange={(event) => setSelectedPaperId(event.target.value)}>
            <option value="">All indexed papers</option>
            {papers.map((paper) => (
              <option key={paper.paper_id} value={paper.paper_id}>
                {paper.title}
              </option>
            ))}
          </select>
          <select aria-label="Answer provider" value={provider} onChange={(event) => setProvider(event.target.value)}>
            <option value="ollama" disabled={llmStatus !== null && !llmStatus.available}>Local Ollama{llmStatus !== null && !llmStatus.available ? " (unavailable)" : ""}</option>
            <option value="offline_extractive">Offline extractive</option>
            <option value="auto">Auto fallback</option>
          </select>
          <select
            aria-label="Local Ollama model"
            value={selectedModel}
            onChange={(event) => setSelectedModel(event.target.value)}
            disabled={provider !== "ollama"}
          >
            {modelOptions.map((model) => (
              <option key={model.name} value={model.name}>
                {modelLabel(model)}
              </option>
            ))}
          </select>
          <BusyButton busy={loading} busyLabel="Asking..." icon={<Send size={16} aria-hidden="true" />} onClick={submitQuestion} disabled={!question.trim()}>
            Ask
          </BusyButton>
        </div>
      </div>

      {diagnostics ? (
        <div className="search-diagnostics">
          <span>{diagnostics.searchable_chunks} searchable chunks</span>
          <span>{diagnostics.total_stored_answers} stored answers</span>
          <span>{diagnostics.default_provider.replaceAll("_", " ")}</span>
          {diagnostics.feature_hashing_index ? <span>Feature hashing: {diagnostics.feature_hashing_index.status} · {formatTimestamp(diagnostics.feature_hashing_index.last_indexed_at)}</span> : null}
          {diagnostics.dense_index ? <span>Dense semantic: {diagnostics.dense_index.status}</span> : null}
          {llmStatus ? <span>{llmStatus.available ? `${llmStatus.model_count} local Ollama models` : "Ollama unavailable"}</span> : null}
        </div>
      ) : null}

      {selectedModelInfo ? (
        <div className="llm-model-strip">
          <span className={`llm-signal llm-signal--${selectedModelInfo.color}`}>{selectedModelInfo.quality_tier.replaceAll("_", " ")}</span>
          <strong>{selectedModelInfo.name}</strong>
          <span>{selectedModelInfo.rationale}</span>
          {selectedModelInfo.benchmark ? (
            <span>
              Avg {selectedModelInfo.benchmark.average_total_seconds}s · {selectedModelInfo.benchmark.average_tokens_per_second} tok/s
            </span>
          ) : (
            <span>Benchmark not run yet</span>
          )}
        </div>
      ) : null}
      {llmStatus?.warnings.length ? <p className="notice notice--warning">{llmStatus.warnings.join(" ")}</p> : null}
      {statusError ? (
        <div className="notice notice--warning" role="status">
          <p>{statusError}</p>
          <button className="action-button" onClick={loadStatus}>Retry status checks</button>
        </div>
      ) : null}

      {loading && response ? <InlineProgress label="Refreshing answer against indexed TTLAB paper chunks..." /> : null}
      {error ? (
        <div className="notice notice--error" role="alert">
          <p>{error}</p>
          <button className="action-button" onClick={submitQuestion}>Retry question</button>
        </div>
      ) : null}
      {loading && !response ? <ListSkeleton count={3} lines={4} /> : null}

      {response ? (
        <div className="answer-layout">
          <article className="answer-card">
            <div className="paper-card__meta">
              <span className={`grounding grounding--${response.grounding_status}`}>{response.grounding_status}</span>
              <span>{response.provider.replaceAll("_", " ")}</span>
              <span>{response.model}</span>
              <span>{response.retrieval_mode}</span>
              <span>Generated {new Date(response.created_at).toLocaleString()}</span>
              {response.paper_id ? <span>Single paper scope</span> : null}
            </div>
            <p className="paper-card__status">
              Grounding status reports structural citations and weak lexical overlap; it does not establish entailment or factual correctness.
            </p>
            <p className="notice notice--warning">
              This transient answer was generated from indexed TTLAB paper chunks and was not saved or human-reviewed. Check every claim against the cited sources.
            </p>
            <h3>Answer</h3>
            <p>{response.answer}</p>
            {response.retrieval_metadata?.query_expansions?.length ? (
              <p className="paper-card__status">Query expansion: {response.retrieval_metadata.query_expansions.join(", ")}</p>
            ) : null}
            {response.unsupported_claims.length ? (
              <div className="notice notice--error" role="alert">
                <strong>Unsupported-claim warnings</strong>
                <ul>{response.unsupported_claims.map((claim) => <li key={claim}>{claim}</li>)}</ul>
              </div>
            ) : null}
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
                    <span>Chunk {citation.chunk_id}</span>
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
            {response.citations.length === 0 ? (
              <EmptyState
                title="No citations were available"
                body="This answer should be treated as unsupported until retrieval returns source chunks."
              />
            ) : null}
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
                    <span>Chunk {chunk.chunk_id}</span>
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

function modelLabel(model: LocalLlmModel) {
  const tier = model.quality_tier.replaceAll("_", " ");
  return `${model.name} · ${tier}`;
}

function fallbackModel(name: string): LocalLlmModel {
  return {
    name,
    installed: false,
    source: "configured_default",
    color: "red",
    quality_tier: "availability unverified",
    rationale: "This configured model has not been confirmed as installed. Use offline extractive mode until the provider status is ready.",
    benchmark: null,
    is_default: true,
  };
}

function formatTimestamp(value: string | null | undefined): string {
  return value ? new Date(value).toLocaleString() : "not built";
}
