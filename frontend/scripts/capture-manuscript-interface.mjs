import { chromium } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const repository = path.resolve(here, "../..");
const output = path.join(repository, "thesis/figures/screenshots/evaluation-current.png");
const baseUrl = process.env.TTLAB_SCREENSHOT_URL ?? "http://127.0.0.1:4173";

const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({
    viewport: { width: 1440, height: 1100 },
    deviceScaleFactor: 1,
    colorScheme: "light",
    reducedMotion: "reduce",
  });
  const consoleErrors = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  await page.goto(`${baseUrl}/evaluation`, { waitUntil: "networkidle" });
  await page.getByText("AI-reviewed silver offline evaluation").waitFor();
  await page.locator(".evaluation-grid").screenshot({ path: output, animations: "disabled" });
  if (consoleErrors.length) {
    throw new Error(`Browser console errors: ${consoleErrors.join(" | ")}`);
  }
  process.stdout.write(`${output}\n`);
} finally {
  await browser.close();
}
