// Drives the Understudy web app against the seeded demo data and records a video of the
// walkthrough: home -> job -> compile -> rehearsal (v1 -> v2 -> v3) -> candidates -> board ->
// answers drawer for a real pilot call and a simulated candidate. Read-only: never clicks
// "Run", "Source candidates", or "Call selected" — no LLM calls, no outbound calls triggered.
const { chromium } = require("playwright");
const path = require("path");

const SCRATCH = "C:/Users/Bonbloc/AppData/Local/Temp/claude/d--OneDrive---bonbloc-com-proj-hunai/d0070a8d-a940-4ab2-ae02-a6e119c2ddec/scratchpad";
const VIDEO_DIR = path.join(SCRATCH, "video");
const BASE_URL = "http://127.0.0.1:3000";

function pause(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function main() {
  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: { width: 1360, height: 860 },
    recordVideo: { dir: VIDEO_DIR, size: { width: 1360, height: 860 } },
  });
  const page = await context.newPage();
  const consoleErrors = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(msg.text());
  });

  // -------- Home: pick the seeded job --------
  await page.goto(BASE_URL, { waitUntil: "domcontentloaded" });
  await page.getByRole("heading", { name: "Jobs" }).waitFor();
  const jobLink = page.locator('a[href^="/jobs/"]').first();
  await jobLink.waitFor();
  await pause(600);
  await jobLink.click();

  // -------- Compile tab (lands here after clicking a job) --------
  await page.getByRole("link", { name: "Rehearsal" }).waitFor();
  await pause(1200);

  // -------- Rehearsal: walk v1 -> v2 -> v3, then inspect a persona case --------
  await page.getByRole("link", { name: "Rehearsal" }).click();
  await page.locator('button:has-text("v1")').first().waitFor({ timeout: 15000 });
  await pause(800);

  for (const v of ["v1", "v2", "v3"]) {
    const btn = page.locator(`button:has-text("${v}")`).first();
    await btn.click();
    await page.locator("text=LLM calls").waitFor();
    await pause(1000);
  }

  // Inspect the CODE_SWITCHER case on v3 — the one whose extraction the v3 patch actually fixed.
  const personaBtn = page.locator('button:has-text("CODE_SWITCHER")').first();
  if (await personaBtn.count()) {
    await personaBtn.click();
    await pause(1200);
  }

  // -------- Candidates --------
  await page.getByRole("link", { name: "Candidates" }).click();
  await page.locator("table").waitFor({ timeout: 15000 });
  await pause(1400);

  // -------- Board --------
  await page.getByRole("link", { name: "Board" }).click();
  await page.getByText("Dialled").waitFor({ timeout: 15000 });
  await pause(1000);

  // Real pilot call (is_simulated=False) — has a recording_url and a genuine Hunar result.
  const pilotBtn = page.locator('button:has-text("Pilot Candidate (EN)")').first();
  await pilotBtn.waitFor({ timeout: 15000 });
  await pilotBtn.click();
  await page.getByText("Result", { exact: true }).waitFor();
  await pause(1800);

  // Show the raw JSON for this answer set.
  const rawBtn = page.getByRole("button", { name: /raw json/i });
  if (await rawBtn.count()) {
    await rawBtn.click();
    await pause(1200);
  }

  // Close, then open a simulated candidate to contrast the SimulatedBadge.
  await page.keyboard.press("Escape");
  await pause(500);
  const simulatedBtn = page.locator("button.status-hatch").first();
  if (await simulatedBtn.count()) {
    await simulatedBtn.click();
    await page.getByText("Result", { exact: true }).waitFor();
    await pause(1600);
  }

  console.log("console errors seen:", JSON.stringify(consoleErrors));

  await context.close();
  await browser.close();

  const fs = require("fs");
  const files = fs.readdirSync(VIDEO_DIR).filter((f) => f.endsWith(".webm"));
  console.log("VIDEO_FILE:", files[files.length - 1]);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
