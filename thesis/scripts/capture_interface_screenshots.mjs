#!/usr/bin/env node
/** Capture the two manuscript UI figures from a running local frontend. */

import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const repository = path.resolve(here, "../..");
const requireFromFrontend = createRequire(path.join(repository, "frontend/package.json"));
const { chromium } = requireFromFrontend("@playwright/test");

const baseUrl = process.env.TTLAB_SCREENSHOT_URL ?? "http://127.0.0.1:4173";
const outputDirectory = path.join(repository, "thesis/figures/screenshots");

const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({
    viewport: { width: 1440, height: 1200 },
    deviceScaleFactor: 1,
    colorScheme: "light",
    reducedMotion: "reduce",
  });
  const consoleErrors = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });

  await page.goto(`${baseUrl}/evaluation`, { waitUntil: "domcontentloaded" });
  await page.locator(".evaluation-grid").waitFor({ timeout: 120_000 });
  await page.locator(".evaluation-grid").screenshot({
    path: path.join(outputDirectory, "evaluation-current.png"),
    animations: "disabled",
  });

  await page.goto(`${baseUrl}/ask`, { waitUntil: "domcontentloaded" });
  await page.getByLabel("Question").fill(
    "What did the source paper automate, and how does this platform extend that work?",
  );
  await page.getByLabel("Retrieval mode").selectOption("keyword");
  await page.getByLabel("Top K").selectOption("5");
  await page.getByLabel("Answer provider").selectOption("offline_extractive");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  await page.getByText(/answered with \d+ citations/i).waitFor({ timeout: 120_000 });
  await page.getByText("719 searchable chunks").waitFor();
  await page.locator(".citation-card").first().waitFor();
  await page.locator(".toast-stack, .toast-region").evaluateAll((nodes) => {
    for (const node of nodes) node.style.display = "none";
  });
  await page.locator(".answer-layout").screenshot({
    path: path.join(outputDirectory, "ask-answer.png"),
    animations: "disabled",
  });

  if (consoleErrors.length) {
    throw new Error(`Browser console errors: ${consoleErrors.join(" | ")}`);
  }
  process.stdout.write(`${outputDirectory}\n`);
} finally {
  await browser.close();
}
