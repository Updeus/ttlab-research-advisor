import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

const paper = {
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
};

const secondPaper = {
  ...paper,
  paper_id: "paper-2",
  title: "Climate Network Planning",
  authors: ["B. Analyst"],
  year: 2024,
  publication_date_raw: "2024",
  venue: "Climate Systems",
  topics: ["climate", "networks"],
  source_url: "https://lab.tt/paper-2",
  post_url: "https://lab.tt/paper-2",
  pdf_url: "https://lab.tt/paper-2.pdf",
};

const stats = {
  papers: 1, with_pdf_url: 1, downloaded_pdfs: 1, extracted_pdfs: 1, extraction_failed: 0,
  no_text_pdfs: 0, missing_pdf: 0, pdf_unavailability_reasons: {}, ocr_status_counts: { not_requested: 1 },
  extraction_content_type_counts: { digital_text: 1 }, corpus_eligibility_status_counts: { eligible: 1 },
  total_chunks: 1, topic_count: 1, author_count: 1,
  paper_topic_links: 1, author_topic_links: null, papers_with_topics: 1, authors_with_topics: null,
  searchable_papers: 1, searchable_chunks: 1, eligible_chunks: 1, raw_chunks: 1,
  keyword_indexed_chunks: 1, semantic_indexed_chunks: null,
  semantic_indexed_chunks_deprecated: "Use feature_hashing_indexed_chunks; feature hashing is lexical, not semantic.",
  feature_hashing_indexed_chunks: 1, dense_indexed_chunks: 0, feature_hashing_index_status: "ready",
  keyword_index_status: "ready", dense_index_status: "missing",
  index_health: {
    keyword: { status: "ready", projection_status: "public_projection_ready", indexed_chunks: 1, public_eligible_chunks: 1, underlying_index_status: "ready", underlying_representation_valid: true, underlying_error_count: 0, last_indexed_at: "2026-01-01T00:00:00Z" },
    feature_hashing: { status: "ready", projection_status: "public_projection_ready", indexed_chunks: 1, public_eligible_chunks: 1, underlying_index_status: "ready", underlying_representation_valid: true, underlying_error_count: 0, last_indexed_at: "2026-01-01T00:00:00Z", classification: "lexical_feature_hashing" },
    dense: { status: "missing", projection_status: "underlying_index_not_ready", indexed_chunks: 0, public_eligible_chunks: 1, underlying_index_status: "missing", underlying_representation_valid: false, underlying_error_count: 0, last_indexed_at: null },
  },
  default_ask_provider: "offline_extractive", evaluation_files_present: {}, evaluation_last_run_at: null,
  top_topics: [["retrieval", 1]], recent_papers: [paper], evaluation_status: "not_started",
};

const retrieverConfig = {
  enable_query_expansion: true, enable_metadata_boost: true, enable_section_boost: true,
  enable_evidence_adjustment: true, enable_topic_adjustment: true, enable_diversity_penalty: true,
  keyword_weight: 0.42, vector_weight: 0.48, metadata_scale: 1, section_scale: 1,
  evidence_scale: 1, topic_scale: 1, diversity_scale: 1, candidate_multiplier: 3,
};

const sourceResult = {
  rank: 1, paper_id: "paper-1", paper_title: paper.title, authors: paper.authors, year: 2025,
  venue: paper.venue, topics: paper.topics, chunk_id: "paper-1-0001", chunk_index: 0,
  section: "Methodology", page_start: 2, page_end: 2,
  snippet: "A source-grounded passage about retrieval.",
  scores: { keyword: 0.8, vector: 0, vector_provider: null, metadata: 0, section_boost: 0, evidence_quality: 0, topical_alignment: 0, diversity_penalty: 0, combined: 0.8 },
  source: { pdf_url: paper.pdf_url, post_url: paper.post_url },
};

test.beforeEach(async ({ page }) => {
  await mockApi(page);
});

test("all primary surfaces have reproducible routes and titles", async ({ page }) => {
  const routes = [
    ["/", "Dashboard"],
    ["/papers", "Paper Browser"],
    ["/search", "Search"],
    ["/ask", "Ask TTLAB"],
    ["/extensions", "Idea Generator"],
    ["/explorer", "Topic and Author Explorer"],
    ["/evaluation", "Evaluation Dashboard"],
    ["/admin", "Admin Review"],
  ] as const;
  for (const [path, title] of routes) {
    await page.goto(path);
    await expect(page).toHaveTitle(new RegExp(`${title} \\| TTLAB`));
    await expect(page.locator("main")).toBeVisible();
  }
  await page.goto("/not-a-route");
  await expect(page.getByRole("heading", { name: "Page not found" })).toBeVisible();
});

test("paper details deep-link, reload, and browser history work", async ({ page }) => {
  await page.goto("/papers");
  await page.getByRole("link", { name: "Details" }).first().click();
  await expect(page).toHaveURL(/\/papers\/paper-1$/);
  await expect(page.getByRole("heading", { name: paper.title })).toBeVisible();
  await page.reload();
  await expect(page.getByText("A source-grounded passage.")).toBeVisible();
  await page.goBack();
  await expect(page.getByRole("heading", { name: "Paper Browser" })).toBeVisible();
});

test("search presents page/chunk citation evidence and distinct retrieval modes", async ({ page }) => {
  await page.goto("/search");
  await expect(page.getByRole("option", { name: "Feature-hashing baseline" })).toBeAttached();
  await expect(page.getByRole("option", { name: "Dense semantic (learned model)" })).toBeAttached();
  let searchRequests = 0;
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === "/api/search") searchRequests += 1;
  });
  const searchInput = page.getByRole("textbox", { name: "Search source chunks" });
  await searchInput.fill("precision retrieval");
  await searchInput.press("Enter");
  await expect(page.getByText("Chunk paper-1-0001")).toBeVisible();
  await expect(page.getByText("Pages 2-2")).toBeVisible();
  await expect(page.getByText(sourceResult.snippet)).toBeVisible();
  expect(searchRequests).toBe(1);
  await searchInput.fill("edited draft");
  await expect(page.getByText(/Results for “precision retrieval”/)).toBeVisible();
});

test("paper facets persist through reload and browser history", async ({ page }) => {
  await page.goto("/papers?topic=retrieval");
  await expect(page.getByRole("heading", { name: paper.title })).toBeVisible();
  await expect(page.getByRole("heading", { name: secondPaper.title })).toHaveCount(0);

  await page.getByLabel("Filter by topic").selectOption("climate");
  await expect(page).toHaveURL(/topic=climate/);
  await expect(page.getByRole("heading", { name: secondPaper.title })).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("Filter by topic")).toHaveValue("climate");
  await expect(page.getByRole("heading", { name: secondPaper.title })).toBeVisible();

  await page.goBack();
  await expect(page.getByLabel("Filter by topic")).toHaveValue("retrieval");
  await expect(page.getByRole("heading", { name: paper.title })).toBeVisible();
});

test("explorer subnavigation is keyboard-operable and loads each routed detail once", async ({ page }) => {
  let detailRequests = 0;
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === "/api/topics/retrieval") detailRequests += 1;
  });
  await page.goto("/explorer");
  const topicsLink = page.getByRole("link", { name: "Topics" });
  await topicsLink.focus();
  await topicsLink.press("Enter");
  await expect(topicsLink).toHaveAttribute("aria-current", "page");
  await page.getByRole("button", { name: "Open Topic" }).click();
  await expect(page).toHaveURL(/\/explorer\/topics\/retrieval$/);
  await expect.poll(() => detailRequests).toBe(1);
  await expect(page.getByRole("heading", { name: "Retrieval", exact: true }).last()).toBeVisible();
});

test("search remains usable when the publication catalogue is unavailable", async ({ page }) => {
  await page.route("http://127.0.0.1:8000/api/papers", (route) => route.fulfill({
    status: 503,
    contentType: "application/json",
    body: JSON.stringify({ detail: "Catalogue unavailable" }),
  }));
  await page.goto("/search");
  await expect(page.getByRole("heading", { name: "Publication catalogue unavailable" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Search Source Chunks" })).toBeVisible();
  await page.getByRole("button", { name: "Search" }).click();
  await expect(page.getByText(sourceResult.snippet)).toBeVisible();
});

test("keyboard skip navigation and anonymous admin protection are explicit", async ({ page }) => {
  await page.goto("/");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Skip to main content" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("#main-content")).toBeFocused();
  await page.goto("/admin");
  await expect(page.getByRole("heading", { name: "Administrator sign in" })).toBeVisible();
  expect(await page.evaluate(() => ({ local: localStorage.length, session: sessionStorage.length }))).toEqual({ local: 0, session: 0 });
});

test("primary routes do not overflow at target widths", async ({ page }) => {
  const routes = ["/", "/papers", "/search", "/ask", "/extensions", "/explorer", "/evaluation", "/admin"];
  for (const width of [360, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    for (const route of routes) {
      await page.goto(route);
      await page.locator("main").waitFor();
      const dimensions = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, client: document.documentElement.clientWidth }));
      expect(dimensions.scroll, `${route} at ${width}px`).toBeLessThanOrEqual(dimensions.client);
    }
  }
});

test("primary navigation forms non-overlapping rows at the tablet breakpoint", async ({ page }) => {
  await page.setViewportSize({ width: 768, height: 900 });
  await page.goto("/");
  const boxes = await page.locator(".tabs a").evaluateAll((links) => links.map((link) => {
    const box = link.getBoundingClientRect();
    return { left: box.left, right: box.right, top: box.top, scrollWidth: link.scrollWidth, clientWidth: link.clientWidth };
  }));
  const rows = new Map<number, typeof boxes>();
  for (const box of boxes) {
    const key = Math.round(box.top);
    rows.set(key, [...(rows.get(key) ?? []), box]);
    expect(box.scrollWidth).toBeLessThanOrEqual(box.clientWidth);
  }
  expect(rows.size).toBe(2);
  for (const row of rows.values()) {
    expect(row.length).toBeGreaterThan(0);
    expect(row.length).toBeLessThanOrEqual(4);
    const ordered = [...row].sort((left, right) => left.left - right.left);
    for (let index = 1; index < ordered.length; index += 1) {
      expect(ordered[index - 1].right).toBeLessThanOrEqual(ordered[index].left);
    }
  }
});

async function mockApi(page: Page) {
  await page.route("http://127.0.0.1:8000/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    let body: unknown;
    if (url.pathname === "/") body = { service: "TTLAB", status: "ok", security_mode: "production", admin_authentication: "bearer_token_required", frontend: "", api_docs: "disabled", health: "/health", readiness: "/ready" };
    else if (url.pathname === "/api/papers") body = [paper, secondPaper];
    else if (url.pathname === "/api/stats") body = stats;
    else if (url.pathname === "/api/search/diagnostics") body = {
      searchable_chunks: 1, searchable_papers: 1, chunks_indexed_for_keyword_search: 1,
      total_chunks: 1, raw_chunks: null, eligible_chunks: 1,
      chunks_indexed_for_feature_hashing: 1, chunks_indexed_for_dense_search: 0, chunks_indexed_for_semantic_search: null,
      semantic_search_deprecation: "Feature hashing is a lexical baseline; use feature_hashing explicitly.",
      embedding_provider: null, embedding_dimensions: null, index_status: "ready",
      last_indexed_timestamp: null,
      keyword: { status: "ready", projection_status: "public_projection_ready", indexed_chunks: 1, public_eligible_chunks: 1, underlying_index_status: "ready", underlying_representation_valid: true, underlying_error_count: 0, last_indexed_at: "2026-01-01T00:00:00Z" },
      feature_hashing: { status: "ready", projection_status: "public_projection_ready", indexed_chunks: 1, public_eligible_chunks: 1, underlying_index_status: "ready", underlying_representation_valid: true, underlying_error_count: 0, last_indexed_at: "2026-01-01T00:00:00Z", classification: "lexical_feature_hashing" },
      dense: { status: "missing", projection_status: "underlying_index_not_ready", indexed_chunks: 0, public_eligible_chunks: 1, underlying_index_status: "missing", underlying_representation_valid: false, underlying_error_count: 0, last_indexed_at: null },
    };
    else if (url.pathname === "/api/search") {
      const query = url.searchParams.get("q") ?? "";
      body = { query, expanded_query: query, query_expansions: [], mode: "keyword", result_count: 1, results: [sourceResult], warnings: [], vector_provider: null, retrieval_strategy: "explicit_config_v1", retriever_config: retrieverConfig, retrieval_scope: "public" };
    }
    else if (url.pathname === "/api/ask/diagnostics") body = {
      total_stored_answers: null, grounded_answers: null, partial_answers: null, unsupported_answers: null,
      history_counts_visibility: "protected_reviewer_only", history_counts_observed: false,
      default_provider: "offline_extractive", allowed_providers: ["offline_extractive"],
      provider_matrix: { offline_extractive: { enabled: true, effective_model: "sentence-overlap-v1", identity_scope: "versioned_deterministic_algorithm" } },
      external_provider_available: false, external_provider_availability_scope: "configured_pinned_model_not_runtime_reachability",
      last_answer_timestamp: null, scope: "public", searchable_chunks: 1, raw_chunks: null,
      semantic_indexed_chunks: null, semantic_index_deprecation: "Feature hashing is lexical, not semantic.",
      keyword_index: { status: "ready", projection_status: "public_projection_ready", indexed_chunks: 1, public_eligible_chunks: 1, underlying_index_status: "ready", underlying_representation_valid: true, underlying_error_count: 0, last_indexed_at: "2026-01-01T00:00:00Z" },
      feature_hashing_index: { status: "ready", projection_status: "public_projection_ready", indexed_chunks: 1, public_eligible_chunks: 1, underlying_index_status: "ready", underlying_representation_valid: true, underlying_error_count: 0, last_indexed_at: "2026-01-01T00:00:00Z", classification: "lexical_feature_hashing" },
      dense_index: { status: "missing", projection_status: "underlying_index_not_ready", indexed_chunks: 0, public_eligible_chunks: 1, underlying_index_status: "missing", underlying_representation_valid: false, underlying_error_count: 0, last_indexed_at: null },
    };
    else if (url.pathname === "/api/llms/local") body = { available: false, base_url: "", default_model: "none", model_count: 0, models: [], recommended_pulls: [], benchmark: null, warnings: ["Ollama unavailable"] };
    else if (url.pathname === "/api/recommendations/extensions/diagnostics") body = { searchable_chunks: 1, searchable_papers: 1, total_recommendation_runs: 0, total_recommendations_generated: 0, grounded_runs: 0, partial_runs: 0, unsupported_runs: 0, default_provider: "offline_deterministic", last_recommendation_timestamp: null };
    else if (url.pathname === "/api/explorer/overview") body = { topic_count: 1, author_count: 0, paper_count: 2, linked_paper_topics: 1, linked_author_topics: 0, top_topics: [topicSummary()], top_authors: [], recent_papers: [paper, secondPaper], explorer_index_status: "ready" };
    else if (url.pathname === "/api/topics") body = { total: 1, limit: 50, offset: 0, items: [topicSummary()] };
    else if (url.pathname === "/api/topics/retrieval") body = { ...topicSummary(), papers: [], authors: [], related_topics: [] };
    else if (url.pathname === "/api/authors") body = { total: 0, limit: 50, offset: 0, items: [] };
    else if (url.pathname === "/api/evaluation/dashboard") body = evaluationDashboard();
    else if (url.pathname === "/api/papers/paper-1/extraction") body = { paper_id: "paper-1", pdf_url: paper.pdf_url, pdf_text_status: "extracted", pdf_unavailability_reason: null, page_count: 4, total_char_count: 800, total_word_count: 120, pages_with_text: 4, pages_without_text: 0, possible_scanned_pdf: false, extraction_content_type: "digital_text", ocr_status: "not_requested", ocr_provider: null, ocr_provider_version: null, ocr_pages_count: 0, ocr_review_required: false, pdf_title_match_status: "matched", pdf_title_match_score: 1, corpus_eligibility_status: "eligible", corpus_exclusion_reason: null, warnings: [], chunk_count: 1 };
    else if (url.pathname === "/api/papers/paper-1/chunks") body = [{ chunk_id: "paper-1-0001", paper_id: "paper-1", chunk_index: 0, page_start: 2, page_end: 2, section: "Methodology", snippet: "A source-grounded passage.", text: "A source-grounded passage.", char_count: 26, word_count: 4, token_count_estimate: 6, source_hash: "fixture" }];
    else if (url.pathname === "/api/papers/paper-1/artifacts" || url.pathname === "/api/papers/paper-1/related") body = [];
    else return route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: `Unhandled ${url.pathname}` }) });
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
}

function topicSummary() {
  return {
    topic_id: "retrieval",
    name: "Retrieval",
    normalized_name: "retrieval",
    description: "Source-derived retrieval topic.",
    paper_count: 1,
    author_count: 1,
    top_authors: [],
    sample_papers: [],
    review_status: "needs_review",
  };
}

function evaluationDashboard() {
  const status = { status: "not_run", result_file_exists: false, path: "redacted", last_run_timestamp: null };
  return {
    retrieval: { ...status, question_count: 0, recall_at_3: null, recall_at_5: null, mrr: null },
    qa: { ...status, question_count: 0, answer_count: 0, cited_gold_paper_count: 0, citation_count: 0, grounding_counts: {} },
    extension: { ...status, case_count: 0, recommendation_count: 0, citation_coverage: null, grounding_counts: {}, warnings_count: 0 },
    artifact: { ...status, case_count: 0, artifact_count: 0, citation_coverage: null, grounding_counts: {}, warnings_count: 0, sections_with_explicit_support: 0, sections_inferred: 0, sections_not_found: 0 },
    human_review_templates: {}, overall_quality: {}, result_files: {},
  };
}
