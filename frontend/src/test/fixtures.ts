export const paper = {
  paper_id: "paper-1",
  title: "Grounded Research Discovery",
  authors: ["A. Researcher"],
  year: 2025,
  publication_date_raw: "2025",
  venue: "Test venue",
  abstract: null,
  source_url: "https://lab.tt/paper-1",
  post_url: "https://lab.tt/paper-1",
  pdf_url: "https://lab.tt/paper-1.pdf",
  topics: ["retrieval"],
  ingestion_status: "imported",
  pdf_text_status: "extracted",
  page_count: 4,
  chunk_count: 1,
  review_status: "needs_review",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

export const stats = {
  papers: 1,
  with_pdf_url: 1,
  downloaded_pdfs: 1,
  extracted_pdfs: 1,
  extraction_failed: 0,
  no_text_pdfs: 0,
  missing_pdf: 0,
  total_chunks: 1,
  topic_count: 1,
  author_count: 1,
  paper_topic_links: 1,
  author_topic_links: 1,
  papers_with_topics: 1,
  authors_with_topics: 1,
  searchable_papers: 1,
  searchable_chunks: 1,
  keyword_indexed_chunks: 1,
  semantic_indexed_chunks: 1,
  feature_hashing_indexed_chunks: 1,
  dense_indexed_chunks: 0,
  feature_hashing_index_status: "ready",
  dense_index_status: "missing",
  total_ask_answers: 0,
  grounded_answers: 0,
  partial_answers: 0,
  unsupported_answers: 0,
  default_ask_provider: "offline_extractive",
  total_extension_recommendation_runs: 0,
  total_extension_ideas: 0,
  grounded_extension_runs: 0,
  partial_extension_runs: 0,
  unsupported_extension_runs: 0,
  total_paper_artifacts: 0,
  papers_with_artifacts: 0,
  podcast_scripts_generated: 0,
  artifacts_needing_review: 0,
  admin_review_queue_count: 0,
  papers_needing_review: 1,
  answers_needing_review: 0,
  recommendations_needing_review: 0,
  total_review_events: 0,
  latest_review_event_at: null,
  evaluation_files_present: {},
  evaluation_last_run_at: null,
  top_topics: [["retrieval", 1]],
  recent_papers: [paper],
  evaluation_status: "not_started",
};

export const serviceStatus = {
  service: "TTLAB Research Intelligence Platform",
  status: "ok",
  security_mode: "production",
  admin_authentication: "bearer_token_required",
  frontend: "http://127.0.0.1:5173",
  api_docs: "disabled",
  health: "/health",
  readiness: "/ready",
};

export function json(value: unknown, init: ResponseInit = {}) {
  return Promise.resolve(new Response(JSON.stringify(value), {
    status: 200,
    headers: { "Content-Type": "application/json" },
    ...init,
  }));
}

export function installBaseFetchMock() {
  return vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
    if (!input) return json({});
    const raw = typeof input === "string"
      ? input
      : input instanceof URL
        ? input.href
        : (input as Request).url;
    const url = new URL(raw, "http://127.0.0.1:8000");
    if (url.pathname === "/api/papers") return json([paper]);
    if (url.pathname === "/api/stats") return json(stats);
    if (url.pathname === "/") return json(serviceStatus);
    if (url.pathname === "/api/papers/paper-1/extraction") return json({
      paper_id: "paper-1",
      pdf_url: paper.pdf_url,
      pdf_text_status: "extracted",
      page_count: 4,
      total_char_count: 800,
      total_word_count: 120,
      pages_with_text: 4,
      pages_without_text: 0,
      possible_scanned_pdf: false,
      warnings: [],
      chunk_count: 1,
    });
    if (url.pathname === "/api/papers/paper-1/chunks") return json([{
      chunk_id: "paper-1-0001",
      paper_id: "paper-1",
      chunk_index: 0,
      page_start: 2,
      page_end: 2,
      section: "Methodology",
      snippet: "A source-grounded passage.",
      text: "A source-grounded passage.",
      char_count: 26,
      word_count: 4,
      token_count_estimate: 6,
      source_hash: "fixture",
    }]);
    if (url.pathname === "/api/papers/paper-1/artifacts") return json([]);
    if (url.pathname === "/api/papers/paper-1/related") return json([]);
    return json({ detail: `Unhandled test endpoint ${url.pathname}` }, { status: 404 });
  });
}
