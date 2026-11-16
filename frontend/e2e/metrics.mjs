// Phase 4 browser check: the dashboard shows the hand-computed totals of the seeded
// dataset (see e2e/seed_metrics.py) and renders the charts.
//   ADMIN_TOKEN=... node e2e/metrics.mjs <project id> [--shots dir]
import fs from "node:fs";

import { chromium, devices } from "playwright";

const args = process.argv.slice(2);
const shotsAt = args.indexOf("--shots");
const SHOTS = shotsAt >= 0 ? args.splice(shotsAt, 2)[1] : "e2e/screenshots";
const [projectId] = args;
const BASE = process.env.BASE_URL ?? "http://localhost:5180";
const TOKEN = process.env.ADMIN_TOKEN;
if (!projectId || !TOKEN) {
  console.error("Usage: ADMIN_TOKEN=... node e2e/metrics.mjs <project id> [--shots dir]");
  process.exit(2);
}
fs.mkdirSync(SHOTS, { recursive: true });
const step = (msg) => console.log(`✓ ${msg}`);
const expectText = async (locator, expected, what) => {
  const text = (await locator.innerText()).replace(/\s+/g, " ").trim();
  for (const e of expected) if (!text.includes(e)) throw new Error(`${what}: expected "${e}" in "${text}"`);
};

const browser = await chromium.launch();
try {
  const page = await browser.newPage({ viewport: { width: 1360, height: 1000 } });
  await page.addInitScript((t) => localStorage.setItem("agentscope.adminToken", t), TOKEN);
  await page.goto(`${BASE}/p/${projectId}/runs`);
  await page.getByRole("link", { name: "metrics" }).click();
  await page.getByTestId("tile-Runs").waitFor();

  const tile = (label) => page.getByTestId(`tile-${label}`);
  await expectText(tile("Runs"), ["6"], "Runs");
  await expectText(tile("Error rate"), ["33%", "2 failed"], "Error rate");
  await expectText(tile("Latency p50"), ["300 ms"], "p50");
  await expectText(tile("Latency p95"), ["880 ms", "p99 976 ms"], "p95");
  await expectText(tile("Tokens"), ["8,300", "6,500 in", "1,800 out"], "Tokens");
  await expectText(tile("Cost"), ["$0.035", "1 unpriced"], "Cost");
  step("stat tiles match: 6 runs, 33% failed, p50 300 ms, p95 880 ms, 8,300 tokens, $0.035");

  const table = page.getByTestId("model-table");
  await expectText(table.locator("tr", { hasText: "claude-sonnet-5-5" }), ["2", "4,000", "1,500", "$0.023"], "sonnet row");
  await expectText(table.locator("tr", { hasText: "claude-opus-5-5" }), ["1", "2,000", "200", "$0.012"], "opus row");
  await expectText(table.locator("tr", { hasText: "gemini-3.8-flash" }), ["500", "100", "unpriced"], "gemini row");
  step("usage table matches per model (sonnet $0.023, opus $0.012, gemini unpriced)");

  await page.getByText("Show the time series as a table").click();
  const series = page.getByTestId("series-table");
  const rows = await series.locator("tbody tr").allInnerTexts();
  const busy = rows.map((r) => r.split("\t").map((c) => c.trim())).filter((c) => c[1] !== "0");
  const cells = busy.map((c) => c.slice(1));
  const expected = [
    ["3", "1", "200 ms", "290 ms", "$0.023"],
    ["3", "1", "700 ms", "970 ms", "$0.012"],
  ];
  if (JSON.stringify(cells) !== JSON.stringify(expected)) {
    throw new Error(`series rows ${JSON.stringify(cells)} != ${JSON.stringify(expected)}`);
  }
  step(`daily series match: ${busy.map((c) => `${c[0]}: ${c.slice(1).join(" / ")}`).join(" | ")}`);

  for (const title of ["Runs per day", "Latency", "Cost by model"]) {
    const marks = page.getByRole("region", { name: title }).locator(".recharts-rectangle, .recharts-line-curve");
    if ((await marks.count()) === 0) throw new Error(`chart "${title}" drew no marks`);
  }
  await page.getByRole("region", { name: "Cost by model" }).getByText("$0.023").waitFor();
  step("all three charts render marks; cost bars are labelled");

  await page.getByRole("region", { name: "Runs per day" }).locator(".recharts-rectangle").first().hover();
  await page.locator(".recharts-tooltip-wrapper").getByText("Succeeded").waitFor();
  step("hovering a column shows a tooltip");
  await page.screenshot({ path: `${SHOTS}/metrics.png`, fullPage: true });

  await page.getByRole("button", { name: "Last 24 hours" }).click();
  await tile("Runs").getByText("0", { exact: true }).waitFor();
  if (!page.url().includes("range=24h")) throw new Error("range should be in the URL");
  step("switching to the last 24 hours shows 0 runs (data is 2-3 days old)");

  const mobile = await browser.newPage({ ...devices["iPhone 13"] });
  await mobile.addInitScript((t) => localStorage.setItem("agentscope.adminToken", t), TOKEN);
  await mobile.goto(`${BASE}/p/${projectId}/metrics`);
  await mobile.getByTestId("tile-Runs").waitFor();
  await mobile.screenshot({ path: `${SHOTS}/metrics-mobile.png`, fullPage: true });
  step("phone layout renders");
  console.log(`\nAll steps passed. Screenshots in ${SHOTS}/`);
} catch (err) {
  console.error(`\n✗ ${err.message}`);
  process.exitCode = 1;
} finally {
  await browser.close();
}
