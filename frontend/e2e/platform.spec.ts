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
  topics: ["retrieval"],
  ingestion_status: "imported",
  pdf_text_status: "extracted",
  page_count: 4,
  chunk_count: 1,
  review_status: "needs_review",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const stats = {
  papers: 1, with_pdf_url: 1, downloaded_pdfs: 1, extracted_pdfs: 1, extraction_failed: 0,
  no_text_pdfs: 0, missing_pdf: 0, total_chunks: 1, topic_count: 1, author_count: 1,
  paper_topic_links: 1, author_topic_links: 1, papers_with_topics: 1, authors_with_topics: 1,
  searchable_papers: 1, searchable_chunks: 1, keyword_indexed_chunks: 1, semantic_indexed_chunks: 1,
  feature_hashing_indexed_chunks: 1, dense_indexed_chunks: 0, feature_hashing_index_status: "ready",
  dense_index_status: "missing", total_ask_answers: 0, grounded_answers: 0, partial_answers: 0,
  unsupported_answers: 0, default_ask_provider: "offline_extractive", total_extension_recommendation_runs: 0,
  total_extension_ideas: 0, grounded_extension_runs: 0, partial_extension_runs: 0, unsupported_extension_runs: 0,
  total_paper_artifacts: 0, papers_with_artifacts: 0, podcast_scripts_generated: 0, artifacts_needing_review: 0,
  admin_review_queue_count: 0, papers_needing_review: 1, answers_needing_review: 0, recommendations_needing_review: 0,
  total_review_events: 0, latest_review_event_at: null, evaluation_files_present: {}, evaluation_last_run_at: null,
  top_topics: [["retrieval", 1]], recent_papers: [paper], evaluation_status: "not_started",
};

const sourceResult = {
  rank: 1, paper_id: "paper-1", paper_title: paper.title, authors: paper.authors, year: 2025,
  chunk_id: "paper-1-0001", section: "Methodology", page_start: 2, page_end: 2,
  snippet: "A source-grounded passage about retrieval.", scores: { keyword: 0.8, semantic: 0.4, combined: 0.8 },
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
    ["/extensions", "Thesis Extension Finder"],
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
  await page.getByRole("link", { name: "Details" }).click();
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
  await page.getByRole("button", { name: "Search" }).click();
  await expect(page.getByText("Chunk paper-1-0001")).toBeVisible();
  await expect(page.getByText("Pages 2-2")).toBeVisible();
  await expect(page.getByText(sourceResult.snippet)).toBeVisible();
});

test("keyboard skip navigation and anonymous admin protection are explicit", async ({ page }) => {
  await page.goto("/");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Skip to main content" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("#main-content")).toBeFocused();
  await page.goto("/admin");
  await expect(page.getByRole("heading", { name: "Reviewer authentication required" })).toBeVisible();
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

async function mockApi(page: Page) {
  await page.route("http://127.0.0.1:8000/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    let body: unknown;
    if (url.pathname === "/") body = { service: "TTLAB", status: "ok", security_mode: "production", admin_authentication: "bearer_token_required", frontend: "", api_docs: "disabled", health: "/health", readiness: "/ready" };
    else if (url.pathname === "/api/papers") body = [paper];
    else if (url.pathname === "/api/stats") body = stats;
    else if (url.pathname === "/api/search/diagnostics") body = {
      searchable_chunks: 1, searchable_papers: 1, chunks_indexed_for_keyword_search: 1,
      chunks_indexed_for_feature_hashing: 1, chunks_indexed_for_dense_search: 0, chunks_indexed_for_semantic_search: 1,
      embedding_provider: "feature_hashing", embedding_dimensions: 384, index_path: "redacted", index_status: "ready",
      last_indexed_timestamp: "2026-01-01T00:00:00Z", keyword: { status: "ready" },
      feature_hashing: { embedding_provider: "feature_hashing", embedding_dimensions: 384, indexed_chunks: 1, index_path: "redacted", status: "ready", index_status: "ready", last_indexed_at: "2026-01-01T00:00:00Z" },
      dense: { embedding_provider: "dense", embedding_dimensions: 384, indexed_chunks: 0, index_path: "redacted", status: "missing", index_status: "missing", last_indexed_at: null },
    };
    else if (url.pathname === "/api/search") body = { query: "RAG", mode: "hybrid", result_count: 1, results: [sourceResult], warnings: [] };
    else if (url.pathname === "/api/ask/diagnostics") body = { total_stored_answers: 0, grounded_answers: 0, partial_answers: 0, unsupported_answers: 0, default_provider: "offline_extractive", external_provider_available: false, searchable_chunks: 1, semantic_indexed_chunks: 1, last_answer_timestamp: null };
    else if (url.pathname === "/api/llms/local") body = { available: false, base_url: "", default_model: "none", model_count: 0, models: [], recommended_pulls: [], benchmark: null, warnings: ["Ollama unavailable"] };
    else if (url.pathname === "/api/recommendations/extensions/diagnostics") body = { searchable_chunks: 1, searchable_papers: 1, total_recommendation_runs: 0, total_recommendations_generated: 0, grounded_runs: 0, partial_runs: 0, unsupported_runs: 0, default_provider: "offline_deterministic", last_recommendation_timestamp: null };
    else if (url.pathname === "/api/explorer/overview") body = { topic_count: 0, author_count: 0, paper_count: 1, linked_paper_topics: 0, linked_author_topics: 0, top_topics: [], top_authors: [], recent_papers: [paper], explorer_index_status: "empty" };
    else if (url.pathname === "/api/topics" || url.pathname === "/api/authors") body = { total: 0, limit: 50, offset: 0, items: [] };
    else if (url.pathname === "/api/evaluation/dashboard") body = evaluationDashboard();
    else if (url.pathname === "/api/papers/paper-1/extraction") body = { paper_id: "paper-1", pdf_url: paper.pdf_url, pdf_text_status: "extracted", page_count: 4, total_char_count: 800, total_word_count: 120, pages_with_text: 4, pages_without_text: 0, possible_scanned_pdf: false, warnings: [], chunk_count: 1 };
    else if (url.pathname === "/api/papers/paper-1/chunks") body = [{ chunk_id: "paper-1-0001", paper_id: "paper-1", chunk_index: 0, page_start: 2, page_end: 2, section: "Methodology", snippet: "A source-grounded passage.", text: "A source-grounded passage.", char_count: 26, word_count: 4, token_count_estimate: 6, source_hash: "fixture" }];
    else if (url.pathname === "/api/papers/paper-1/artifacts" || url.pathname === "/api/papers/paper-1/related") body = [];
    else return route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: `Unhandled ${url.pathname}` }) });
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
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
