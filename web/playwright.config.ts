import { defineConfig, devices } from "@playwright/test";

/**
 * Runs against seeded data (`make seed` — see backend/scripts/seed.py), not a live LLM/Hunar
 * call: the job, versions, rehearsal runs, and board rows this spec asserts on all come from that
 * frozen fixture, so the suite is reproducible with no API key.
 *
 * Prerequisites (not orchestrated here — this only starts the Next.js dev server):
 *   1. Backend + Postgres running (`make up`, or `uvicorn` against a local Postgres).
 *   2. `make seed` run at least once against that database.
 *   3. web/.env.local pointing NEXT_PUBLIC_API_BASE_URL at that backend.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  reporter: "html",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "npm run dev",
    url: "http://localhost:3000",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
