import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "jest-axe";
import { MemoryRouter } from "react-router-dom";

import { App } from "../App";
import { setReviewerToken } from "../api/client";
import type { AskResponse, SearchResponse } from "../types/paper";
import { installBaseFetchMock, json, paper } from "./fixtures";

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
};

describe("automated accessibility smoke", () => {
  beforeEach(() => installBaseFetchMock());
  afterEach(() => setReviewerToken(""));

  it.each([
    ["/", "Research intelligence dashboard"],
    ["/papers", "Paper Browser"],
    ["/papers/paper-1", "Grounded Research Discovery"],
    ["/search", "Search Source Chunks"],
    ["/ask", "Ask TTLAB"],
    ["/extensions", "Thesis Extension Finder"],
    ["/explorer", "Topic and author explorer"],
    ["/evaluation", "Evaluation dashboard"],
    ["/admin", "Reviewer authentication required"],
  ])("has no detectable axe violations on %s", async (route, heading) => {
    const { container } = render(<MemoryRouter initialEntries={[route]}><App /></MemoryRouter>);
    await screen.findByRole("heading", { name: heading });
    expect(await axe(container)).toHaveNoViolations();
  });

  it("has no detectable axe violations on a generated Ask answer", async () => {
    const user = userEvent.setup();
    overrideFetch((input, init) => {
      const url = requestUrl(input);
      if (url.pathname === "/api/ask" && init?.method === "POST") {
        return json({
          answer_id: "a11y-answer",
          question: "Which paper discusses retrieval?",
          answer: "The cited paper discusses retrieval.",
          grounding_status: "partial",
          support_status: "support_unverified",
          provider: "offline_extractive",
          model: "sentence-overlap-v1",
          retrieval_mode: "keyword",
          top_k: 5,
          paper_id: null,
          citations: [{
            paper_id: paper.paper_id,
            title: paper.title,
            authors: paper.authors,
            year: paper.year,
            chunk_id: "paper-1-0001",
            section: "Methodology",
            page_start: 2,
            page_end: 2,
            snippet: "A source-grounded passage.",
            score: 0.8,
            source_url: paper.source_url,
            pdf_url: paper.pdf_url,
          }],
          retrieved_chunks: [{
            chunk_id: "paper-1-0001",
            paper_id: paper.paper_id,
            title: paper.title,
            authors: paper.authors,
            year: paper.year,
            page_start: 2,
            page_end: 2,
            section: "Methodology",
            snippet: "A source-grounded passage.",
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
            source: { pdf_url: paper.pdf_url, post_url: paper.source_url },
          }],
          retrieval_metadata: { expanded_query: "Which paper discusses retrieval?", query_expansions: [], retrieval_strategy: "explicit_config_v1", retrieval_scope: "public" },
          generation_metadata: {},
          answerability: { answerable: true, reason: "source_term_coverage", query_terms: ["retrieval"], matched_query_terms: ["retrieval"], max_query_coverage: 1, minimum_query_coverage: 0.34, relevant_chunk_ids: ["paper-1-0001"], warnings: [] },
          claim_support: [{ claim: "The cited paper discusses retrieval [paper-1-0001].", classification: "support_unverified", cited_chunk_ids: ["paper-1-0001"], supporting_chunk_ids: ["paper-1-0001"], citation_support: [{ chunk_id: "paper-1-0001", lexical_overlap: 0.5, classification: "support_unverified", entailment_verified: false }], lexical_overlap: 0.5, entailment_verified: false }],
          runtime_provenance: { schema_version: 1 },
          source_text_delivery: "bounded_snippets_only",
          warnings: [],
          unsupported_claims: [],
          created_at: "2026-07-20T12:00:00Z",
        } satisfies AskResponse);
      }
      return undefined;
    });

    const { container } = render(<MemoryRouter initialEntries={["/ask"]}><App /></MemoryRouter>);
    await screen.findByRole("heading", { name: "Ask TTLAB" });
    const input = screen.getByRole("textbox", { name: "Question" });
    await user.clear(input);
    await user.type(input, "Which paper discusses retrieval?");
    await user.click(screen.getByRole("button", { name: "Ask" }));
    await screen.findByText("The cited paper discusses retrieval.");
    expect(await axe(container)).toHaveNoViolations();
  });

  it("has no detectable axe violations on a dynamic Finder evidence result", async () => {
    const user = userEvent.setup();
    overrideFetch((input) => {
      const url = requestUrl(input);
      if (url.pathname === "/api/search") {
        return json({
          query: "retrieval",
          mode: "keyword",
          result_count: 1,
          results: [{
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
            snippet: "A source-grounded passage.",
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
            source: { pdf_url: paper.pdf_url, post_url: paper.source_url },
          }],
          warnings: [],
          expanded_query: "retrieval",
          query_expansions: [],
          vector_provider: null,
          retrieval_strategy: "explicit_config_v1",
          retriever_config: retrieverConfig,
          retrieval_scope: "public",
        } satisfies SearchResponse);
      }
      return undefined;
    });

    const { container } = render(<MemoryRouter initialEntries={["/extensions"]}><App /></MemoryRouter>);
    await screen.findByRole("heading", { name: "Thesis Extension Finder" });
    await user.click(screen.getByRole("radio", { name: "Evidence-only ranked papers/passages" }));
    await user.click(screen.getByRole("button", { name: "Retrieve Evidence Only" }));
    await screen.findByRole("heading", { name: "Evidence-only ranked papers and passages" });
    expect(await axe(container)).toHaveNoViolations();
  });

  it("has no detectable axe violations on a retryable error state", async () => {
    const user = userEvent.setup();
    overrideFetch((input) => {
      const url = requestUrl(input);
      if (url.pathname === "/api/search") {
        return json({ detail: "Search index unavailable" }, { status: 503 });
      }
      return undefined;
    });

    const { container } = render(<MemoryRouter initialEntries={["/search"]}><App /></MemoryRouter>);
    await screen.findByRole("heading", { name: "Search Source Chunks" });
    await user.type(screen.getByRole("textbox", { name: "Search source chunks" }), "retrieval");
    await user.click(screen.getByRole("button", { name: "Search" }));
    expect((await screen.findAllByRole("alert")).length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Retry search" })).toBeInTheDocument();
    expect(await axe(container)).toHaveNoViolations();
  });

  it("has no detectable axe violations on the authenticated service-reviewer surface", async () => {
    setReviewerToken("a".repeat(32));
    overrideFetch((input) => {
      const url = requestUrl(input);
      if (url.pathname === "/api/admin/overview") return json({
        papers_total: 1,
        papers_needing_metadata_review: 1,
        papers_missing_pdfs: 0,
        papers_with_extraction_failures: 0,
        possible_scanned_pdfs: 0,
        total_chunks: 1,
        rag_answers: {},
        rag_answers_by_grounding: {},
        thesis_recommendations: {},
        thesis_recommendations_by_grounding: {},
        paper_artifacts: {},
        paper_artifacts_by_grounding: {},
        paper_artifacts_by_type: {},
        artifacts_needing_review: 0,
        total_review_events: 0,
        recent_review_events: [],
      });
      if (url.pathname === "/api/admin/publication-preview/papers") return json({ surface: "local_review_preview", public: false, notice: "Protected reviewer preview.", items: [] });
      if (url.pathname === "/api/admin/capabilities") return json({
        actor: { actor_id: "capture-service", role: "reviewer", reviewer_type: "service", local_demo_bypass: false },
        capabilities: { review: true, save_corrections: true, approve_or_reject: false, set_publication_and_rights: false, trigger_ingestion: false },
        allowed_review_transitions: { needs_review: ["needs_review", "needs_reprocess"] },
      });
      if (url.pathname === "/api/admin/ingestion-sync") return json({
        source: "ttlab", enabled: false, schedule: "0 2 * * *", timezone: "America/La_Paz",
        run_on_startup: false, worker_poll_seconds: 30, download_pdfs: false,
        dense_index_policy: "never", manual_trigger_allowed: false, running: false,
        manual_request_pending: false, manual_requested_at: null, manual_requested_by: null,
        last_success_at: null, last_failure_at: null, next_scheduled_at: null,
        last_run: null, recent_runs: [],
      });
      if (url.pathname === "/api/admin/review-queue") return json({ total: 0, limit: 50, offset: 0, items: [] });
      if (url.pathname === "/api/admin/review-events") return json({ total: 0, limit: 50, offset: 0, items: [] });
      return undefined;
    });

    const { container } = render(<MemoryRouter initialEntries={["/admin"]}><App /></MemoryRouter>);
    expect((await screen.findAllByText(/capture-service/)).length).toBeGreaterThan(0);
    expect(await axe(container)).toHaveNoViolations();
  });
});

type FetchOverride = (
  input: RequestInfo | URL,
  init?: RequestInit,
) => Promise<Response> | undefined;

function overrideFetch(handler: FetchOverride) {
  const mock = vi.mocked(globalThis.fetch);
  const fallback = mock.getMockImplementation();
  if (!fallback) throw new Error("Base fetch fixture must be installed before adding an override.");
  mock.mockImplementation((input, init) => handler(input, init) ?? fallback(input, init));
}

function requestUrl(input: RequestInfo | URL) {
  if (!input) return new URL("http://127.0.0.1:8000/__missing_fetch_input__");
  const raw = typeof input === "string"
    ? input
    : input instanceof URL
      ? input.href
      : input.url;
  return new URL(raw, "http://127.0.0.1:8000");
}
