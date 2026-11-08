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

const evidence = {
  chunk_id: 7,
  document_id: 42,
  document_title: "Example PDF",
  page: 2,
  text: "Attention connects evidence and context.",
  section: "Attention",
  retrieval_score: 0.71,
  rerank_score: 0.86,
  score_components: { lexical: 0.71 },
};

function minimalPdf(): Buffer {
  const content = "BT\n/F1 18 Tf\n72 700 Td\n(Attention connects evidence and context.) Tj\nET";
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R 5 0 R 7 0 R] /Count 3 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 6 0 R >>",
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 8 0 R >>",
    "<< /Length 0 >>\nstream\n\nendstream",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 10 0 R >>",
    `<< /Length ${content.length} >>\nstream\n${content}\nendstream`,
    "<< /Length 0 >>\nstream\n\nendstream",
    "<< /Length 0 >>\nstream\n\nendstream",
  ];
  let pdf = "%PDF-1.4\n";
  const offsets = [0];
  objects.forEach((object, index) => {
    offsets.push(Buffer.byteLength(pdf, "ascii"));
    pdf += `${index + 1} 0 obj\n${object}\nendobj\n`;
  });
  const xrefOffset = Buffer.byteLength(pdf, "ascii");
  pdf += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  for (const offset of offsets.slice(1)) {
    pdf += `${String(offset).padStart(10, "0")} 00000 n \n`;
  }
  pdf += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xrefOffset}\n%%EOF`;
  return Buffer.from(pdf, "ascii");
}

type ChatState = {
  feedback: { feedback: "thumbs_up" | "thumbs_down"; reason: string | null } | null;
  sessions: boolean;
};

function messageDetail(state: ChatState) {
  return {
    id: 91,
    title: "What does attention do?",
    owner_id: 8,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    messages: [
      {
        id: 100,
        session_id: 91,
        role: "user",
        content: "What does attention do?",
        citations: [],
        unsupported_sentences: [],
        explanation: {},
        created_at: "2026-01-01T00:00:00Z",
      },
      {
        id: 101,
        session_id: 91,
        role: "assistant",
        content: "Attention connects evidence and context. [Example PDF, p.2]",
        citations: [{ document_title: "Example PDF", page: 2, chunk_id: 7 }],
        grounding_score: 0.86,
        unsupported_sentences: [],
        explanation: {
          chunks: [evidence],
          answer_sentences: ["Attention connects evidence and context."],
          provider: "answered by: mock-provider",
          mode: "normal",
          latency_ms: 42.5,
        },
        provider: "answered by: mock-provider",
        latency_ms: 42.5,
        feedback: state.feedback?.feedback ?? null,
        feedback_reason: state.feedback?.reason ?? null,
        created_at: "2026-01-01T00:00:01Z",
      },
    ],
  };
}

async function mockApi(page: Page, state: ChatState = { feedback: null, sessions: true }) {
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
        body: minimalPdf(),
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
  await page.route("**/chat/sessions", (route) => {
    if (route.request().method() === "GET") {
      return route.fulfill({
        status: 200,
        json: state.sessions ? [{
          id: 91,
          title: "What does attention do?",
          owner_id: 8,
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
        }] : [],
      });
    }
    return route.fulfill({
      status: 201,
      json: {
        id: 91,
        title: "What does attention do?",
        owner_id: 8,
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
      },
    });
  });
  await page.route("**/chat/sessions/91", (route) => {
    if (route.request().method() === "DELETE") {
      state.sessions = false;
      return route.fulfill({ status: 204 });
    }
    return route.fulfill({ status: 200, json: messageDetail(state) });
  });
  await page.route("**/chat/messages/101/feedback", async (route) => {
    const body = route.request().postDataJSON() as {
      feedback: "thumbs_up" | "thumbs_down";
      reason?: string;
    };
    state.feedback = { feedback: body.feedback, reason: body.reason ?? null };
    return route.fulfill({
      status: 200,
      json: { message_id: 101, feedback: body.feedback, reason: body.reason ?? null },
    });
  });
}

async function mockAnswer(page: Page) {
  await page.route("**/chat/sessions/91/messages", (route) =>
    route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body:
        `data: ${JSON.stringify({ token: "Attention connects evidence and context. " })}\n\n` +
        `data: ${JSON.stringify({ token: "[Example PDF, p.2]" })}\n\n` +
        `data: ${JSON.stringify({
          done: true,
          provider: "answered by: mock-provider",
          citations: [{ document_title: "Example PDF", page: 2, chunk_id: 7 }],
          grounding_score: 0.86,
          unsupported_sentences: [],
          explanation: {
            chunks: [evidence],
            answer_sentences: ["Attention connects evidence and context."],
            provider: "answered by: mock-provider",
            mode: "normal",
            latency_ms: 42.5,
          },
          message_id: 101,
          latency_ms: 42.5,
        })}\n\n`,
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
  await mockAnswer(page);
  await login(page);
  await page.goto("/chat/42");
  await page.getByRole("textbox", { name: "Ask a question about this document" }).fill(
    "What does attention do?",
  );
  await page.getByRole("button", { name: "Send question" }).click();

  await expect(page.getByText("Answered by: mock-provider")).toBeVisible();
  await expect(page.getByLabel("Grounding score 0.86: Well supported")).toBeVisible();
  await page.getByRole("button", { name: "Go to Example PDF, page 2" }).click();
  await expect(page.getByRole("spinbutton", { name: "Current page" })).toHaveValue("2");
  await expect(page.locator('[data-page="2"] .textLayer')).toContainText(
    "Attention connects evidence and context.",
  );
  await expect(page.locator('[data-page="2"] [aria-hidden="true"] span').first()).toBeVisible();
});

test("opens the explanation drawer and jumps to a retrieved chunk", async ({ page }) => {
  await mockApi(page);
  await mockAnswer(page);
  await login(page);
  await page.goto("/chat/42");
  await page.getByRole("textbox", { name: "Ask a question about this document" }).fill(
    "What does attention do?",
  );
  await page.getByRole("button", { name: "Send question" }).click();
  await expect(page.getByText("Answered by: mock-provider")).toBeVisible();

  await page.getByRole("button", { name: "Why this answer" }).click();
  await expect(page.getByRole("dialog", { name: "Why this answer" })).toContainText(
    "Retrieval score",
  );
  await expect(page.getByRole("dialog", { name: "Why this answer" })).toContainText("Rerank score");
  await page.getByRole("button", { name: "Go to page 2 and highlight" }).click();
  await expect(page.getByRole("spinbutton", { name: "Current page" })).toHaveValue("2");
  await expect(page.locator('[data-page="2"] [aria-hidden="true"] span').first()).toBeVisible();
});

test("submits thumbs-down feedback and reloads the stored state", async ({ page }) => {
  const state: ChatState = { feedback: null, sessions: true };
  await mockApi(page, state);
  await mockAnswer(page);
  await login(page);
  await page.goto("/chat/42");
  await page.getByRole("textbox", { name: "Ask a question about this document" }).fill(
    "What does attention do?",
  );
  await page.getByRole("button", { name: "Send question" }).click();
  await expect(page.getByRole("button", { name: "Not helpful answer" })).toBeVisible();

  await page.getByRole("button", { name: "Not helpful answer" }).click();
  await page.getByLabel("Optional reason").fill("The evidence needs more detail.");
  await page.getByRole("button", { name: "Send feedback" }).click();
  await expect(page.getByText("Feedback saved: The evidence needs more detail.")).toBeVisible();
  expect(state.feedback).toEqual({
    feedback: "thumbs_down",
    reason: "The evidence needs more detail.",
  });

  await page.reload();
  await page.getByRole("button", { name: "History" }).click();
  await page.getByRole("button", { name: "Open chat: What does attention do?" }).click();
  await expect(page.getByText("Feedback saved: The evidence needs more detail.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Not helpful answer" })).toBeDisabled();
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
