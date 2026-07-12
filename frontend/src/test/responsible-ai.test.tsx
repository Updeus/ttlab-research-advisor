import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { AskPage } from "../pages/AskPage";
import { SearchPage } from "../pages/SearchPage";
import { ThesisExtensionFinder } from "../pages/ThesisExtensionFinder";
import { json, paper } from "./fixtures";

const sourceResult = {
  rank: 1,
  paper_id: paper.paper_id,
  paper_title: paper.title,
  authors: paper.authors,
  year: paper.year,
  chunk_id: "paper-1-0001",
  section: "Methodology",
  page_start: 2,
  page_end: 2,
  snippet: "A source-grounded passage about retrieval.",
  scores: { keyword: 0.8, semantic: 0.4, combined: 0.8 },
  source: { pdf_url: paper.pdf_url, post_url: paper.post_url, local_pdf_path: null },
};

const indexDiagnostics = {
  searchable_chunks: 1,
  searchable_papers: 1,
  chunks_indexed_for_keyword_search: 1,
  chunks_indexed_for_feature_hashing: 1,
  chunks_indexed_for_dense_search: 0,
  chunks_indexed_for_semantic_search: 1,
  embedding_provider: "feature_hashing",
  embedding_dimensions: 384,
  index_path: "redacted",
  index_status: "ready",
  last_indexed_timestamp: "2026-01-01T00:00:00Z",
  keyword: { status: "ready", keyword_indexed_chunks: 1 },
  feature_hashing: { embedding_provider: "feature_hashing", embedding_dimensions: 384, indexed_chunks: 1, index_path: "redacted", status: "ready", index_status: "ready", last_indexed_at: "2026-01-01T00:00:00Z" },
  dense: { embedding_provider: "dense", embedding_dimensions: 384, indexed_chunks: 0, index_path: "redacted", status: "missing", index_status: "missing", last_indexed_at: null },
};

describe("evidence and responsible-AI interfaces", () => {
  it("shows distinct index modes, freshness, source passage IDs, and retryable search evidence", async () => {
    const user = userEvent.setup();
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = new URL(String(input));
      if (url.pathname === "/api/search/diagnostics") return json(indexDiagnostics);
      if (url.pathname === "/api/search") return json({ query: "RAG", mode: "keyword", result_count: 1, results: [sourceResult], warnings: [] });
      return json({}, { status: 404 });
    });
    render(<SearchPage papers={[paper as never]} onSelectPaper={() => undefined} />);
    expect(await screen.findByText(/Dense semantic: 0 · missing/)).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Feature-hashing baseline" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Search" }));
    expect(await screen.findByText("Chunk paper-1-0001")).toBeInTheDocument();
    expect(screen.getAllByText("A source-grounded passage about retrieval.").length).toBeGreaterThan(0);
  });

  it("echoes a transient profile and exposes the evidence-only finder baseline", async () => {
    const user = userEvent.setup();
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = new URL(String(input));
      if (url.pathname.endsWith("/extensions/diagnostics")) return json({ searchable_chunks: 1, searchable_papers: 1, total_recommendation_runs: 0, total_recommendations_generated: 0, grounded_runs: 0, partial_runs: 0, unsupported_runs: 0, default_provider: "offline_deterministic", last_recommendation_timestamp: null });
      if (url.pathname === "/api/search") return json({ query: "profile", mode: "hybrid", result_count: 1, results: [sourceResult], warnings: [] });
      return json({}, { status: 404 });
    });
    render(<ThesisExtensionFinder papers={[paper as never]} onSelectPaper={() => undefined} />);
    await user.click(screen.getByRole("radio", { name: "Evidence-only ranked papers/passages" }));
    await user.click(screen.getByRole("button", { name: "Retrieve Evidence Only" }));
    expect(await screen.findByRole("heading", { name: "Submitted profile (transient)" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Evidence-only ranked papers and passages" })).toBeInTheDocument();
    expect(screen.getByText("Chunk paper-1-0001")).toBeInTheDocument();
    expect(screen.getByText(/not a saved account or student record/)).toBeInTheDocument();
    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
  });

  it("marks a public Ask answer transient and renders citation provenance", async () => {
    const user = userEvent.setup();
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = new URL(String(input));
      if (url.pathname === "/api/ask/diagnostics") return json({ total_stored_answers: 0, grounded_answers: 0, partial_answers: 0, unsupported_answers: 0, default_provider: "offline_extractive", external_provider_available: false, searchable_chunks: 1, semantic_indexed_chunks: 1, last_answer_timestamp: null });
      if (url.pathname === "/api/llms/local") return json({ available: false, base_url: "http://localhost:11434", default_model: "none", model_count: 0, models: [], recommended_pulls: [], benchmark: null, warnings: ["Ollama unavailable"] });
      if (url.pathname === "/api/ask" && init?.method === "POST") return json({
        answer_id: "answer-1",
        question: "Which paper?",
        answer: "The cited paper discusses retrieval.",
        grounding_status: "grounded",
        provider: "offline_extractive",
        model: "sentence-overlap-v1",
        retrieval_mode: "hybrid",
        top_k: 5,
        paper_id: null,
        citations: [{ ...sourceResult, title: sourceResult.paper_title, score: 0.8, source_url: paper.post_url, pdf_url: paper.pdf_url }],
        retrieved_chunks: [{ chunk_id: sourceResult.chunk_id, paper_id: paper.paper_id, title: paper.title, authors: paper.authors, year: paper.year, page_start: 2, page_end: 2, section: "Methodology", snippet: sourceResult.snippet, scores: sourceResult.scores }],
        retrieval_metadata: {},
        generation_metadata: {},
        warnings: [],
        unsupported_claims: [],
        created_at: "2026-01-01T00:00:00Z",
      });
      return json({}, { status: 404 });
    });
    render(<AskPage papers={[paper as never]} onSelectPaper={() => undefined} />);
    expect((await screen.findAllByText("Ollama unavailable")).length).toBeGreaterThan(0);
    await user.click(screen.getByRole("button", { name: "Ask" }));
    expect(await screen.findByText(/transient answer/)).toBeInTheDocument();
    expect(screen.getAllByText("Chunk paper-1-0001").length).toBeGreaterThan(0);
    expect(screen.getAllByText("A source-grounded passage about retrieval.").length).toBeGreaterThan(0);
  });
});
