// Phase 6 browser check: two eval runs of one dataset show per-item scores and compare.
// Run two experiments first (evals/: --version v1, then --version v2-concise). Usage:
//   ADMIN_TOKEN=... node e2e/evals.mjs "<project name>" [--shots dir]
import fs from "node:fs";

import { chromium } from "playwright";

const args = process.argv.slice(2);
const shotsAt = args.indexOf("--shots");
const SHOTS = shotsAt >= 0 ? args.splice(shotsAt, 2)[1] : "e2e/screenshots";
const [projectName] = args;
const BASE = process.env.BASE_URL ?? "http://localhost:5180";
const TOKEN = process.env.ADMIN_TOKEN;
if (!projectName || !TOKEN) {
  console.error('Usage: ADMIN_TOKEN=... node e2e/evals.mjs "<project name>" [--shots dir]');
  process.exit(2);
}
fs.mkdirSync(SHOTS, { recursive: true });
const step = (msg) => console.log(`✓ ${msg}`);

const browser = await chromium.launch();
try {
  const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } });
  await page.addInitScript((t) => localStorage.setItem("agentscope.adminToken", t), TOKEN);
  await page.goto(BASE);
  await page.getByLabel("Project").selectOption({ label: projectName });
  await page.getByRole("link", { name: "evals" }).click();
  const rows = page.getByTestId("eval-run-row");
  await rows.first().waitFor();
  if ((await rows.count()) < 2) throw new Error("need at least two eval runs");
  const [newest, previous] = [await rows.nth(0).innerText(), await rows.nth(1).innerText()];
  if (!/%/.test(newest) || !/%/.test(previous)) throw new Error("the two newest runs have no scores");
  step(`eval runs listed with scores (${await rows.count()} runs)`);
  await page.screenshot({ path: `${SHOTS}/evals-list.png` });

  await rows.first().getByRole("link").click();
  const results = page.getByTestId("eval-result");
  await results.first().waitFor();
  const first = (await results.first().innerText()).toLowerCase(); // labels are CSS-uppercased
  for (const part of ["answer", "expected", "trace →", "%"]) {
    if (!first.includes(part)) throw new Error(`result card is missing "${part}"`);
  }
  step(`run detail shows ${await results.count()} items with answer, expected, scores and a trace link`);
  await page.goBack();

  await rows.nth(0).locator("input[type=checkbox]").check();
  await rows.nth(1).locator("input[type=checkbox]").check();
  await page.getByRole("button", { name: "Compare 2/2" }).click();
  const items = page.getByTestId("compare-row");
  await items.first().waitFor();
  const summary = await page.getByTestId("compare-summary").innerText();
  for (const part of ["Overall score", "Pass rate", "judge", "B − A"]) {
    if (!summary.includes(part)) throw new Error(`summary is missing "${part}"`);
  }
  const chart = page.getByRole("region", { name: "Scores by scorer" });
  await chart.locator(".recharts-rectangle").first().waitFor(); // bars draw after an animation
  step(`compare view: summary deltas, scorer chart and ${await items.count()} item rows`);
  await page.screenshot({ path: `${SHOTS}/eval-compare.png`, fullPage: true });
  console.log(`\nAll steps passed. Screenshots in ${SHOTS}/`);
} catch (err) {
  console.error(`\n✗ ${err.message}`);
  process.exitCode = 1;
} finally {
  await browser.close();
}
