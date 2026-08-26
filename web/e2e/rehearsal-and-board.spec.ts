import { expect, test } from "@playwright/test";

/**
 * Walks the assignment's required flow end to end against seeded data (backend/scripts/seed.py):
 * open the seeded job, inspect a rehearsal run that failed a persona, then check the board for a
 * real (non-simulated) completed call and read its answers. See playwright.config.ts for the
 * prerequisites this needs running first.
 */
test("rehearsal failure and board answers, from the seeded job", async ({ page }) => {
  await page.goto("/");

  await page.getByRole("link", { name: /Delivery Rider/i }).click();
  await expect(page).toHaveURL(/\/jobs\/.+\/compile/);

  await page.getByRole("link", { name: "Rehearsal" }).click();
  await expect(page).toHaveURL(/\/jobs\/.+\/rehearsal/);

  // v3 (the newest, cleanest version) is selected by default — switch to v1, the run with real
  // failures, to exercise the failure-inspection path.
  await page.getByRole("combobox").click();
  await page.getByRole("option", { name: /^v1 · ENGLISH · compiled$/ }).click();
  await expect(page.getByText(/^\d+$/).first()).toBeVisible(); // composite score renders

  await page.getByText("CODE_SWITCHER", { exact: true }).click();

  await expect(page.getByText("Extracted vs. ground truth")).toBeVisible();
  const yearsRidingRow = page.getByRole("row", { name: /years_riding/ });
  await expect(yearsRidingRow).toBeVisible();
  await expect(yearsRidingRow).toContainText("6"); // expected
  await expect(yearsRidingRow).toContainText("3"); // what v1 actually extracted — the mismatch

  await page.getByRole("link", { name: "Board" }).click();
  await expect(page).toHaveURL(/\/jobs\/.+\/board/);

  await page.getByText("Pilot Candidate (EN)", { exact: true }).click();
  const drawer = page.locator('[data-slot="drawer-popup"]');
  await expect(drawer.getByText("Result", { exact: true })).toBeVisible();
  await expect(drawer.getByText("Immediately")).toBeVisible(); // earliest_start, from the real result
  await expect(drawer.getByText("Simulated")).toHaveCount(0); // this row is real, never simulated
});
