import { expect, test } from "@playwright/test";

test("every visible desk control accepts interaction without client errors", async ({ page }) => {
  const clientErrors: string[] = [];
  page.on("pageerror", (error) => clientErrors.push(error.message));

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "From dread to delivery." })).toBeVisible();

  await page.getByRole("button", { name: "Refresh" }).click();
  await expect(page.getByText(/Connected to FastAPI/)).toBeVisible();
  await page.getByRole("button", { name: "New project" }).click();
  await expect(page.getByRole("dialog", { name: "Create project" })).toBeVisible();
  await page.getByRole("button", { name: "Cancel" }).click();
  await expect(page.getByRole("dialog", { name: "Create project" })).toBeHidden();

  await expect(page.getByRole("button", { name: "New episode" })).toBeVisible();

  for (const filter of ["all", "review", "running", "failed", "final", "published"]) {
    await page.getByRole("button", { name: filter, exact: true }).click();
    await expect(page.getByRole("button", { name: filter, exact: true })).toHaveClass(/active/);
  }

  expect(clientErrors).toEqual([]);
});
