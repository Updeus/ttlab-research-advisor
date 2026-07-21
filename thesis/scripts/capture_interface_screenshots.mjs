#!/usr/bin/env node
/**
 * Stage manuscript UI evidence from an explicitly isolated live runtime.
 *
 * This script deliberately never writes to thesis/figures/screenshots. A run is
 * accepted only when the backend is local, bearer-protected, index-ready, and
 * serving an identity-valid current remediation-v2 package. The generated
 * screenshots and capture-manifest.json remain in an ignored staging directory
 * for manual privacy/rights and print-scale inspection before any separate,
 * explicit promotion step.
 */

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

const baseUrl = localOrigin(process.env.TTLAB_SCREENSHOT_URL ?? "http://127.0.0.1:4173", "TTLAB_SCREENSHOT_URL");
const apiUrl = localOrigin(process.env.TTLAB_API_URL ?? "http://127.0.0.1:8000", "TTLAB_API_URL");
const reviewerToken = process.env.TTLAB_SCREENSHOT_REVIEWER_TOKEN?.trim() ?? "";
const expectedActorId = process.env.TTLAB_SCREENSHOT_EXPECTED_ACTOR_ID?.trim() || "capture-service";
const outputDirectory = path.resolve(
  process.env.TTLAB_SCREENSHOT_OUTPUT_DIR
    ?? path.join(repository, "tmp/manuscript-interface-captures/staged"),
);
const trackedScreenshotDirectory = path.join(repository, "thesis/figures/screenshots");
const repositoryTempDirectory = path.join(repository, "tmp");
const manifestPath = path.join(outputDirectory, "capture-manifest.json");
const generatedAt = new Date().toISOString();
const finderProfile = {
  profile_id: "ui-demo-capture-v1",
  interests: "document processing, information retrieval, and evidence dashboards for a public research archive",
  skills: ["Python", "TypeScript", "data visualization"],
  available_time: "semester",
  project_type: "dashboard/visualization",
  data_constraints: "public data preferred",
  preferred_difficulty: "medium",
  preferred_topics: ["document processing", "research discovery"],
  avoid_topics: ["private student data"],
  top_k: 3,
  retrieval_mode: "keyword",
};

if (process.env.TTLAB_CAPTURE_ISOLATED !== "1") {
  throw new Error("Refusing capture: set TTLAB_CAPTURE_ISOLATED=1 only for a disposable database/index runtime.");
}
if (reviewerToken.length < 32) {
  throw new Error("TTLAB_SCREENSHOT_REVIEWER_TOKEN must contain the ephemeral capture-service bearer token (at least 32 characters).");
}
if (baseUrl === apiUrl) {
  throw new Error("The frontend and API must use distinct loopback origins.");
}
assertSafeOutputDirectory(outputDirectory);

const headCommit = git("rev-parse", "HEAD");
const headTree = git("rev-parse", "HEAD^{tree}");
const worktreeStatus = git("status", "--porcelain=v1", "--untracked-files=all");
if (worktreeStatus) {
  throw new Error("Refusing capture from a dirty worktree. Commit the final code/evidence state first.");
}

await prepareEmptyOutputDirectory(outputDirectory);

const report = {
  schema_version: 3,
  status: "running",
  generated_at: generatedAt,
  claim_boundary: "Live implementation evidence only; not a usability study, human review, semantic-entailment result, ethics approval, or permission to redistribute source documents.",
  capture_scope: {
    evaluation: "identity-valid remediation-v2 panel only; historical-v1 state is verified but excluded from the image for print readability",
    finder: "empty public projection pending human editorial and rights approval; technical prototype evidence is excluded",
    admin: "read-only service-actor governance queues without approval authority",
  },
  source: {
    git_commit: headCommit,
    git_tree: headTree,
    worktree_clean: true,
    frontend_origin: baseUrl,
    api_origin: apiUrl,
    isolated_runtime_operator_attestation: true,
  },
  privacy_and_safety: {
    bearer_token_recorded: false,
    browser_storage_required: false,
    tracked_screenshot_directory_written: false,
    record_level_admin_content_captured: false,
    mutation_methods_blocked: ["PATCH", "PUT", "DELETE"],
    post_requests_permitted: false,
    only_allowed_post_path: null,
    manual_privacy_rights_and_print_review_required_before_promotion: true,
  },
  preflight: [],
  governance_queue_accessibility: {},
  finder_public_projection: {
    state: "expected_empty_pending_human_editorial_and_rights_approval",
    expected_searchable_chunks: 0,
    expected_searchable_papers: 0,
    expected_recommendation_posts: 0,
    expected_recommendations: 0,
    technical_prototype_evidence_included: false,
    profile_id: finderProfile.profile_id,
    profile_sha256: canonicalHash(finderProfile),
    profile_sent_to_api: false,
    evaluation_case: false,
    interpretation: "Fixed synthetic form state shown only to demonstrate the fail-closed empty public projection; not a held-out evaluation case, student profile, technical-corpus result, or publication approval.",
  },
  captures: [],
  browser: {
    api_responses: [],
    blocked_requests: [],
    request_failures: [],
    console_errors: [],
    page_errors: [],
  },
  database_state: {},
  errors: [],
};

let browser;
try {
  const root = await apiJson("service_root", "/");
  assert(root.service === "TTLAB Research Intelligence Platform", "Unexpected backend service identity.");
  assert(root.status === "ok", "Backend service root is not healthy.");
  assert(root.security_mode === "local_demo", "Capture backend must use isolated local_demo mode.");
  assert(root.admin_authentication === "bearer_token_required", "Insecure local-demo bypass must be disabled for governance evidence.");

  const health = await apiJson("health", "/health");
  assert(health.status === "ok" && health.service === "ttlab-research-intelligence", "Health endpoint identity mismatch.");

  const readiness = await apiJson("readiness", "/ready");
  assert(readiness.status === "ready", "Backend readiness gate did not pass.");
  assert(readiness.checks?.database === true, "Database readiness did not pass.");
  assert(readiness.checks?.keyword_index?.ready === true, "Authoritative keyword index is not complete and ready.");
  assert(readiness.checks?.feature_hashing_index?.ready === true, "Authoritative feature-hashing index is not complete and ready.");
  const dense = readiness.checks?.dense_index;
  assert(dense?.status === "missing" || dense?.ready === true, "A present dense index is stale, partial, or invalid.");

  const evaluation = await apiJson("evaluation_dashboard", "/api/evaluation/dashboard");
  assertCurrentV2Evaluation(evaluation);

  const capabilities = await apiJson("admin_capabilities", "/api/admin/capabilities", true);
  assert(capabilities.actor?.actor_id === expectedActorId, "Authenticated actor ID does not match the capture-service identity.");
  assert(capabilities.actor?.reviewer_type === "service", "Governance screenshots must use an honest service actor, not a fabricated human reviewer.");
  assert(capabilities.actor?.role === "admin", "Capture-service actor must have the admin role needed to inspect governance queues.");
  assert(capabilities.actor?.local_demo_bypass === false, "Governance capture may not use the insecure local-demo bypass.");
  assert(capabilities.capabilities?.approve_or_reject === false, "The service actor must not be able to issue human approval/rejection states.");

  const authorQueue = await apiJson(
    "author_review_queue",
    "/api/admin/review-queue?item_type=author&review_status=needs_review&limit=200&offset=0",
    true,
  );
  const authorTopicQueue = await apiJson(
    "author_topic_review_queue",
    "/api/admin/review-queue?item_type=author_topic&review_status=needs_review&limit=200&offset=0",
    true,
  );
  assert(Array.isArray(authorQueue.items) && Number.isInteger(authorQueue.total), "Protected author review queue response is malformed.");
  assert(Array.isArray(authorTopicQueue.items) && Number.isInteger(authorTopicQueue.total), "Protected author-topic review queue response is malformed.");
  report.governance_queue_accessibility = {
    record_content_recorded: false,
    author: { status: "accessible", aggregate_total: authorQueue.total, returned_count: authorQueue.items.length },
    author_topic: { status: "accessible", aggregate_total: authorTopicQueue.total, returned_count: authorTopicQueue.items.length },
  };

  const finderDiagnostics = await apiJson("finder_diagnostics", "/api/recommendations/extensions/diagnostics");
  assert(Number(finderDiagnostics.searchable_chunks) === 0, "Public Finder projection unexpectedly contains searchable chunks; capture requires the truthful no-approved-corpus state.");
  assert(Number(finderDiagnostics.searchable_papers) === 0, "Public Finder projection unexpectedly contains searchable papers; capture requires the truthful no-approved-corpus state.");
  assert(finderDiagnostics.scope === "public", "Finder diagnostics do not declare the public projection scope.");
  report.finder_public_projection.diagnostics_sha256 = canonicalHash(finderDiagnostics);
  report.finder_public_projection.observed_searchable_chunks = Number(finderDiagnostics.searchable_chunks);
  report.finder_public_projection.observed_searchable_papers = Number(finderDiagnostics.searchable_papers);

  const overviewBefore = await apiJson("admin_overview_before", "/api/admin/overview", true);
  const stateBefore = persistentStateSummary(overviewBefore, authorQueue, authorTopicQueue);
  report.database_state.before_sha256 = canonicalHash(stateBefore);
  report.database_state.before = stateBefore;

  browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1200 },
    deviceScaleFactor: 1,
    colorScheme: "light",
    reducedMotion: "reduce",
    locale: "en-GB",
    timezoneId: "UTC",
  });

  let finderPostCount = 0;
  const allowedOrigins = new Set([baseUrl, apiUrl]);
  await context.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const method = request.method().toUpperCase();
    if (!allowedOrigins.has(url.origin)) {
      report.browser.blocked_requests.push({ method, origin: url.origin, path: url.pathname, reason: "external_origin" });
      await route.abort("blockedbyclient");
      return;
    }
    if (url.pathname.startsWith("/api/") && url.origin !== apiUrl) {
      report.browser.blocked_requests.push({ method, origin: url.origin, path: url.pathname, reason: "api_origin_mismatch" });
      await route.abort("blockedbyclient");
      return;
    }
    if (["PATCH", "PUT", "DELETE"].includes(method)) {
      report.browser.blocked_requests.push({ method, origin: url.origin, path: url.pathname, reason: "mutation_method" });
      await route.abort("blockedbyclient");
      return;
    }
    if (method === "POST") {
      finderPostCount += 1;
      report.browser.blocked_requests.push({ method, origin: url.origin, path: url.pathname, reason: "post_not_permitted_for_empty_public_projection_capture" });
      await route.abort("blockedbyclient");
      return;
    }
    await route.continue();
  });

  const page = await context.newPage();
  page.on("console", (message) => {
    if (message.type() === "error") report.browser.console_errors.push(redact(message.text()));
  });
  page.on("pageerror", (error) => report.browser.page_errors.push(redact(error.message)));
  page.on("requestfailed", (request) => {
    const url = new URL(request.url());
    report.browser.request_failures.push({
      method: request.method(),
      origin: url.origin,
      path: url.pathname,
      error: redact(request.failure()?.errorText ?? "unknown"),
    });
  });
  page.on("response", (response) => {
    const url = new URL(response.url());
    if (url.origin === apiUrl) {
      report.browser.api_responses.push({ method: response.request().method(), path: url.pathname, status: response.status() });
    }
  });

  await gotoRoute(page, "/evaluation");
  const v2Region = page.getByRole("region", { name: "Peer-review remediation v2 evidence" });
  await v2Region.waitFor({ state: "visible", timeout: 120_000 });
  await page.locator('[data-evaluation-v2-status="current"]').waitFor({ state: "visible", timeout: 120_000 });
  await v2Region.getByText("Identity-validated current AI-reviewed silver package.").waitFor();
  const history = page.locator(".evaluation-history");
  await history.getByRole("heading", { name: "Historical v1 evidence" }).waitFor();
  assert(await history.getByText("historical", { exact: true }).count() === 4, "All four retained v1 cards must remain visibly historical.");
  await assertNoHorizontalOverflow(page, "evaluation");
  const v2Bounds = await v2Region.boundingBox();
  assert(v2Bounds && v2Bounds.height <= v2Bounds.width * 0.9, "Remediation-v2 capture is too tall for readable thesis-width placement.");
  await stageLocatorScreenshot(page, "evaluation-current.png", v2Region);

  await gotoRoute(page, "/extensions");
  await page.getByRole("heading", { name: "Thesis Extension Finder" }).waitFor();
  await page.getByLabel("Interests").fill(finderProfile.interests);
  await page.getByLabel("Skills").fill(finderProfile.skills.join(", "));
  await page.getByLabel("Available time").selectOption(finderProfile.available_time);
  await page.getByLabel("Project type").selectOption(finderProfile.project_type);
  await page.getByLabel("Data constraints").selectOption(finderProfile.data_constraints);
  await page.getByLabel("Preferred difficulty").selectOption(finderProfile.preferred_difficulty);
  await page.getByLabel("Preferred topics").fill(finderProfile.preferred_topics.join(", "));
  await page.getByLabel("Avoid topics").fill(finderProfile.avoid_topics.join(", "));
  await page.getByLabel("Recommendations").selectOption(String(finderProfile.top_k));
  await page.getByLabel("Retrieval mode").selectOption(finderProfile.retrieval_mode);
  await page.getByText("0 searchable chunks", { exact: true }).waitFor({ timeout: 120_000 });
  await page.getByText("0 papers with chunks", { exact: true }).waitFor({ timeout: 120_000 });
  const emptyPublicProjection = page.locator('[data-finder-public-corpus-state="empty"]');
  await emptyPublicProjection.getByText("No papers are approved for public Finder recommendations yet").waitFor({ timeout: 120_000 });
  await emptyPublicProjection.getByText("Reviewer-only technical prototype evidence is not substituted", { exact: false }).waitFor();
  assert(await page.getByRole("button", { name: "Find Thesis Extensions" }).isDisabled(), "Finder action must fail closed when the public projection is empty.");
  await assertNoHorizontalOverflow(page, "finder");
  await stageRangeScreenshot(page, "finder-public-projection-empty.png", [
    page.locator(".finder-panel"),
    page.locator(".search-diagnostics"),
    emptyPublicProjection,
  ]);

  await gotoRoute(page, "/admin");
  await page.getByLabel("Reviewer bearer token").fill(reviewerToken);
  await page.getByRole("button", { name: "Open protected review" }).click();
  const protectedNotice = page.locator("p.notice", { hasText: "Protected reviewer tools" });
  await protectedNotice.waitFor({ state: "visible", timeout: 120_000 });
  const actorNotice = page.locator("p.notice", { hasText: `Acting as ${expectedActorId}` });
  await actorNotice.waitFor({ state: "visible", timeout: 120_000 });
  await page.getByText("This actor cannot approve or reject", { exact: false }).waitFor();
  const adminTabs = page.getByRole("tablist", { name: "Admin review sections" });
  await adminTabs.waitFor({ state: "visible", timeout: 120_000 });
  assert(await page.getByRole("tab", { name: "Overview" }).getAttribute("aria-selected") === "true", "Governance shell capture must remain on the aggregate Overview tab.");
  const adminMetrics = page.locator(".admin-metrics");
  await adminMetrics.waitFor({ state: "visible", timeout: 120_000 });
  await assertNoHorizontalOverflow(page, "admin-governance-shell");
  await stageRangeScreenshot(page, "admin-governance-shell-current.png", [protectedNotice, actorNotice, adminTabs, adminMetrics]);

  const storageState = await page.evaluate(() => ({
    local_storage_keys: Object.keys(window.localStorage),
    session_storage_keys: Object.keys(window.sessionStorage),
  }));
  assert(storageState.local_storage_keys.length === 0, "Capture flow unexpectedly wrote localStorage.");
  assert(storageState.session_storage_keys.length === 0, "Capture flow unexpectedly wrote sessionStorage.");
  report.privacy_and_safety.browser_storage = storageState;

  const overviewAfter = await apiJson("admin_overview_after", "/api/admin/overview", true);
  const authorQueueAfter = await apiJson(
    "author_review_queue_after",
    "/api/admin/review-queue?item_type=author&review_status=needs_review&limit=200&offset=0",
    true,
  );
  const authorTopicQueueAfter = await apiJson(
    "author_topic_review_queue_after",
    "/api/admin/review-queue?item_type=author_topic&review_status=needs_review&limit=200&offset=0",
    true,
  );
  const stateAfter = persistentStateSummary(overviewAfter, authorQueueAfter, authorTopicQueueAfter);
  report.database_state.after_sha256 = canonicalHash(stateAfter);
  report.database_state.after = stateAfter;
  report.database_state.unchanged = report.database_state.before_sha256 === report.database_state.after_sha256;

  assert(report.database_state.unchanged, "Persistent review/recommendation state changed during capture.");
  assert(finderPostCount === 0, `Expected no Finder POST while the public projection is empty, observed ${finderPostCount}.`);
  assert(report.browser.blocked_requests.length === 0, "A disallowed origin or mutation request was attempted.");
  assert(report.browser.request_failures.length === 0, "A browser request failed during capture.");
  assert(report.browser.console_errors.length === 0, "Browser console errors occurred during capture.");
  assert(report.browser.page_errors.length === 0, "Browser page errors occurred during capture.");
  assert(
    report.browser.api_responses.every((response) => response.status >= 200 && response.status < 400),
    "A browser API response was not successful.",
  );

  report.status = "pass";
} catch (error) {
  report.status = "failed";
  report.errors.push(redact(error instanceof Error ? error.message : String(error)));
  process.exitCode = 1;
} finally {
  if (browser) await browser.close();
  await atomicWriteJson(manifestPath, report);
}

if (report.status === "pass") {
  process.stdout.write(`${outputDirectory}\n`);
} else {
  process.stderr.write(`Capture failed; inspect ${manifestPath}\n`);
}

async function apiJson(label, pathname, authenticated = false) {
  const headers = authenticated ? { Authorization: `Bearer ${reviewerToken}` } : {};
  const response = await fetch(`${apiUrl}${pathname}`, { headers });
  const text = await response.text();
  let payload;
  try {
    payload = JSON.parse(text);
  } catch {
    throw new Error(`${label} returned non-JSON HTTP ${response.status}.`);
  }
  report.preflight.push({
    label,
    path: new URL(`${apiUrl}${pathname}`).pathname,
    status: response.status,
    response_sha256: canonicalHash(payload),
  });
  if (!response.ok) throw new Error(`${label} failed with HTTP ${response.status}.`);
  return payload;
}

function assertCurrentV2Evaluation(dashboard) {
  const evidence = dashboard.peer_review_remediation_v2;
  const freshness = dashboard.freshness?.peer_review_remediation_v2;
  assert(dashboard.evaluation_status === "current", "Evaluation dashboard is not current.");
  assert(dashboard.freshness?.status === "current", "Overall evaluation freshness is not current.");
  assert(evidence?.status === "completed", "Remediation-v2 evidence package is not completed.");
  assert(freshness?.status === "current", "Remediation-v2 frozen identities are not current.");
  assert(evidence?.evaluation_id === "peer-review-remediation-v2", "Unexpected remediation-v2 evaluation identity.");
  assert(evidence?.evidence_tier === "ai_silver", "Remediation-v2 evidence is not declared AI-silver.");
  assert(evidence?.reviewer_type === "ai", "Remediation-v2 reviewer type is not AI.");
  assert(evidence?.human_validation === false, "Remediation-v2 incorrectly claims human validation.");
  assert(evidence?.entailment_claimed === false, "Remediation-v2 incorrectly claims semantic entailment.");
  assert(evidence?.technical_scope_only === true, "Remediation-v2 technical-corpus boundary is missing.");
  assert(evidence?.public_projection_exercised === false, "Remediation-v2 unexpectedly claims public-projection evaluation.");
  assert(evidence?.qa_test && evidence?.finder_test && evidence?.topics_test && evidence?.ocr, "One or more v2 result summaries are missing.");
  const topics = evidence.topics_test;
  assert(topics.label_scope === "positive_only_not_exhaustive_closed_world", "V2 topic labels are not declared positive-only/non-exhaustive.");
  assert(Number.isFinite(topics.known_positive_micro?.recall), "V2 known-positive topic recall is missing.");
  assert(Number.isFinite(topics.known_positive_case_coverage_rate), "V2 known-positive topic case coverage is missing.");
  assert(Number.isInteger(topics.unadjudicated_predictions?.count) && topics.unadjudicated_predictions.count >= 0, "V2 unadjudicated topic-prediction count is missing or invalid.");
  assert(Number.isFinite(topics.unadjudicated_predictions?.share), "V2 unadjudicated topic-prediction share is missing.");
  assert(topics.unadjudicated_predictions?.false_positive_interpretation_permitted === false, "V2 topic output permits an invalid false-positive interpretation.");
  assert(topics.micro === undefined && topics.exact_match_rate === undefined, "Capture API still exposes the superseded closed-world topic metric schema.");
  assert(freshness?.freshness_contract === "frozen_inputs_and_outputs_v2", "Unexpected remediation-v2 freshness contract.");
  assert(
    ["code", "corpus", "configuration", "release", "manifest"]
      .every((key) => freshness?.checks?.[key] === "match"),
    "One or more remediation-v2 identity checks do not match.",
  );
  for (const key of ["retrieval", "qa", "extension", "artifact"]) {
    assert(dashboard[key]?.status === "historical", `Retained v1 ${key} evidence is not visibly historical.`);
  }
}

function persistentStateSummary(overview, authorQueue, authorTopicQueue) {
  return {
    papers_total: overview.papers_total,
    total_chunks: overview.total_chunks,
    total_review_events: overview.total_review_events,
    rag_answers: overview.rag_answers,
    thesis_recommendations: overview.thesis_recommendations,
    paper_artifacts: overview.paper_artifacts,
    author_needs_review_total: authorQueue.total,
    author_topic_needs_review_total: authorTopicQueue.total,
    review_event_integrity_status: overview.review_event_integrity?.status,
    database_integrity_status: overview.database_integrity?.status,
  };
}

async function gotoRoute(page, route) {
  const response = await page.goto(`${baseUrl}${route}`, { waitUntil: "domcontentloaded", timeout: 120_000 });
  assert(response?.status() === 200, `${route} returned HTTP ${response?.status() ?? "unknown"}.`);
  await page.locator("main").waitFor({ state: "visible", timeout: 120_000 });
  await page.evaluate(() => document.fonts.ready);
}

async function assertNoHorizontalOverflow(page, label) {
  const dimensions = await page.evaluate(() => ({
    scroll_width: document.documentElement.scrollWidth,
    client_width: document.documentElement.clientWidth,
  }));
  assert(dimensions.scroll_width <= dimensions.client_width + 1, `${label} has horizontal overflow.`);
}

async function stageLocatorScreenshot(page, filename, locator) {
  await locator.waitFor({ state: "visible", timeout: 120_000 });
  const target = path.join(outputDirectory, filename);
  await refuseExistingFile(target);
  const box = await locator.boundingBox();
  assert(box && box.width > 0 && box.height > 0, `Cannot resolve screenshot bounds for ${filename}.`);
  await locator.screenshot({ path: target, animations: "disabled", caret: "hide" });
  await recordCapture(filename, target, box);
}

async function stageRangeScreenshot(page, filename, locators) {
  const boxes = [];
  for (const locator of locators) {
    await locator.waitFor({ state: "visible", timeout: 120_000 });
    const box = await locator.boundingBox();
    assert(box && box.width > 0 && box.height > 0, `Cannot resolve one screenshot range for ${filename}.`);
    boxes.push(box);
  }
  const left = Math.max(0, Math.min(...boxes.map((box) => box.x)) - 2);
  const top = Math.max(0, Math.min(...boxes.map((box) => box.y)) - 2);
  const right = Math.max(...boxes.map((box) => box.x + box.width)) + 2;
  const bottom = Math.max(...boxes.map((box) => box.y + box.height)) + 2;
  const clip = { x: left, y: top, width: right - left, height: bottom - top };
  const target = path.join(outputDirectory, filename);
  await refuseExistingFile(target);
  await page.screenshot({ path: target, clip, animations: "disabled", caret: "hide" });
  await recordCapture(filename, target, clip);
}

async function recordCapture(filename, target, bounds) {
  const stat = await fs.stat(target);
  report.captures.push({
    filename,
    sha256: sha256(await fs.readFile(target)),
    bytes: stat.size,
    width_css_px: Math.round(bounds.width),
    height_css_px: Math.round(bounds.height),
  });
}

function localOrigin(raw, label) {
  let url;
  try {
    url = new URL(raw);
  } catch {
    throw new Error(`${label} must be a valid URL.`);
  }
  const loopback = url.hostname === "127.0.0.1" || url.hostname === "localhost" || url.hostname === "[::1]";
  if (url.protocol !== "http:" || !loopback || (url.pathname !== "/" && url.pathname !== "")) {
    throw new Error(`${label} must be an http loopback origin without a path.`);
  }
  return url.origin;
}

function assertSafeOutputDirectory(candidate) {
  const repositoryPathIsSafe = !isWithin(candidate, repository) || isWithin(candidate, repositoryTempDirectory);
  if (!repositoryPathIsSafe || candidate === repository || isWithin(candidate, trackedScreenshotDirectory)) {
    throw new Error("Refusing capture output outside the ignored repository tmp directory (or an external temporary directory).");
  }
}

function isWithin(candidate, parent) {
  const relative = path.relative(parent, candidate);
  return relative === "" || (!relative.startsWith("..") && !path.isAbsolute(relative));
}

async function prepareEmptyOutputDirectory(directory) {
  await fs.mkdir(directory, { recursive: true });
  const entries = await fs.readdir(directory);
  if (entries.length) {
    throw new Error(`Refusing to overwrite non-empty capture staging directory: ${directory}`);
  }
}

async function refuseExistingFile(target) {
  try {
    await fs.access(target);
    throw new Error(`Refusing to overwrite staged capture: ${target}`);
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
  }
}

async function atomicWriteJson(target, value) {
  const temporary = `${target}.${process.pid}.tmp`;
  await fs.writeFile(temporary, `${JSON.stringify(value, null, 2)}\n`, { encoding: "utf8", flag: "wx" });
  await fs.rename(temporary, target);
}

function git(...args) {
  return execFileSync("git", args, { cwd: repository, encoding: "utf8" }).trim();
}

function canonicalHash(value) {
  return sha256(JSON.stringify(sortKeys(value)));
}

function sortKeys(value) {
  if (Array.isArray(value)) return value.map(sortKeys);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.keys(value).sort().map((key) => [key, sortKeys(value[key])]));
  }
  return value;
}

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

function redact(value) {
  return String(value).replaceAll(reviewerToken, "[REDACTED]");
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}
