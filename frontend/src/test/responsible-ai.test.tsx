import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { AskPage } from "../pages/AskPage";
import { Dashboard } from "../pages/Dashboard";
import { PaperDetail } from "../pages/PaperDetail";
import { SearchPage } from "../pages/SearchPage";
import { ThesisExtensionFinder } from "../pages/ThesisExtensionFinder";
import { json, paper, stats } from "./fixtures";

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
  searchable_chunks: 1,
  searchable_papers: 1,
  chunks_indexed_for_keyword_search: 1,
  chunks_indexed_for_feature_hashing: 1,
  chunks_indexed_for_dense_search: 0,
  chunks_indexed_for_semantic_search: null,
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
  it("does not report dense search unavailable before diagnostics finish loading", () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() => new Promise<Response>(() => undefined));
    render(<SearchPage papers={[paper as never]} onSelectPaper={() => undefined} />);
    expect(screen.queryByText(/Dense semantic search is unavailable/)).not.toBeInTheDocument();
  });

  it("treats a healthy public index projection as ready on Search and Dashboard", async () => {
    const projected = {
      ...indexDiagnostics,
      keyword: { ...indexDiagnostics.keyword, status: "public_projection_ready" },
      feature_hashing: { ...indexDiagnostics.feature_hashing, status: "public_projection_ready", underlying_index_status: "ready" },
    };
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = new URL(String(input));
      if (url.pathname === "/api/search/diagnostics") return json(projected);
      return json({}, { status: 404 });
    });
    render(<SearchPage papers={[paper as never]} onSelectPaper={() => undefined} />);
    await screen.findByText(/Feature hashing: 1 · public_projection_ready/);
    expect(screen.queryByText(/A required search index is not ready/)).not.toBeInTheDocument();

    render(<Dashboard stats={{ ...stats, feature_hashing_index_status: "public_projection_ready" } as never} papers={[paper as never]} />);
    expect(screen.queryByText(/search snapshot is incomplete or stale/)).not.toBeInTheDocument();
  });

  it("keeps Ollama disabled without a digest-verified model and labels protected diagnostics", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = new URL(String(input));
      if (url.pathname === "/api/ask/diagnostics") return json({ total_stored_answers: null, grounded_answers: null, partial_answers: null, unsupported_answers: null, default_provider: "offline_extractive", external_provider_available: false, searchable_chunks: 1, semantic_indexed_chunks: 1, last_answer_timestamp: null });
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
      const url = new URL(String(input));
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
      const url = new URL(String(input));
      if (url.pathname.endsWith("/extensions/diagnostics")) return json({ searchable_chunks: 0, searchable_papers: 0, total_recommendation_runs: null, total_recommendations_generated: null, grounded_runs: null, partial_runs: null, unsupported_runs: null, default_provider: "offline_deterministic", last_recommendation_timestamp: null });
      return json({}, { status: 404 });
    });

    render(<ThesisExtensionFinder papers={[]} onSelectPaper={() => undefined} />);

    expect(await screen.findByText("No papers are approved for public Finder recommendations yet")).toBeInTheDocument();
    expect(screen.getByText(/Reviewer-only technical prototype evidence is not substituted/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Find Thesis Extensions" })).toBeDisabled();
    expect(fetchMock.mock.calls.filter(([input]) => new URL(String(input)).pathname === "/api/recommendations/extensions")).toHaveLength(0);
  });

  it("shows distinct index modes, freshness, source passage IDs, and retryable search evidence", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = new URL(String(input));
      if (url.pathname === "/api/search/diagnostics") return json(indexDiagnostics);
      if (url.pathname === "/api/search") return json({ query: "RAG", mode: "keyword", result_count: 1, results: [sourceResult], warnings: [] });
      return json({}, { status: 404 });
    });
    render(<SearchPage papers={[paper as never]} onSelectPaper={() => undefined} />);
    expect(await screen.findByText(/Dense semantic: 0 · missing/)).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Search mode" })).toHaveValue("keyword");
    expect(screen.getByRole("option", { name: "Hybrid (experimental; not validated as better)" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Feature-hashing baseline" })).toBeInTheDocument();
    const searchInput = screen.getByRole("textbox", { name: "Search source chunks" });
    await user.clear(searchInput);
    await user.type(searchInput, "precision retrieval{Enter}");
    expect(await screen.findByText("Chunk paper-1-0001")).toBeInTheDocument();
    expect(screen.getAllByText("A source-grounded passage about retrieval.").length).toBeGreaterThan(0);
    expect(fetchMock.mock.calls.filter(([input]) => new URL(String(input)).pathname === "/api/search")).toHaveLength(1);
    await user.clear(searchInput);
    await user.type(searchInput, "edited after submission");
    expect(screen.getByText(/Results for “precision retrieval”/)).toBeInTheDocument();
  });

  it("ignores an older Search response that completes after a newer request", async () => {
    const user = userEvent.setup();
    const pending: Array<(response: Response) => void> = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = new URL(String(input));
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

    await act(async () => pending[1](await json({ query: "newer query", mode: "hybrid", result_count: 1, results: [{ ...sourceResult, snippet: "Newer result" }], warnings: [] })));
    expect(await screen.findByText("Newer result")).toBeInTheDocument();
    await act(async () => pending[0](await json({ query: "older query", mode: "hybrid", result_count: 1, results: [{ ...sourceResult, snippet: "Older result" }], warnings: [] })));
    expect(screen.getByText(/Results for “newer query”/)).toBeInTheDocument();
    expect(screen.queryByText("Older result")).not.toBeInTheDocument();
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
    const questionInput = screen.getByRole("textbox", { name: "Question" });
    await user.clear(questionInput);
    await user.type(questionInput, "What evidence supports retrieval?");
    await user.click(screen.getByRole("button", { name: "Ask" }));
    expect(await screen.findByText(/transient answer/)).toBeInTheDocument();
    expect(screen.getByText(/does not establish entailment or factual correctness/i)).toBeInTheDocument();
    expect(screen.getAllByText("Chunk paper-1-0001").length).toBeGreaterThan(0);
    expect(screen.getAllByText("A source-grounded passage about retrieval.").length).toBeGreaterThan(0);
    await user.clear(questionInput);
    await user.type(questionInput, "A different draft question");
    expect(screen.getByText(/Answer to “What evidence supports retrieval\?”/)).toBeInTheDocument();
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
      const url = new URL(String(input));
      if (url.pathname === "/api/ask/diagnostics") return json({ total_stored_answers: 0, grounded_answers: 0, partial_answers: 0, unsupported_answers: 0, default_provider: "offline_extractive", external_provider_available: false, searchable_chunks: 1, semantic_indexed_chunks: 1, last_answer_timestamp: null });
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
      const url = new URL(String(input));
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
      if (url.pathname === "/api/search") return json({ query: "profile", mode: "hybrid", result_count: 1, results: [sourceResult], warnings: [] });
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
      const url = new URL(String(input));
      if (url.pathname.endsWith("/extraction")) return json({ paper_id: paper.paper_id, pdf_text_status: "extracted", page_count: 4, total_char_count: 800, total_word_count: 120, pages_with_text: 4, pages_without_text: 0, possible_scanned_pdf: false, warnings: [], chunk_count: 1 });
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

  it("fails closed when an artifact has generated content but no approved effective version", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = new URL(String(input));
      if (url.pathname.endsWith("/extraction")) return json({ paper_id: paper.paper_id, pdf_text_status: "extracted", page_count: 4, total_char_count: 800, total_word_count: 120, pages_with_text: 4, pages_without_text: 0, possible_scanned_pdf: false, warnings: [], chunk_count: 1 });
      if (url.pathname.endsWith("/chunks")) return json([{ chunk_id: "paper-1-0001", paper_id: paper.paper_id, chunk_index: 0, page_start: 1, page_end: 1, section: "Summary", snippet: "Loaded source chunk", text: "Loaded source chunk", char_count: 19, word_count: 3, token_count_estimate: 4, source_hash: "fixture" }]);
      if (url.pathname.endsWith("/artifacts")) return json([{
        artifact_id: "artifact-needs-review",
        paper_id: paper.paper_id,
        artifact_type: "paper_intelligence_bundle",
        generated_json: intelligenceBundle("MUST NOT BE PUBLIC"),
        effective_json: null,
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
    expect(screen.getByText("Paper intelligence is awaiting approval")).toBeInTheDocument();
    expect(screen.queryByText("MUST NOT BE PUBLIC")).not.toBeInTheDocument();
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
