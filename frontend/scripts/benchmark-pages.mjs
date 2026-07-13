import { spawn } from "node:child_process";
import process from "node:process";
import { chromium } from "playwright";

const args = new Map();
for (let index = 2; index < process.argv.length; index += 2) {
  args.set(process.argv[index], process.argv[index + 1]);
}
const repetitions = Number.parseInt(args.get("--repetitions") ?? "1", 10);
const temperature = args.get("--temperature") ?? "cold";
const port = Number.parseInt(args.get("--port") ?? "5173", 10);
const baseUrl = `http://127.0.0.1:${port}`;
const routes = ["/", "/papers", "/search", "/ask", "/extensions", "/explorer", "/evaluation", "/admin"];

if (!Number.isInteger(repetitions) || repetitions < 1) throw new Error("--repetitions must be positive");
if (!["cold", "warm"].includes(temperature)) throw new Error("--temperature must be cold or warm");

const preview = spawn("npm", ["run", "preview", "--", "--host", "127.0.0.1", "--port", String(port)], {
  cwd: new URL("..", import.meta.url),
  stdio: ["ignore", "ignore", "pipe"],
  shell: false,
});
let previewError = "";
preview.stderr.on("data", (chunk) => { previewError += chunk.toString(); });

async function waitForPreview() {
  for (let attempt = 0; attempt < 80; attempt += 1) {
    try {
      const response = await fetch(baseUrl);
      if (response.ok) return;
    } catch { /* retry */ }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`Vite preview did not start: ${previewError.slice(-500)}`);
}

async function measureRoutes(page, repetition) {
  const rows = [];
  for (const route of routes) {
    const started = performance.now();
    try {
      const response = await page.goto(`${baseUrl}${route}`, { waitUntil: "networkidle", timeout: 30_000 });
      await page.locator("main").waitFor({ state: "visible", timeout: 10_000 });
      rows.push({
        repetition,
        route,
        status: "ok",
        http_status: response?.status() ?? null,
        elapsed_ms: performance.now() - started,
      });
    } catch (error) {
      rows.push({
        repetition,
        route,
        status: "failed",
        elapsed_ms: performance.now() - started,
        error: String(error).slice(0, 500),
      });
    }
  }
  return rows;
}

let browser;
try {
  await waitForPreview();
  const rows = [];
  if (temperature === "warm") {
    browser = await chromium.launch({ headless: true });
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await context.newPage();
    for (let repetition = 1; repetition <= repetitions; repetition += 1) {
      rows.push(...await measureRoutes(page, repetition));
    }
    await context.close();
  } else {
    for (let repetition = 1; repetition <= repetitions; repetition += 1) {
      browser = await chromium.launch({ headless: true });
      const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
      const page = await context.newPage();
      rows.push(...await measureRoutes(page, repetition));
      await context.close();
      await browser.close();
      browser = undefined;
    }
  }
  process.stdout.write(`${JSON.stringify({ temperature, repetitions, routes, rows })}\n`);
} finally {
  if (browser) await browser.close();
  preview.kill("SIGTERM");
}
