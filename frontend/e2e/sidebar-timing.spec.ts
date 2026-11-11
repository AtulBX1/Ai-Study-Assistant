import { expect, test, type Page } from "@playwright/test";

const user = { id: 8, email: "student@example.test", full_name: "Student", role: "student", public_handle: "learner-1234", show_on_leaderboards: true };
const session = { access_token: "mock-access-token", refresh_token: "mock-refresh-token", token_type: "bearer", user };
const routes = ["/library", "/chat", "/quizzes", "/flashcards", "/syllabus", "/study-tools", "/test-library", "/progress", "/lab", "/benchmarks", "/settings"];

test("measures first and second sidebar visit latency in the production build", async ({ page }) => {
  await page.route("http://localhost:8000/**", (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await page.route("**/auth/login", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(session) }));
  await page.route("**/auth/refresh", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(session) }));
  await page.goto("/login"); await page.getByLabel("Email").fill(user.email); await page.getByLabel("Password", { exact: true }).fill("password"); await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/library$/);
  const measurements: Record<string, [number, number]> = {};
  for (const destination of routes) {
    const values: number[] = [];
    for (let visit = 0; visit < 2; visit += 1) {
      await page.goto("/library");
      const link = page.locator(`aside a[href="${destination}"]`);
      const start = performance.now();
      await link.click();
      await page.waitForURL((url) => url.pathname === destination);
      await page.locator("main").first().waitFor({ state: "visible" });
      values.push(Math.round(performance.now() - start));
    }
    measurements[destination] = [values[0], values[1]];
  }
  console.log(`SIDEBAR_TIMINGS ${JSON.stringify(measurements)}`);
});
