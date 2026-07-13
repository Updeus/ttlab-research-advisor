#!/usr/bin/env node
/** Capture live desktop/mobile evidence for every primary application route. */

import fs from "node:fs/promises";
import path from "node:path";
import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";


const here = path.dirname(fileURLToPath(import.meta.url));
const repository = path.resolve(here, "../..");
const baseUrl = process.env.TTLAB_SCREENSHOT_URL ?? "http://127.0.0.1:4173";
const apiUrl = process.env.TTLAB_API_URL ?? "http://127.0.0.1:8000";
const outputDirectory = path.resolve(
  process.env.TTLAB_ROUTE_CAPTURE_DIR ?? path.join(repository, "tmp/final-route-captures"),
);
const baseRoutes = [
  ["dashboard", "/"],
  ["papers", "/papers"],
  ["search", "/search"],
  ["ask", "/ask"],
  ["extensions", "/extensions"],
  ["explorer", "/explorer"],
  ["evaluation", "/evaluation"],
  ["admin", "/admin"],
];
const viewports = [
  ["desktop", { width: 1440, height: 1000 }],
  ["mobile", { width: 360, height: 900 }],
];


await fs.mkdir(outputDirectory, { recursive: true });
const browser = await chromium.launch({ headless: true });
const report = {
  schema_version: 1,
  generated_at: new Date().toISOString(),
  base_url: baseUrl,
  api_url: apiUrl,
  viewports: Object.fromEntries(viewports),
  captures: [],
  discovered_routes: [],
  errors: [],
};

try {
  const routes = [...baseRoutes, ...(await discoverDetailRoutes(browser))];
  report.discovered_routes = routes.slice(baseRoutes.length).map(([name, route]) => ({ name, route }));
  for (const [viewportName, viewport] of viewports) {
    for (const [name, route] of routes) {
      const page = await browser.newPage({
        viewport,
        colorScheme: "light",
        reducedMotion: "reduce",
      });
      const consoleErrors = [];
      const pageErrors = [];
      page.on("console", (message) => {
        if (message.type() === "error") consoleErrors.push(message.text());
      });
      page.on("pageerror", (error) => pageErrors.push(error.message));
      try {
        const response = await page.goto(`${baseUrl}${route}`, {
          waitUntil: "domcontentloaded",
          timeout: 120_000,
        });
        await page.locator("main").waitFor({ state: "visible", timeout: 120_000 });
        await page.waitForLoadState("networkidle", { timeout: 120_000 });
        const dimensions = await page.evaluate(() => ({
          scroll_width: document.documentElement.scrollWidth,
          client_width: document.documentElement.clientWidth,
          scroll_height: document.documentElement.scrollHeight,
          client_height: document.documentElement.clientHeight,
        }));
        const filename = `${viewportName}-${name}.png`;
        const screenshotPath = path.join(outputDirectory, filename);
        await page.screenshot({
          path: screenshotPath,
          fullPage: true,
          animations: "disabled",
        });
        const capture = {
          name,
          route,
          viewport: viewportName,
          filename,
          sha256: createHash("sha256").update(await fs.readFile(screenshotPath)).digest("hex"),
          status: response?.status() ?? null,
          title: await page.title(),
          dimensions,
          horizontal_overflow: dimensions.scroll_width > dimensions.client_width + 1,
          console_errors: consoleErrors,
          page_errors: pageErrors,
        };
        report.captures.push(capture);
        if (capture.status !== 200 || capture.horizontal_overflow || consoleErrors.length || pageErrors.length) {
          report.errors.push(capture);
        }
      } catch (error) {
        report.errors.push({ name, route, viewport: viewportName, error: String(error) });
      } finally {
        await page.close();
      }
    }
  }
} finally {
  await browser.close();
}

await fs.writeFile(
  path.join(outputDirectory, "manifest.json"),
  `${JSON.stringify(report, null, 2)}\n`,
  "utf8",
);
process.stdout.write(`${outputDirectory}\n`);
if (report.errors.length) process.exitCode = 1;


async function discoverDetailRoutes(browserInstance) {
  const page = await browserInstance.newPage({
    viewport: { width: 1440, height: 1000 },
    colorScheme: "light",
    reducedMotion: "reduce",
  });
  const discovered = [];
  try {
    for (const [sourceRoute, selector, name] of [
      ["/papers", 'a[href^="/papers/"]', "paper-detail"],
    ]) {
      await page.goto(`${baseUrl}${sourceRoute}`, { waitUntil: "domcontentloaded", timeout: 120_000 });
      await page.locator("main").waitFor({ state: "visible", timeout: 120_000 });
      await page.waitForLoadState("networkidle", { timeout: 120_000 });
      const locator = page.locator(selector).first();
      try {
        await locator.waitFor({ state: "attached", timeout: 30_000 });
      } catch {
        continue;
      }
      if ((await locator.count()) > 0) {
        const route = await locator.getAttribute("href");
        if (route) discovered.push([name, route]);
      }
    }

    for (const [endpoint, field, name, prefix] of [
      ["/api/topics?limit=1&offset=0", "topic_id", "topic-detail", "/explorer/topics/"],
      ["/api/authors?limit=1&offset=0", "author_id", "author-detail", "/explorer/authors/"],
    ]) {
      const response = await fetch(`${apiUrl}${endpoint}`);
      if (!response.ok) continue;
      const payload = await response.json();
      const identifier = payload?.items?.[0]?.[field];
      if (identifier !== undefined && identifier !== null) {
        discovered.push([name, `${prefix}${encodeURIComponent(String(identifier))}`]);
      }
    }
  } finally {
    await page.close();
  }
  return discovered;
}
