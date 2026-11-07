import { expect, test, type Page, type Route } from "@playwright/test";

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

type MockDocument = {
  id: number;
  title: string;
  status: string;
  progress: number;
  error_message: string | null;
  page_count: number;
  language: string | null;
  created_at: string;
};

function documentRecord(
  status: string,
  errorMessage: string | null = null,
): MockDocument {
  return {
    id: 71,
    title: "Course.pdf",
    status,
    progress: status === "ready" || status === "failed" ? 100 : 30,
    error_message: errorMessage,
    page_count: 2,
    language: "en",
    created_at: "2026-01-01T00:00:00Z",
  };
}

async function mockApi(page: Page) {
  await page.route("http://localhost:8000/**", (route) =>
    route.fulfill({
      status: 404,
      contentType: "application/json",
      body: JSON.stringify({ detail: "No mock for this API request." }),
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

async function mockLibrary(page: Page, initial: MockDocument[]) {
  let documents = [...initial];
  await page.route(
    (url) => url.pathname === "/documents",
    async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(documents),
      });
    },
  );
  await page.route(
    (url) => url.pathname === "/documents/upload",
    async (route: Route) => {
      if (route.request().method() !== "POST") return route.fallback();
      documents = [documentRecord("queued"), ...documents];
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify(documents[0]),
      });
    },
  );
  await page.route(
    (url) => url.pathname === "/documents/71/events",
    (route) =>
      route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: `data: ${JSON.stringify({
          document_id: 71,
          status: "ready",
          progress: 100,
          error_message: null,
        })}\n\n`,
      }),
  );
  await page.route(
    (url) => url.pathname === "/documents/71",
    async (route: Route) => {
      if (route.request().method() === "DELETE") {
        documents = documents.filter((item) => item.id !== 71);
        await route.fulfill({ status: 204 });
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(documents[0] ?? documentRecord("ready")),
      });
    },
  );
}

async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(user.email);
  await page.getByLabel("Password", { exact: true }).fill("a-strong-password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Library", exact: true })).toBeVisible();
}

test("uploads a PDF and observes it become ready", async ({ page }) => {
  await mockApi(page);
  await mockLibrary(page, []);
  await login(page);

  await page.locator('input[type="file"]').setInputFiles({
    name: "Course.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.from("%PDF-1.4\n/Type /Page\n%%EOF"),
  });
  await page.getByLabel("Private").uncheck();
  await page.getByRole("button", { name: "Upload PDF" }).click();

  await expect(page.getByRole("link", { name: "Course.pdf" })).toBeVisible();
  await expect(page.getByText("Ready", { exact: true })).toBeVisible();
});

test("deletes a document only after confirmation", async ({ page }) => {
  await mockApi(page);
  await mockLibrary(page, [documentRecord("ready")]);
  await login(page);

  await page.locator('summary[aria-label="Actions for Course.pdf"]').click();
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await expect(page.getByText(/also removes its chunks/)).toBeVisible();
  await page.getByRole("button", { name: "Delete document" }).click();

  await expect(page.getByText("Your library is empty")).toBeVisible();
});

test("shows the backend error for a failed document", async ({ page }) => {
  await mockApi(page);
  await mockLibrary(page, [
    documentRecord("failed", "Text extraction failed."),
  ]);
  await login(page);

  await expect(page.getByText("Failed", { exact: true })).toBeVisible();
  await expect(page.getByText("Text extraction failed.").first()).toBeVisible();
});
