import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { AskPage } from "../pages/AskPage";
import { Dashboard } from "../pages/Dashboard";
import { PaperDetail } from "../pages/PaperDetail";
import { SearchPage } from "../pages/SearchPage";
import { ThesisExtensionFinder } from "../pages/ThesisExtensionFinder";
import type { AskDiagnostics, AskResponse, ExtractionDiagnostics, RetrieverConfig, SearchDiagnostics, SearchMode, SearchResponse, SearchResult } from "../types/paper";
import { json, paper, stats } from "./fixtures";

const sourceResult = {
  rank: 1,
  paper_id: paper.paper_id,
  paper_title: paper.title,
  authors: paper.authors,
  year: paper.year,
  venue: paper.venue,
  topics: paper.topics,
  chunk_id: "paper-1-0001",
  chunk_index: 0,
  section: "Methodology",
  page_start: 2,
  page_end: 2,
  snippet: "A source-grounded passage about retrieval.",
  scores: {
    keyword: 0.8,
    vector: 0,
    vector_provider: null,
    metadata: 0,
    section_boost: 0,
    evidence_quality: 0,
    topical_alignment: 0,
    diversity_penalty: 0,
    combined: 0.8,
  },
  source: { pdf_url: paper.pdf_url, post_url: paper.post_url },
} satisfies SearchResult;

const hybridSourceResult = {
  ...sourceResult,
  scores: { ...sourceResult.scores, vector: 0.4, vector_provider: "feature_hashing" },
} satisfies SearchResult;

const retrieverConfig = {
  enable_query_expansion: true,
  enable_metadata_boost: true,
  enable_section_boost: true,
  enable_evidence_adjustment: true,
  enable_topic_adjustment: true,
  enable_diversity_penalty: true,
  keyword_weight: 0.42,
  vector_weight: 0.48,
  metadata_scale: 1,
  section_scale: 1,
  evidence_scale: 1,
  topic_scale: 1,
  diversity_scale: 1,
  candidate_multiplier: 3,
} satisfies RetrieverConfig;

function searchPayload(query: string, mode: SearchMode, results: SearchResult[] = [sourceResult]): SearchResponse {
  return {
    query,
    expanded_query: query,
    query_expansions: [],
    mode,
    result_count: results.length,
    results,
    warnings: [],
    vector_provider: mode === "keyword" ? null : "feature_hashing",
    retrieval_strategy: "explicit_config_v1",
    retriever_config: retrieverConfig,
    retrieval_scope: "public",
  };
}

const unknownDifficultyRecommendation = {
  rank: 1,
  paper_id: paper.paper_id,
  paper_title: paper.title,
  authors: paper.authors,
  year: paper.year,
  fit_score: 0.5,
  score_breakdown: {},
  paper_focus: "Source-backed retrieval work.",
  source_supported_facts: [],
  identified_gap: { text: "No explicit gap was found.", support_status: "not_found", source_chunk_ids: [] },
  extension_title: "Scope requires confirmation",
  extension_summary: "A system-suggested extension.",
  why_it_fits_student: "Proxy fit only.",
  mvp_scope: "Confirm scope before implementation.",
  stretch_goals: [],
  required_skills: [],
  skills_gap: [],
  data_required: "Unknown",
  data_availability: "unknown",
  evaluation_plan: "Define a source-backed protocol.",
  difficulty: "unknown",
  risk_level: "high",
  implementation_time: "unknown",
  related_papers: [],
  potential_researcher_fit: [],
  citations: [],
  warnings: ["Difficulty was not inferable from source evidence."],
};

const indexDiagnostics = {
  total_chunks: 1,
  raw_chunks: null,
  eligible_chunks: 1,
  searchable_chunks: 1,
  searchable_papers: 1,
  chunks_indexed_for_keyword_search: 1,
  chunks_indexed_for_feature_hashing: 1,
  chunks_indexed_for_dense_search: 0,
  chunks_indexed_for_semantic_search: null,
  semantic_search_deprecation: "Feature hashing is a lexical baseline; use feature_hashing explicitly.",
  embedding_provider: null,
  embedding_dimensions: null,
  index_status: "ready",
  last_indexed_timestamp: null,
  keyword: { status: "ready", projection_status: "public_projection_ready", indexed_chunks: 1, public_eligible_chunks: 1, underlying_index_status: "ready", underlying_representation_valid: true, underlying_error_count: 0, last_indexed_at: "2026-01-01T00:00:00Z" },
  feature_hashing: { status: "ready", projection_status: "public_projection_ready", indexed_chunks: 1, public_eligible_chunks: 1, underlying_index_status: "ready", underlying_representation_valid: true, underlying_error_count: 0, last_indexed_at: "2026-01-01T00:00:00Z", classification: "lexical_feature_hashing" },
  dense: { status: "missing", projection_status: "underlying_index_not_ready", indexed_chunks: 0, public_eligible_chunks: 1, underlying_index_status: "missing", underlying_representation_valid: false, underlying_error_count: 0, last_indexed_at: null },
} satisfies SearchDiagnostics;

const askDiagnostics = {
  total_stored_answers: null,
  grounded_answers: null,
  partial_answers: null,
  unsupported_answers: null,
  history_counts_visibility: "protected_reviewer_only",
  history_counts_observed: false,
  default_provider: "offline_extractive",
  allowed_providers: ["offline_extractive"],
  provider_matrix: { offline_extractive: { enabled: true, effective_model: "sentence-overlap-v1", identity_scope: "versioned_deterministic_algorithm" } },
  external_provider_available: false,
  external_provider_availability_scope: "configured_pinned_model_not_runtime_reachability",
  scope: "public",
  searchable_chunks: 1,
  raw_chunks: null,
  semantic_indexed_chunks: null,
  semantic_index_deprecation: "Feature hashing is lexical, not semantic.",
  last_answer_timestamp: null,
  keyword_index: indexDiagnostics.keyword,
  feature_hashing_index: indexDiagnostics.feature_hashing,
  dense_index: indexDiagnostics.dense,
} satisfies AskDiagnostics;

const extractionDiagnostics = {
  paper_id: paper.paper_id,
  pdf_url: paper.pdf_url,
  pdf_text_status: "extracted",
  pdf_unavailability_reason: null,
  page_count: 4,
  total_char_count: 800,
  total_word_count: 120,
  pages_with_text: 4,
  pages_without_text: 0,
  possible_scanned_pdf: false,
  extraction_content_type: "digital_text",
  ocr_status: "not_requested",
  ocr_provider: null,
  ocr_provider_version: null,
  ocr_pages_count: 0,
  ocr_review_required: false,
  pdf_title_match_status: "matched",
  pdf_title_match_score: 1,
  corpus_eligibility_status: "eligible",
  corpus_exclusion_reason: null,
  warnings: [],
  chunk_count: 1,
} satisfies ExtractionDiagnostics;

const localGenerationStatus = {
  runtime_profile: "local",
  provider: "ollama",
  display_name: "Local Ollama",
  configured: true,
  location: "local",
  model: "qwen3:4b-instruct-2507-q4_K_M",
  model_selection_enabled: true,
  external_processing: false,
  privacy_notice: "your question and paper scope are sent for this request only.",
};

describe("evidence and responsible-AI interfaces", () => {
  it("does not report dense search unavailable before diagnostics finish loading", () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() => new Promise<Response>(() => undefined));
    render(<SearchPage papers={[paper as never]} onSelectPaper={() => undefined} />);
    expect(screen.queryByText(/Dense semantic search is unavailable/)).not.toBeInTheDocument();
  });

  it("treats a healthy public index projection as ready on Search and Dashboard", async () => {
    const projected = {
      ...indexDiagnostics,
      keyword: { ...indexDiagnostics.keyword, projection_status: "public_projection_ready" },
      feature_hashing: { ...indexDiagnostics.feature_hashing, projection_status: "public_projection_ready", underlying_index_status: "ready" },
    };
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = new URL(String(input), window.location.origin);
      if (url.pathname === "/api/search/diagnostics") return json(projected);
      return json({}, { status: 404 });
    });
    render(<SearchPage papers={[paper as never]} onSelectPaper={() => undefined} />);
    await screen.findByText(/Feature hashing: 1 · public_projection_ready/);
    expect(screen.queryByText(/A required search index is not ready/)).not.toBeInTheDocument();

    render(<Dashboard stats={stats} papers={[paper]} />);
    expect(screen.queryByText(/search snapshot is incomplete or stale/)).not.toBeInTheDocument();
  });

  it("defaults to Local Ollama when a usable installed model is available", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = new URL(String(input), window.location.origin);
      if (url.pathname === "/api/ask/diagnostics") return json(askDiagnostics);
      if (url.pathname === "/api/llms/status") return json(localGenerationStatus);
      if (url.pathname === "/api/llms/local") return json({
        available: true, generation_available: true, default_model: "local:test",
        models: [{ name: "local:test", installed: true, usable: true, color: "yellow", quality_tier: "unvalidated", rationale: "Not evaluated" }],
        warnings: [],
      });
      return json({}, { status: 404 });
    });
    render(<AskPage papers={[paper as never]} onSelectPaper={() => undefined} />);
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Local Ollama model" })).toHaveValue("local:test"));
    expect(screen.getByRole("combobox", { name: "Answer provider" })).toHaveValue("ollama");
    expect(screen.getByRole("combobox", { name: "Local Ollama model" })).toBeEnabled();
  });

  it("keeps Ollama disabled without a digest-verified model and labels protected diagnostics", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = new URL(String(input), window.location.origin);
      if (url.pathname === "/api/ask/diagnostics") return json(askDiagnostics);
      if (url.pathname === "/api/llms/status") return json(localGenerationStatus);
      if (url.pathname === "/api/llms/local") return json({
        available: true,
        generation_available: false,
        base_url: "http://localhost:11434",
        default_model: "unpinned:latest",
        model_count: 1,
        models: [{ name: "unpinned:latest", installed: true, usable: false, digest_allowed: false, source: "ollama", color: "yellow", quality_tier: "unvalidated", rationale: "Digest is not approved", is_default: true }],
        candidate_pulls: [],
        recommended_pulls: [],
        benchmark: null,
        warnings: ["No digest-verified model"],
      });
      return json({}, { status: 404 });
    });
    render(<AskPage papers={[paper as never]} onSelectPaper={() => undefined} />);
    expect(await screen.findByText("Stored answer history protected")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Retrieval mode" })).toHaveValue("keyword");
    expect(screen.getByRole("option", { name: "Hybrid (experimental; not validated as better)" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Answer provider" })).toHaveValue("offline_extractive");
    expect(screen.getByRole("option", { name: "Local Ollama (no digest-verified model)" })).toBeDisabled();
  });

  it("labels protected Finder history instead of rendering null as a count", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = new URL(String(input), window.location.origin);
      if (url.pathname.endsWith("/extensions/diagnostics")) return json({ searchable_chunks: 1, searchable_papers: 1, total_recommendation_runs: null, total_recommendations_generated: null, grounded_runs: null, partial_runs: null, unsupported_runs: null, default_provider: "offline_deterministic", last_recommendation_timestamp: null });
      return json({}, { status: 404 });
    });
    render(<ThesisExtensionFinder papers={[paper as never]} onSelectPaper={() => undefined} />);
    expect(await screen.findByText("Stored recommendation history protected")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Retrieval mode" })).toHaveValue("keyword");
    expect(screen.getByRole("option", { name: "hybrid (experimental; not validated as better)" })).toBeInTheDocument();
  });

  it("fails closed without submitting when the public Finder projection is empty", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = new URL(String(input), window.location.origin);
      if (url.pathname.endsWith("/extensions/diagnostics")) return json({ searchable_chunks: 0, searchable_papers: 0, total_recommendation_runs: null, total_recommendations_generated: null, grounded_runs: null, partial_runs: null, unsupported_runs: null, default_provider: "offline_deterministic", last_recommendation_timestamp: null });
      return json({}, { status: 404 });
    });

    render(<ThesisExtensionFinder papers={[]} onSelectPaper={() => undefined} />);

    expect(await screen.findByText("No papers are approved for public Finder recommendations yet")).toBeInTheDocument();
    expect(screen.getByText(/Reviewer-only technical prototype evidence is not substituted/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Find Thesis Extensions" })).toBeDisabled();
    expect(fetchMock.mock.calls.filter(([input]) => new URL(String(input), window.location.origin).pathname === "/api/recommendations/extensions")).toHaveLength(0);
  });

  it("shows distinct index modes, freshness, source passage IDs, and retryable search evidence", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = new URL(String(input), window.location.origin);
      if (url.pathname === "/api/search/diagnostics") return json(indexDiagnostics);
      if (url.pathname === "/api/search") return json(searchPayload("RAG", "keyword"));
      return json({}, { status: 404 });
    });
    render(<SearchPage papers={[paper as never]} onSelectPaper={() => undefined} />);
    expect(await screen.findByText(/Dense semantic: 0 · underlying_index_not_ready/)).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Search mode" })).toHaveValue("keyword");
    expect(screen.getByRole("option", { name: "Hybrid (experimental; not validated as better)" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Feature-hashing baseline" })).toBeInTheDocument();
    const searchInput = screen.getByRole("textbox", { name: "Search source chunks" });
    await user.clear(searchInput);
    await user.type(searchInput, "precision retrieval{Enter}");
    expect(await screen.findByText("Chunk paper-1-0001")).toBeInTheDocument();
    expect(screen.getAllByText("A source-grounded passage about retrieval.").length).toBeGreaterThan(0);
    expect(fetchMock.mock.calls.filter(([input]) => new URL(String(input), window.location.origin).pathname === "/api/search")).toHaveLength(1);
    await user.clear(searchInput);
    await user.type(searchInput, "edited after submission");
    expect(screen.getByText(/Results for “precision retrieval”/)).toBeInTheDocument();
  });

  it("ignores an older Search response that completes after a newer request", async () => {
    const user = userEvent.setup();
    const pending: Array<(response: Response) => void> = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = new URL(String(input), window.location.origin);
      if (url.pathname === "/api/search/diagnostics") return json(indexDiagnostics);
      if (url.pathname === "/api/search") return new Promise<Response>((resolve) => pending.push(resolve));
      return json({}, { status: 404 });
    });
    render(<SearchPage papers={[paper as never]} onSelectPaper={() => undefined} />);
    const input = screen.getByRole("textbox", { name: "Search source chunks" });
    const form = input.closest("form");
    expect(form).not.toBeNull();

    await user.clear(input);
    await user.type(input, "older query");
    fireEvent.submit(form!);
    await waitFor(() => expect(pending).toHaveLength(1));

    await user.clear(input);
    await user.type(input, "newer query");
    fireEvent.submit(form!);
    await waitFor(() => expect(pending).toHaveLength(2));

    await act(async () => pending[1](await json(searchPayload("newer query", "hybrid", [{ ...hybridSourceResult, snippet: "Newer result" }]))));
    expect(await screen.findByText("Newer result")).toBeInTheDocument();
    await act(async () => pending[0](await json(searchPayload("older query", "hybrid", [{ ...hybridSourceResult, snippet: "Older result" }]))));
    expect(screen.getByText(/Results for “newer query”/)).toBeInTheDocument();
    expect(screen.queryByText("Older result")).not.toBeInTheDocument();
  });

  it("echoes a transient profile and exposes the evidence-only finder baseline", async () => {
    const user = userEvent.setup();
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = new URL(String(input), window.location.origin);
      if (url.pathname.endsWith("/extensions/diagnostics")) return json({ searchable_chunks: 1, searchable_papers: 1, total_recommendation_runs: 0, total_recommendations_generated: 0, grounded_runs: 0, partial_runs: 0, unsupported_runs: 0, default_provider: "offline_deterministic", last_recommendation_timestamp: null });
      if (url.pathname === "/api/search") return json(searchPayload("profile", "hybrid", [hybridSourceResult]));
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
      const url = new URL(String(input), window.location.origin);
      if (url.pathname === "/api/ask/diagnostics") return json(askDiagnostics);
      if (url.pathname === "/api/llms/status") return json(localGenerationStatus);
      if (url.pathname === "/api/llms/local") return json({ available: false, base_url: "http://localhost:11434", default_model: "none", model_count: 0, models: [], recommended_pulls: [], benchmark: null, warnings: ["Ollama unavailable"] });
      if (url.pathname === "/api/ask" && init?.method === "POST") return json({
        answer_id: "answer-1",
        question: "Which paper?",
        answer: "**Main finding:** The cited paper discusses retrieval [S3].",
        grounding_status: "partial",
        support_status: "support_unverified",
        provider: "offline_extractive",
        model: "sentence-overlap-v1",
        retrieval_mode: "hybrid",
        top_k: 5,
        paper_id: null,
        citations: [{
          paper_id: paper.paper_id,
          title: paper.title,
          authors: paper.authors,
          year: paper.year,
          chunk_id: hybridSourceResult.chunk_id,
          section: "Methodology",
          page_start: 2,
          page_end: 2,
          snippet: hybridSourceResult.snippet,
          score: 0.8,
          source_url: paper.post_url,
          pdf_url: paper.pdf_url,
        }],
        retrieved_chunks: [
          { chunk_id: "other-0001", paper_id: "other-1", title: "Unrelated source one", authors: [], year: 2024, page_start: 1, page_end: 1, section: "Introduction", snippet: "Unrelated evidence one.", scores: hybridSourceResult.scores, source: { pdf_url: null, post_url: null } },
          { chunk_id: "other-0002", paper_id: "other-2", title: "Unrelated source two", authors: [], year: 2024, page_start: 1, page_end: 1, section: "Introduction", snippet: "Unrelated evidence two.", scores: hybridSourceResult.scores, source: { pdf_url: null, post_url: null } },
          { chunk_id: hybridSourceResult.chunk_id, paper_id: paper.paper_id, title: paper.title, authors: paper.authors, year: paper.year, page_start: 2, page_end: 2, section: "Methodology", snippet: hybridSourceResult.snippet, scores: hybridSourceResult.scores, source: hybridSourceResult.source },
        ],
        retrieval_metadata: { expanded_query: "Which paper?", query_expansions: [], retrieval_strategy: "explicit_config_v1", retrieval_scope: "public" },
        generation_metadata: {},
        answerability: { answerable: true, reason: "source_term_coverage", query_terms: ["retrieval"], matched_query_terms: ["retrieval"], max_query_coverage: 1, minimum_query_coverage: 0.34, relevant_chunk_ids: [hybridSourceResult.chunk_id], warnings: [] },
        claim_support: [],
        runtime_provenance: { schema_version: 1 },
        source_text_delivery: "bounded_snippets_only",
        warnings: [],
        unsupported_claims: [],
        created_at: "2026-01-01T00:00:00Z",
      } satisfies AskResponse);
      return json({}, { status: 404 });
    });
    render(<AskPage papers={[paper as never]} onSelectPaper={() => undefined} />);
    expect((await screen.findAllByText("Ollama unavailable")).length).toBeGreaterThan(0);
    const questionInput = screen.getByRole("textbox", { name: "Question" });
    await user.clear(questionInput);
    await user.type(questionInput, "What evidence supports retrieval?");
    await user.click(screen.getByRole("button", { name: "Ask" }));
    expect(await screen.findByText(/transient answer/)).toBeInTheDocument();
    expect(screen.getByText(/does not establish entailment or factual correctness/i)).toBeInTheDocument();
    expect(screen.getByText("Main finding:").tagName).toBe("STRONG");
    const inlineCitation = screen.getByRole("link", { name: `Source: ${paper.title}, Methodology, p. 2` });
    expect(inlineCitation).toHaveTextContent(`[${paper.title}, p. 2]`);
    expect(inlineCitation).toHaveAttribute("href", "#ask-source-paper-1-0001");
    expect(document.querySelector("#ask-source-paper-1-0001")).toBeInTheDocument();
    expect(screen.queryByText(/\[S3\]/)).not.toBeInTheDocument();
    expect(screen.getAllByText("A source-grounded passage about retrieval.").length).toBeGreaterThan(0);
    await user.clear(questionInput);
    await user.type(questionInput, "A different draft question");
    expect(screen.getByText(/Answer to “What evidence supports retrieval\?”/)).toBeInTheDocument();
  });

  it("disables learned dense retrieval while its local model warms up", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = new URL(String(input), window.location.origin);
      if (url.pathname === "/api/ask/diagnostics") return json({
        ...askDiagnostics,
        dense_provider: { state: "warming", started_at: "2026-01-01T00:00:00Z", ready_at: null, elapsed_seconds: null },
      });
      if (url.pathname === "/api/llms/status") return json(localGenerationStatus);
      if (url.pathname === "/api/llms/local") return json({ available: false, base_url: "", default_model: "none", model_count: 0, models: [], recommended_pulls: [], benchmark: null, warnings: [] });
      return json({}, { status: 404 });
    });

    render(<AskPage papers={[paper as never]} onSelectPaper={() => undefined} />);

    expect(await screen.findByRole("option", { name: /Dense semantic.*warming up/ })).toBeDisabled();
    expect(screen.getByText("Dense semantic: warming up")).toBeInTheDocument();
  });

  it("excludes metadata-only papers from Ask scopes, including deep links", async () => {
    const metadataOnly = {
      ...paper,
      paper_id: "paper-metadata-only",
      title: "Metadata-only Publication",
      public_access_level: "metadata_only",
      chunk_count: 0,
    };
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = new URL(String(input), window.location.origin);
      if (url.pathname === "/api/ask/diagnostics") return json(askDiagnostics);
      if (url.pathname === "/api/llms/status") return json(localGenerationStatus);
      if (url.pathname === "/api/llms/local") return json({ available: false, base_url: "", default_model: "none", model_count: 0, models: [], recommended_pulls: [], benchmark: null, warnings: [] });
      return json({}, { status: 404 });
    });

    render(<AskPage papers={[paper, metadataOnly] as never[]} initialPaperId={metadataOnly.paper_id} onSelectPaper={() => undefined} />);

    const scope = await screen.findByRole("combobox", { name: "Paper scope" });
    expect(scope).toHaveValue("");
    expect(screen.queryByRole("option", { name: "Metadata-only Publication" })).not.toBeInTheDocument();
    expect(screen.getByRole("option", { name: paper.title })).toBeInTheDocument();
    expect(screen.getByText(/Metadata-only catalogue records are not available as Ask scopes/)).toBeInTheDocument();
  });

  it("replaces Finder output atomically when switching between advisor and evidence-only modes", async () => {
    const user = userEvent.setup();
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = new URL(String(input), window.location.origin);
      if (url.pathname.endsWith("/extensions/diagnostics")) return json({ searchable_chunks: 1, searchable_papers: 1, total_recommendation_runs: 0, total_recommendations_generated: 0, grounded_runs: 0, partial_runs: 0, unsupported_runs: 0, default_provider: "offline_deterministic", last_recommendation_timestamp: null });
      if (url.pathname === "/api/recommendations/extensions" && init?.method === "POST") return json({
        recommendation_id: "run-1",
        request: {},
        grounding_status: "unsupported",
        recommendations: [unknownDifficultyRecommendation],
        warnings: [],
        provider: "offline_deterministic",
        model: "deterministic-v1",
        retrieval_mode: "hybrid",
        top_k: 5,
        created_at: "2026-01-01T00:00:00Z",
      });
      if (url.pathname === "/api/search") return json(searchPayload("profile", "hybrid", [hybridSourceResult]));
      return json({}, { status: 404 });
    });

    render(<ThesisExtensionFinder papers={[paper as never]} onSelectPaper={() => undefined} />);
    await user.click(screen.getByRole("button", { name: "Find Thesis Extensions" }));
    expect(await screen.findByRole("heading", { name: "Recommendation Run" })).toBeInTheDocument();
    expect(screen.getAllByText("Full advisor suggestions").length).toBeGreaterThan(0);
    expect(screen.getByText(/Difficulty could not be inferred from the available source evidence/)).toBeInTheDocument();

    await user.click(screen.getByRole("radio", { name: "Evidence-only ranked papers/passages" }));
    await user.click(screen.getByRole("button", { name: "Retrieve Evidence Only" }));
    expect(await screen.findByRole("heading", { name: "Evidence-only ranked papers and passages" })).toBeInTheDocument();
    expect(screen.getByText("Evidence-only baseline")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Recommendation Run" })).not.toBeInTheDocument();
  });

  it("renders only the approved effective artifact payload on public paper detail", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = new URL(String(input), window.location.origin);
      if (url.pathname.endsWith("/extraction")) return json(extractionDiagnostics);
      if (url.pathname.endsWith("/chunks")) return json([{ chunk_id: "paper-1-0001", paper_id: paper.paper_id, chunk_index: 0, page_start: 1, page_end: 1, section: "Summary", snippet: "Loaded source chunk", text: "Loaded source chunk", char_count: 19, word_count: 3, token_count_estimate: 4, source_hash: "fixture" }]);
      if (url.pathname.endsWith("/artifacts")) return json([{
        artifact_id: "artifact-approved",
        paper_id: paper.paper_id,
        artifact_type: "paper_intelligence_bundle",
        generated_json: intelligenceBundle("UNREVIEWED GENERATED TEXT"),
        effective_json: intelligenceBundle("APPROVED REVIEWER CORRECTION"),
        citations: [],
        grounding_status: "grounded",
        generation_status: "generated",
        warnings: [],
        review_status: "approved",
        provenance: { provider: "offline", model: "fixture", generated_at: "2026-01-01T00:00:00Z", approved_version: "2026-01-02T00:00:00Z", correction_fields: ["corrected_json"] },
        created_at: "2026-01-01T00:00:00Z",
      }]);
      if (url.pathname.endsWith("/related")) return json([]);
      return json({}, { status: 404 });
    });

    render(<PaperDetail paper={paper as never} onBack={() => undefined} />);
    expect(await screen.findByText("APPROVED REVIEWER CORRECTION")).toBeInTheDocument();
    expect(screen.queryByText("UNREVIEWED GENERATED TEXT")).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalled();
  });

  it("shows the current generated artifact publicly with an explicit unreviewed warning", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = new URL(String(input), window.location.origin);
      if (url.pathname.endsWith("/extraction")) return json(extractionDiagnostics);
      if (url.pathname.endsWith("/chunks")) return json([{ chunk_id: "paper-1-0001", paper_id: paper.paper_id, chunk_index: 0, page_start: 1, page_end: 1, section: "Summary", snippet: "Loaded source chunk", text: "Loaded source chunk", char_count: 19, word_count: 3, token_count_estimate: 4, source_hash: "fixture" }]);
      if (url.pathname.endsWith("/artifacts")) return json([{
        artifact_id: "artifact-needs-review",
        paper_id: paper.paper_id,
        artifact_type: "paper_intelligence_bundle",
        generated_json: intelligenceBundle("CURRENT GENERATED DRAFT"),
        effective_json: intelligenceBundle("CURRENT GENERATED DRAFT"),
        citations: [],
        grounding_status: "grounded",
        generation_status: "generated",
        warnings: [],
        review_status: "needs_review",
        provenance: { provider: "offline", model: "fixture", generated_at: "2026-01-01T00:00:00Z", approved_version: null, correction_fields: [] },
        created_at: "2026-01-01T00:00:00Z",
      }]);
      if (url.pathname.endsWith("/related")) return json([]);
      return json({}, { status: 404 });
    });

    render(<PaperDetail paper={paper as never} onBack={() => undefined} />);
    expect(await screen.findByText("Loaded source chunk")).toBeInTheDocument();
    expect(screen.getByText("CURRENT GENERATED DRAFT")).toBeInTheDocument();
    expect(screen.getByText(/Public AI-generated draft/)).toBeInTheDocument();
    expect(screen.getByText(/Current generated version/)).toBeInTheDocument();
    expect(screen.queryByText("Paper intelligence is awaiting approval")).not.toBeInTheDocument();
  });

  it("uses a generated artifact payload when an effective projection is absent", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = new URL(String(input), window.location.origin);
      if (url.pathname.endsWith("/extraction")) return json(extractionDiagnostics);
      if (url.pathname.endsWith("/chunks")) return json([]);
      if (url.pathname.endsWith("/artifacts")) return json([{
        artifact_id: "artifact-generated-default",
        paper_id: paper.paper_id,
        artifact_type: "paper_intelligence_bundle",
        generated_json: intelligenceBundle("GENERATED DEFAULT CONTENT"),
        effective_json: null,
        citations: [],
        grounding_status: "partial",
        generation_status: "generated",
        warnings: [],
        review_status: "needs_review",
        provenance: { provider: "offline", model: "fixture", generated_at: "2026-01-01T00:00:00Z", approved_version: null, correction_fields: [] },
        created_at: "2026-01-01T00:00:00Z",
      }]);
      if (url.pathname.endsWith("/related")) return json([]);
      return json({}, { status: 404 });
    });

    render(<PaperDetail paper={paper as never} onBack={() => undefined} />);

    expect(await screen.findByText("GENERATED DEFAULT CONTENT")).toBeInTheDocument();
    expect(screen.queryByText(/awaiting approval/i)).not.toBeInTheDocument();
  });
});

function intelligenceBundle(text: string) {
  const section = { text, support_status: "explicit", citations: [] };
  return {
    paper_id: paper.paper_id,
    paper_title: paper.title,
    authors: paper.authors,
    year: paper.year,
    generated_notice: "Approved output",
    public_summary: section,
    technical_summary: section,
    contribution: section,
    methods: section,
    limitations: section,
    future_work: section,
    possible_extensions: [],
    required_skills: { ...section, skills: [] },
    evaluation_plan: section,
    warnings: [],
    review_status: "approved",
  };
}
