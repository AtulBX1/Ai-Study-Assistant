import { expect, test, type Page } from "@playwright/test";

const user = {
  id: 8,
  email: "student@example.test",
  full_name: "Student",
  role: "student",
  public_handle: "learner-1234",
  show_on_leaderboards: true,
};

const session = {
  access_token: "mock-access-token",
  refresh_token: "mock-refresh-token",
  token_type: "bearer",
  user,
};

async function mockApi(page: Page) {
  await page.route("http://localhost:8000/**", (route) =>
    route.fulfill({
      status: 404,
      contentType: "application/json",
      body: JSON.stringify({ detail: "No mock for this API request." }),
    }),
  );
  await page.route("**/auth/register", (route) =>
    route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify(session),
    }),
  );
  await page.route("**/auth/login", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(session),
    }),
  );
  await page.route("**/auth/refresh", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(session),
    }),
  );
  await page.route("**/auth/logout", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ status: "logged_out" }),
    }),
  );
}

async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(user.email);
  await page.getByLabel("Password", { exact: true }).fill("a-strong-password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Library", exact: true })).toBeVisible();
}

test("registers and lands on the library placeholder", async ({ page }) => {
  await mockApi(page);
  await page.goto("/register");
  await page.getByLabel("Full name").fill(user.full_name);
  await page.getByLabel("Email").fill(user.email);
  await page.getByLabel("Password", { exact: true }).fill("a-strong-password");
  await page.getByLabel("Confirm password").fill("a-strong-password");
  await page.getByRole("button", { name: "Create account" }).click();

  await expect(page.getByRole("heading", { name: "Library", exact: true })).toBeVisible();
  await expect(page.getByText("Library is coming soon")).toBeVisible();
});

test("redirects protected routes to login and returns after login", async ({ page }) => {
  await mockApi(page);
  await page.goto("/settings");
  await expect(page.getByRole("heading", { name: "Welcome back" })).toBeVisible();
  await expect(page).toHaveURL(/next=%2Fsettings/);
  await page.getByLabel("Email").fill(user.email);
  await page.getByLabel("Password", { exact: true }).fill("a-strong-password");
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page.getByRole("heading", { name: "Settings", exact: true })).toBeVisible();
  await expect(page.getByText(user.email)).toBeVisible();
});

test("logs out and returns to login", async ({ page }) => {
  await mockApi(page);
  await login(page);
  await page.getByText(user.public_handle).click();
  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page.getByRole("heading", { name: "Welcome back" })).toBeVisible();
});

test("toggles dark mode and persists the selection", async ({ page }) => {
  await mockApi(page);
  await login(page);
  await page.getByRole("link", { name: "Settings" }).click();
  await page.getByRole("button", { name: "Switch to dark mode" }).click();
  await expect(page.locator("html")).toHaveClass(/dark/);
  await expect(page).toHaveURL(/settings$/);
  await page.reload();
  await expect(page.locator("html")).toHaveClass(/dark/);
  await expect(page.getByRole("button", { name: "Switch to light mode" })).toBeVisible();
});
