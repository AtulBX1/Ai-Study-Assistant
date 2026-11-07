import { expect, test, type Page } from "@playwright/test";

const user = {
  id: 8,
  email: "student@example.test",
  full_name: "Student",
  role: "student",
  public_handle: "learner-1234",
  show_on_leaderboards: true,
};
const authSession = {
  access_token: "mock-access-token",
  refresh_token: "mock-refresh-token",
  token_type: "bearer",
  user,
};
const documentRecord = {
  id: 42,
  title: "Example PDF",
  status: "ready",
  progress: 100,
  error_message: null,
  page_count: 3,
  language: "English",
  created_at: "2026-01-01T00:00:00Z",
  is_private: true,
};

async function mockApi(page: Page) {
  await page.route("http://localhost:8000/**", (route) =>
    route.fulfill({
      status: 404,
      contentType: "application/json",
      body: JSON.stringify({ detail: "No mock for this API request." }),
    }),
  );
  await page.route("**/auth/login", (route) =>
    route.fulfill({ status: 200, json: authSession }),
  );
  await page.route("**/auth/refresh", (route) =>
    route.fulfill({ status: 200, json: authSession }),
  );
  await page.route("**/documents**", (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/documents") {
      return route.fulfill({ status: 200, json: [documentRecord] });
    }
    if (url.pathname === "/documents/42") {
      return route.fulfill({ status: 200, json: documentRecord });
    }
    if (url.pathname === "/documents/42/download") {
      return route.fulfill({
        status: 200,
        contentType: "application/pdf",
        body: "mock pdf bytes",
      });
    }
    if (url.pathname === "/documents/42/pages/2/image") {
      return route.fulfill({
        status: 200,
        contentType: "image/png",
        body: Buffer.from(
          "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/n8sAAAAASUVORK5CYII=",
          "base64",
        ),
      });
    }
    return route.fulfill({ status: 200, json: [documentRecord] });
  });
  await page.route("**/study/documents/42/glossary**", (route) =>
    route.fulfill({
      status: 200,
      json: {
        items: [{ term: "attention", pages: [1] }],
        total: 1,
        limit: 100,
        offset: 0,
      },
    }),
  );
  await page.route("**/chat/sessions", (route) =>
    route.fulfill({
      status: 201,
      json: {
        id: 91,
        title: "Question",
        owner_id: 8,
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
      },
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

test("asks about a PDF and follows the answer citation to its page", async ({ page }) => {
  await mockApi(page);
  await page.route("**/chat/sessions/91/messages", (route) =>
    route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body:
        `data: ${JSON.stringify({ token: "Attention connects the concepts. " })}\n\n` +
        `data: ${JSON.stringify({ token: "[Example PDF, p.2]" })}\n\n` +
        `data: ${JSON.stringify({ done: true, provider: "answered by: mock-provider" })}\n\n`,
    }),
  );
  await login(page);
  await page.goto("/chat/42");
  await page.getByRole("textbox", { name: "Ask a question about this document" }).fill(
    "What does attention do?",
  );
  await page.getByRole("button", { name: "Send question" }).click();

  await expect(page.getByText("Answered by: mock-provider")).toBeVisible();
  await page.getByRole("button", { name: "Go to Example PDF, page 2" }).click();
  await expect(page.getByRole("spinbutton", { name: "Current page" })).toHaveValue("2");
});

test("stops a response after its first streamed token", async ({ page }) => {
  await mockApi(page);
  await page.addInitScript(() => {
    const originalFetch = window.fetch.bind(window);
    window.fetch = async (input, init) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (url.includes("/chat/sessions/91/messages")) {
        const encoder = new TextEncoder();
        let timer: number | undefined;
        const body = new ReadableStream<Uint8Array>({
          start(controller) {
            controller.enqueue(
              encoder.encode(`data: ${JSON.stringify({ token: "First partial token." })}\n\n`),
            );
            timer = window.setTimeout(() => {
              controller.enqueue(
                encoder.encode(`data: ${JSON.stringify({ token: " late token" })}\n\n`),
              );
              controller.close();
            }, 2000);
          },
          cancel() {
            if (timer !== undefined) window.clearTimeout(timer);
          },
        });
        init?.signal?.addEventListener(
          "abort",
          () => {
            if (timer !== undefined) window.clearTimeout(timer);
          },
          { once: true },
        );
        return new Response(body, {
          headers: { "Content-Type": "text/event-stream" },
        });
      }
      return originalFetch(input, init);
    };
  });
  await login(page);
  await page.goto("/chat/42");
  await page.getByRole("textbox", { name: "Ask a question about this document" }).fill(
    "Explain this document",
  );
  await page.getByRole("button", { name: "Send question" }).click();
  await expect(page.getByText("First partial token.")).toBeVisible();
  await page.getByRole("button", { name: "Stop response" }).click();
  await expect(page.getByText("Response stopped.")).toBeVisible();
  await expect(page.getByText("late token")).toHaveCount(0);
});
