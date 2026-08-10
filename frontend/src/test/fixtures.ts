import type { Paper, Stats } from "../types/paper";

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
  doi: null,
  keywords: [],
  topics: ["retrieval"],
  ingestion_status: "imported",
  pdf_text_status: "extracted",
  extraction_content_type: "digital_text",
  ocr_status: "not_requested",
  ocr_review_required: false,
  corpus_eligibility_status: "eligible",
  corpus_exclusion_reason: null,
  publication_status: "published",
  rights_status: "cleared",
  public_access_level: "searchable",
  pdf_title_match_status: "matched",
  page_count: 4,
  chunk_count: 1,
  review_status: "approved",
  reviewed_at: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
} satisfies Paper;

export const stats = {
  papers: 1,
  with_pdf_url: 1,
  downloaded_pdfs: 1,
  extracted_pdfs: 1,
  extraction_failed: 0,
  no_text_pdfs: 0,
  missing_pdf: 0,
  pdf_unavailability_reasons: {},
  ocr_status_counts: { not_requested: 1 },
  extraction_content_type_counts: { digital_text: 1 },
  corpus_eligibility_status_counts: { eligible: 1 },
  total_chunks: 1,
  topic_count: 1,
  author_count: 1,
  paper_topic_links: 1,
  author_topic_links: null,
  papers_with_topics: 1,
  authors_with_topics: null,
  searchable_papers: 1,
  searchable_chunks: 1,
  eligible_chunks: 1,
  raw_chunks: 1,
  keyword_indexed_chunks: 1,
  semantic_indexed_chunks: null,
  semantic_indexed_chunks_deprecated: "Use feature_hashing_indexed_chunks; feature hashing is lexical, not semantic.",
  feature_hashing_indexed_chunks: 1,
  dense_indexed_chunks: 0,
  keyword_index_status: "ready",
  feature_hashing_index_status: "ready",
  dense_index_status: "missing",
  index_health: {
    keyword: { status: "ready", projection_status: "public_projection_ready", indexed_chunks: 1, public_eligible_chunks: 1, underlying_index_status: "ready", underlying_representation_valid: true, underlying_error_count: 0, last_indexed_at: "2026-01-01T00:00:00Z" },
    feature_hashing: { status: "ready", projection_status: "public_projection_ready", indexed_chunks: 1, public_eligible_chunks: 1, underlying_index_status: "ready", underlying_representation_valid: true, underlying_error_count: 0, last_indexed_at: "2026-01-01T00:00:00Z", classification: "lexical_feature_hashing" },
    dense: { status: "missing", projection_status: "underlying_index_not_ready", indexed_chunks: 0, public_eligible_chunks: 1, underlying_index_status: "missing", underlying_representation_valid: false, underlying_error_count: 0, last_indexed_at: null },
  },
  default_ask_provider: "offline_extractive",
  evaluation_files_present: {},
  evaluation_last_run_at: null,
  top_topics: [["retrieval", 1]],
  recent_papers: [paper],
  evaluation_status: "not_started",
} satisfies Stats;

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
    if (url.pathname === "/api/search/diagnostics") return json({
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
    });
    if (url.pathname === "/api/ask/diagnostics") return json({
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
      keyword_index: { status: "ready", projection_status: "public_projection_ready", indexed_chunks: 1, public_eligible_chunks: 1, underlying_index_status: "ready", underlying_representation_valid: true, underlying_error_count: 0, last_indexed_at: "2026-01-01T00:00:00Z" },
      feature_hashing_index: { status: "ready", projection_status: "public_projection_ready", indexed_chunks: 1, public_eligible_chunks: 1, underlying_index_status: "ready", underlying_representation_valid: true, underlying_error_count: 0, last_indexed_at: "2026-01-01T00:00:00Z", classification: "lexical_feature_hashing" },
      dense_index: { status: "missing", projection_status: "underlying_index_not_ready", indexed_chunks: 0, public_eligible_chunks: 1, underlying_index_status: "missing", underlying_representation_valid: false, underlying_error_count: 0, last_indexed_at: null },
    });
    if (url.pathname === "/api/llms/status") return json({
      runtime_profile: "local",
      provider: "ollama",
      display_name: "Local Ollama",
      configured: true,
      model: "qwen-test:4b",
      model_selection_enabled: true,
      external_processing: false,
      privacy_notice: "Generation stays on the configured local runtime.",
    });
    if (url.pathname === "/api/llms/local") return json({
      available: false,
      base_url: "",
      default_model: "none",
      model_count: 0,
      models: [],
      recommended_pulls: [],
      benchmark: null,
      warnings: ["Ollama unavailable"],
    });
    if (url.pathname === "/api/recommendations/extensions/diagnostics") return json({
      searchable_chunks: 1,
      searchable_papers: 1,
      total_recommendation_runs: 0,
      total_recommendations_generated: 0,
      grounded_runs: 0,
      partial_runs: 0,
      unsupported_runs: 0,
      default_provider: "offline_deterministic",
      last_recommendation_timestamp: null,
    });
    if (url.pathname === "/api/explorer/overview") return json({
      topic_count: 0,
      author_count: 0,
      paper_count: 1,
      linked_paper_topics: 0,
      linked_author_topics: 0,
      top_topics: [],
      top_authors: [],
      recent_papers: [paper],
      explorer_index_status: "empty",
    });
    if (url.pathname === "/api/topics" || url.pathname === "/api/authors") return json({ total: 0, limit: 50, offset: 0, items: [] });
    if (url.pathname === "/api/evaluation/dashboard") return json(emptyEvaluationDashboard());
    return json({ detail: `Unhandled test endpoint ${url.pathname}` }, { status: 404 });
  });
}

function emptyEvaluationDashboard() {
  const status = { status: "not_run", result_file_exists: false, path: "redacted", last_run_timestamp: null };
  return {
    retrieval: { ...status, question_count: 0, recall_at_3: null, recall_at_5: null, mrr: null },
    qa: { ...status, question_count: 0, answer_count: 0, cited_gold_paper_count: 0, citation_count: 0, grounding_counts: {} },
    extension: { ...status, case_count: 0, recommendation_count: 0, citation_coverage: null, grounding_counts: {}, warnings_count: 0 },
    artifact: { ...status, case_count: 0, artifact_count: 0, citation_coverage: null, grounding_counts: {}, warnings_count: 0, sections_with_explicit_support: 0, sections_inferred: 0, sections_not_found: 0 },
    human_review_templates: {},
    overall_quality: {},
    result_files: {},
  };
}
