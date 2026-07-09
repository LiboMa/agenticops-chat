import { test, expect } from "@playwright/test";

// Manual/optional UI gate. Requires: backend on :8000 with seeded resources
// and a completed build, frontend served. Run: npx playwright test galaxy.spec.ts
test("galaxy overview renders, drills down, panel opens and closes", async ({ page }) => {
  await page.goto("/app/galaxy");
  await expect(page.getByText("Galaxy")).toBeVisible();

  // Overview shows group/account nodes.
  const node = page.locator(".react-flow__node").first();
  await expect(node).toBeVisible();

  // Double-click a group to drill down.
  await node.dblclick();
  await expect(page.getByText("Back to overview")).toBeVisible();

  // Single-click a node opens the detail panel; ESC closes it.
  await page.locator(".react-flow__node").first().click();
  await expect(page.locator("text=Health")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.locator("text=Health")).toBeHidden();

  // Provenance: at least one dashed (llm) edge is present in the SVG.
  const dashed = page.locator('.react-flow__edge path[stroke-dasharray]');
  await expect(dashed.first()).toBeVisible();
});
