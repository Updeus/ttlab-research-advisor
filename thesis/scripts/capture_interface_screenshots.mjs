#!/usr/bin/env node
/** Capture deterministic, synthetic current-interface fixtures for the thesis. */

import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const repository = path.resolve(here, "../..");
const requireFromFrontend = createRequire(path.join(repository, "frontend/package.json"));
const { chromium } = requireFromFrontend("@playwright/test");

const frontendOrigin = loopbackOrigin(process.env.TTLAB_SCREENSHOT_URL ?? "http://127.0.0.1:4173");
const apiOrigin = loopbackOrigin(process.env.TTLAB_API_URL ?? "http://127.0.0.1:8000");
const outputDirectory = path.resolve(
  process.env.TTLAB_SCREENSHOT_OUTPUT_DIR
    ?? path.join(repository, "thesis/figures/screenshots"),
);
const ideaPath = path.join(outputDirectory, "idea-generator-current.png");
const adminPath = path.join(outputDirectory, "admin-control-current.png");
const manifestPath = path.join(outputDirectory, "governance-capture-manifest.json");
const productSourceCommit = git("rev-parse", "HEAD");
const observedRequests = [];
const unhandledRequests = [];
const consoleErrors = [];

const paper = {
  paper_id: "fixture-paper-1",
  title: "Evidence-Aware Research Discovery",
  authors: ["A. Researcher"],
  year: 2025,
  publication_date_raw: "2025",
  venue: "Synthetic interface fixture",
  abstract: null,
  source_url: "https://example.invalid/paper",
  post_url: "https://example.invalid/paper",
  pdf_url: null,
  doi: null,
  keywords: ["retrieval", "research discovery"],
  topics: ["retrieval", "research discovery"],
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
  page_count: 8,
  chunk_count: 1,
  review_status: "approved",
  reviewed_at: null,
  created_at: "2026-07-22T00:00:00Z",
  updated_at: "2026-07-22T00:00:00Z",
};

const features = [
  ["papers", "Papers", "Browse approved publication records."],
  ["search", "Search", "Search source chunks."],
  ["ask", "Ask TTLAB", "Generate citation-bearing answers."],
  ["finder", "Idea Generator", "Generate source-aware candidate thesis directions."],
  ["explorer", "Topic and Author Explorer", "Explore publication-derived relations."],
  ["evaluation", "Evaluation", "Inspect bounded offline evidence."],
].map(([key, label, description]) => ({ key, label, description, enabled: true, disabled_message: null }));

const stats = {
  papers: 1, with_pdf_url: 0, downloaded_pdfs: 1, extracted_pdfs: 1,
  extraction_failed: 0, no_text_pdfs: 0, missing_pdf: 0,
  pdf_unavailability_reasons: {}, ocr_status_counts: { not_requested: 1 },
  extraction_content_type_counts: { digital_text: 1 },
  corpus_eligibility_status_counts: { eligible: 1 }, total_chunks: 1,
  topic_count: 2, author_count: 1, paper_topic_links: 2, author_topic_links: 2,
  papers_with_topics: 1, authors_with_topics: 1, searchable_papers: 1,
  searchable_chunks: 1, eligible_chunks: 1, raw_chunks: 1,
  keyword_indexed_chunks: 1, semantic_indexed_chunks: null,
  semantic_indexed_chunks_deprecated: "Feature hashing is lexical, not semantic.",
  feature_hashing_indexed_chunks: 1, dense_indexed_chunks: 1,
  feature_hashing_index_status: "ready", keyword_index_status: "ready",
  dense_index_status: "ready", index_health: {},
  default_ask_provider: "offline_extractive", evaluation_files_present: {},
  evaluation_last_run_at: null, top_topics: [["retrieval", 1]],
  recent_papers: [paper], evaluation_status: "available",
};

const ideaResponse = {
  message_id: "fixture-idea-message",
  reply: "A related TTLAB paper provides a useful starting point, but the proposed direction still requires literature review and supervisor approval.",
  paper_match_status: "matched",
  ideas: [{
    title: "Evidence-Aware Research Discovery for Student Projects",
    research_question: "How can evidence displays help students inspect AI-generated research directions?",
    summary: "Build a focused research-discovery prototype that separates retrieved paper facts from newly generated project suggestions.",
    why_it_fits: "It combines Python, web development, retrieval, and responsible-AI interface design.",
    mvp_scope: "Implement one source-aware idea workflow, a bounded corpus, and an auditable evaluation report.",
    skills: ["Python", "FastAPI", "React", "information retrieval"],
    evaluation_plan: "Measure retrieval accuracy, citation selection, answer-point coverage, and structured source-fidelity errors on a frozen test set.",
    basis: "paper_informed",
    source_chunk_ids: ["fixture-paper-1-0001"],
  }],
  citations: [{
    paper_id: paper.paper_id,
    title: paper.title,
    authors: paper.authors,
    year: paper.year,
    chunk_id: "fixture-paper-1-0001",
    section: "Methodology",
    page_start: 3,
    page_end: 4,
    snippet: "The fixture paper describes an evidence-aware workflow with source-linked retrieval and reviewable generated output.",
    score: 0.82,
    source_url: paper.source_url,
    pdf_url: null,
  }],
  provider: "ollama",
  model: "qwen3:4b@sha256:fixture-digest",
  generation_metadata: {
    paper_match_status: "matched",
    retrieved_source_count: 1,
    generation_time_digest_verified: true,
  },
  runtime_provenance: {
    prompt_template_version: "idea-generator-v1",
    retrieval_mode: "keyword",
    corpus_scope: "public",
  },
  warnings: ["Fixture output: cited papers provide background, not proof of novelty or feasibility."],
  created_at: "2026-07-22T00:00:00Z",
  demo_preview: false,
  corpus_access_mode: "approved_public_projection",
};

await fs.mkdir(outputDirectory, { recursive: true });
const browser = await chromium.launch({ headless: true });
try {
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1200 },
    deviceScaleFactor: 1,
    colorScheme: "light",
    reducedMotion: "reduce",
    locale: "en-GB",
    timezoneId: "UTC",
  });
  await context.addInitScript(() => {
    Object.defineProperty(Date, "now", { value: () => 1784678400000 });
  });
  await context.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.origin === frontendOrigin) return route.continue();
    if (url.origin !== apiOrigin) return route.abort("blockedbyclient");
    observedRequests.push({ method: request.method(), path: url.pathname });
    const fixture = apiFixture(url, request.method());
    if (fixture === undefined) {
      unhandledRequests.push(`${request.method()} ${url.pathname}`);
      return route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: "Unhandled fixture endpoint" }) });
    }
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(fixture) });
  });

  const page = await context.newPage();
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  await page.addStyleTag({ content: "*,*::before,*::after{animation:none!important;transition:none!important;caret-color:transparent!important}" }).catch(() => undefined);

  await page.goto(`${frontendOrigin}/extensions`, { waitUntil: "networkidle" });
  await page.getByRole("heading", { name: "Idea Generator" }).waitFor();
  await page.getByLabel("What are you interested in doing?").fill("I know Python and React and want a semester project about trustworthy research discovery.");
  await page.getByRole("button", { name: "Generate ideas" }).click();
  await page.getByRole("heading", { name: ideaResponse.ideas[0].title }).waitFor();
  await page.locator("details").evaluateAll((nodes) => nodes.forEach((node) => { node.open = true; }));
  await page.addStyleTag({ content: ".idea-composer,.toast-stack{display:none!important}" });
  await page.evaluate(() => document.fonts.ready);
  await page.locator(".idea-generator").screenshot({ path: ideaPath });

  await page.goto(`${frontendOrigin}/admin`, { waitUntil: "networkidle" });
  const signInHeading = page.getByRole("heading", { name: "Administrator sign in" });
  if (await signInHeading.isVisible()) {
    await page.getByLabel("Username").fill("fixture-admin");
    await page.getByLabel("Password").fill("synthetic-capture-password");
    await page.getByRole("button", { name: "Sign in" }).click();
  }
  await page.getByRole("heading", { name: "Admin Control Center" }).waitFor();
  await page.getByRole("button", { name: "Preview eligible approvals" }).click();
  await page.getByText("17 eligible; 3 blocked and unchanged.").waitFor();
  await page.evaluate(() => document.fonts.ready);
  const adminCard = page.locator(".admin-card").first();
  await adminCard.scrollIntoViewIfNeeded();
  const box = await adminCard.boundingBox();
  if (!box) throw new Error("Admin Control card has no capture box");
  await page.screenshot({
    path: adminPath,
    clip: { x: box.x, y: box.y, width: box.width, height: Math.min(box.height, 1010) },
  });
  await context.close();
} finally {
  await browser.close();
}

if (unhandledRequests.length || consoleErrors.length) {
  throw new Error(`Capture diagnostics failed: ${JSON.stringify({ unhandledRequests, consoleErrors })}`);
}

const captures = await Promise.all([ideaPath, adminPath].map(async (file) => {
  const bytes = await fs.readFile(file);
  return {
    file: path.basename(file),
    sha256: createHash("sha256").update(bytes).digest("hex"),
    width: bytes.readUInt32BE(16),
    height: bytes.readUInt32BE(20),
  };
}));

await fs.writeFile(manifestPath, `${JSON.stringify({
  schema_version: 4,
  status: "accepted_deterministic_fixture",
  generated_at: new Date().toISOString(),
  product_source_commit: productSourceCommit,
  frontend_origin: frontendOrigin,
  viewport: { width: 1440, height: 1200, device_scale_factor: 1 },
  scenarios: {
    idea_generator: "synthetic paper-informed conversation with transient-input, source-basis, citation, warning, and model metadata",
    admin_control: "synthetic authenticated admin state with feature/model status and actor-bound bulk preview",
  },
  claim_boundary: "Visible current-interface contract only; not live-model output, corpus evidence, usability, accessibility conformance, human review, effectiveness, ethics approval, or publication-rights approval.",
  privacy: {
    real_student_data: false,
    real_corpus_text: false,
    credentials_recorded: false,
    mutations_executed: false,
  },
  observed_request_count: observedRequests.length,
  captures,
}, null, 2)}\n`, "utf8");

console.log(JSON.stringify({ status: "PASS", outputDirectory, captures }, null, 2));

function apiFixture(url, method) {
  const pathName = url.pathname;
  if (pathName === "/") return { service: "TTLAB Research Intelligence Platform", status: "ok", security_mode: "production", admin_authentication: "bearer_token_required", frontend: frontendOrigin, api_docs: "disabled", health: "/health", readiness: "/ready", corpus_access_mode: "approved_public_projection" };
  if (pathName === "/api/features") return { features };
  if (pathName === "/api/papers") return [paper];
  if (pathName === "/api/stats") return stats;
  if (pathName === "/api/auth/me") return { authenticated: true, user: { user_id: "fixture-admin", username: "fixture-admin", display_name: "Fixture Administrator", active: true, must_change_password: false }, authentication_method: "session" };
  if (pathName === "/api/auth/login" && method === "POST") return { authenticated: true, user: { user_id: "fixture-admin", username: "fixture-admin", display_name: "Fixture Administrator", active: true, must_change_password: false }, authentication_method: "session" };
  if (pathName === "/api/llms/local") return { available: true, generation_available: true, base_url: "http://127.0.0.1:11434", default_model: "qwen3:4b@sha256:fixture-digest", model_count: 1, models: [], candidate_pulls: [], recommended_pulls: [], benchmark: null, warnings: [], model_policy: "pinned_digest_only" };
  if (pathName === "/api/recommendations/ideas" && method === "POST") return ideaResponse;
  if (pathName === "/api/admin/overview") return { papers_total: 134, papers_needing_metadata_review: 17, papers_missing_pdfs: 35, papers_with_extraction_failures: 2, possible_scanned_pdfs: 0, total_chunks: 735, rag_answers: {}, rag_answers_by_grounding: {}, thesis_recommendations: {}, thesis_recommendations_by_grounding: {}, paper_artifacts: {}, paper_artifacts_by_grounding: {}, paper_artifacts_by_type: {}, artifacts_needing_review: 4, total_review_events: 69, recent_review_events: [] };
  if (pathName === "/api/admin/publication-preview/papers") return { surface: "local_review_preview", public: false, notice: "Synthetic review fixture — no publication or rights decision is represented.", items: [] };
  if (pathName === "/api/admin/capabilities") return { actor: { actor_id: "fixture-admin", role: "admin", reviewer_type: "human", local_demo_bypass: false }, capabilities: { review: true, save_corrections: true, approve_or_reject: true, set_publication_and_rights: true, trigger_ingestion: true }, allowed_review_transitions: {} };
  if (pathName === "/api/admin/ingestion-sync") return { source: "ttlab", enabled: true, schedule: "0 2 * * *", timezone: "America/La_Paz", run_on_startup: false, worker_poll_seconds: 30, download_pdfs: true, dense_index_policy: "if_present", manual_trigger_allowed: true, running: false, manual_request_pending: false, manual_requested_at: null, manual_requested_by: null, last_success_at: null, last_failure_at: null, next_scheduled_at: "2026-07-23T06:00:00Z", last_run: null, recent_runs: [] };
  if (pathName === "/api/admin/review-queue") return { total: 0, limit: 50, offset: 0, items: [] };
  if (pathName === "/api/admin/review-events") return { total: 0, limit: 50, offset: 0, items: [] };
  if (pathName === "/api/admin/control/summary") return { features, admin_count: 2, corpus_import_available: false, corpus_import_blocker: "atomic_generation_promotion_not_implemented" };
  if (pathName === "/api/admin/control/models") return { provider_reachable: true, warnings: [], items: [{ name: "qwen3:4b", digest: "sha256:fixture-digest", pinned: true, enabled: true, is_default: true, digest_matches: true }] };
  if (pathName === "/api/admin/control/admins") return { items: [{ user_id: "fixture-admin", username: "fixture-admin", display_name: "Fixture Administrator", active: true, must_change_password: false }] };
  if (pathName === "/api/admin/control/ingestion-candidates") return { items: [], import_available: false, import_blocker: "atomic_generation_promotion_not_implemented" };
  if (pathName === "/api/admin/control/bulk/preview" && method === "POST") return { operation_id: "fixture-preview", preview_hash: "f".repeat(64), eligible_count: 17, blocked_count: 3, approval_mode: "eligible", expires_at: "2026-07-22T00:10:00Z" };
  return undefined;
}

function loopbackOrigin(value) {
  const parsed = new URL(value);
  if (!["127.0.0.1", "localhost", "::1"].includes(parsed.hostname)) {
    throw new Error(`Screenshot origin must be loopback: ${value}`);
  }
  return parsed.origin;
}

function git(...args) {
  return execFileSync("git", args, { cwd: repository, encoding: "utf8" }).trim();
}
