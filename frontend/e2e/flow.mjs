// Phase 3 browser check: an SDK trace shows up with the right nesting, and clicking a
// span shows its details.
//
// Needs the backend + frontend running and a trace sent by e2e/send_trace.py. Usage:
//   ADMIN_TOKEN=... node e2e/flow.mjs "<project name>" "<run name>" [--shots dir]
import fs from "node:fs";

import { chromium, devices } from "playwright";

const args = process.argv.slice(2);
const shotsAt = args.indexOf("--shots");
const SHOTS = shotsAt >= 0 ? args.splice(shotsAt, 2)[1] : "e2e/screenshots";
const [projectName, runName] = args;
const BASE = process.env.BASE_URL ?? "http://localhost:5180";
const TOKEN = process.env.ADMIN_TOKEN;
if (!projectName || !runName || !TOKEN) {
  console.error('Usage: ADMIN_TOKEN=... node e2e/flow.mjs "<project>" "<run>" [--shots dir]');
  process.exit(2);
}
fs.mkdirSync(SHOTS, { recursive: true });
const step = (msg) => console.log(`✓ ${msg}`);
const fail = (msg) => {
  throw new Error(msg);
};

// Expected tree, as [name, depth], from e2e/send_trace.py.
const EXPECTED = [
  ["agent", 0],
  ["plan", 1],
  ["search_docs", 1],
  ["answer", 1],
  ["llm-call", 2],
  ["format", 2],
];

const browser = await chromium.launch();
try {
  const page = await browser.newPage({ viewport: { width: 1360, height: 860 } });

  await page.goto(`${BASE}/login`);
  await page.getByLabel("Admin token").fill("wrong-token");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByRole("alert").filter({ hasText: "not valid" }).waitFor();
  step("a wrong admin token is refused");
  await page.getByLabel("Admin token").fill(TOKEN);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL(/\/p\/[0-9a-f-]+\/runs/);

  await page.getByLabel("Project").selectOption({ label: projectName });
  await page.getByRole("link", { name: runName }).waitFor();
  step(`runs list for "${projectName}" shows "${runName}"`);
  await page.getByLabel("Search runs by name").fill("no-such-run");
  await page.getByRole("button", { name: "Search" }).click();
  await page.getByText("No runs match these filters.").waitFor();
  await page.getByLabel("Search runs by name").fill(runName.slice(0, 6).toUpperCase());
  await page.getByRole("button", { name: "Search" }).click();
  await page.getByRole("link", { name: runName }).waitFor();
  step("name search filters the list (case-insensitive)");
  await page.screenshot({ path: `${SHOTS}/1-runs.png` });

  await page.getByRole("link", { name: runName }).click();
  await page.getByTestId("span-tree").waitFor();
  const rows = page.getByTestId("span-row");
  const actual = [];
  for (let i = 0; i < (await rows.count()); i++) {
    const row = rows.nth(i);
    actual.push([(await row.locator("span.truncate").innerText()).trim(), Number(await row.getAttribute("data-depth"))]);
  }
  if (JSON.stringify(actual) !== JSON.stringify(EXPECTED)) {
    fail(`tree mismatch:\n  got      ${JSON.stringify(actual)}\n  expected ${JSON.stringify(EXPECTED)}`);
  }
  step(`span tree nests correctly: ${actual.map(([n, d]) => `${"  ".repeat(d)}${n}`).join(" | ")}`);
  await page.screenshot({ path: `${SHOTS}/2-run.png` });

  await page.getByRole("button", { name: "Collapse answer" }).click();
  if ((await rows.count()) !== 4) fail("collapsing 'answer' should hide its 2 children");
  await page.getByRole("button", { name: "Expand answer" }).click();
  if ((await rows.count()) !== 6) fail("expanding 'answer' should show its children again");
  step("collapse / expand works");

  await page.getByTestId("span-row").filter({ hasText: "llm-call" }).locator("button").last().click();
  const details = page.getByTestId("details");
  await details.getByTestId("details-name").filter({ hasText: "llm-call" }).waitFor();
  const text = await details.innerText();
  for (const expected of ["gemini-3.8-flash", "Input tokens", "120", "Output tokens", "Reset it from Settings"]) {
    if (!text.includes(expected)) fail(`details panel is missing "${expected}"`);
  }
  if (!page.url().includes("span=")) fail("selected span should be in the URL");
  step("clicking llm-call shows its model, tokens, input and output");

  await page.getByTestId("span-row").filter({ hasText: "format" }).locator("button").last().click();
  await details.getByText("ValueError: bad markdown").waitFor();
  step("an error span shows its error");
  await page.screenshot({ path: `${SHOTS}/3-span-details.png` });

  await page.reload();
  await details.getByTestId("details-name").filter({ hasText: "format" }).waitFor();
  step("reloading keeps the selected span (URL state)");

  const mobile = await browser.newPage({ ...devices["iPhone 13"] });
  await mobile.addInitScript((t) => localStorage.setItem("agentscope.adminToken", t), TOKEN);
  await mobile.goto(page.url());
  await mobile.getByTestId("details-name").filter({ hasText: "format" }).waitFor();
  await mobile.screenshot({ path: `${SHOTS}/4-mobile.png`, fullPage: true });
  step("phone layout renders the run");

  console.log(`\nAll steps passed. Screenshots in ${SHOTS}/`);
} catch (err) {
  console.error(`\n✗ ${err.message}`);
  process.exitCode = 1;
} finally {
  await browser.close();
}
