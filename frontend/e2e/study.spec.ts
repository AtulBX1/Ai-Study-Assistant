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

const quizQuestion = {
  id: 41,
  question: "Which term is supported by this page?",
  type: "multiple_choice",
  options: ["Alpha", "Beta", "Gamma", "Delta"],
  explanation: "The source page defines Alpha.",
  evidence: "Alpha is described in the document.",
  source_chunk_id: 5,
  page: 6,
  difficulty: "medium",
  engine: "classic",
  topic: "Unit II",
  source_page_url: "/documents/4/pages/6",
};

function apiPath(url: URL, pathname: string): boolean {
  return url.hostname === "localhost" && url.port === "8000" && url.pathname === pathname;
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
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(session) }),
  );
  await page.route("**/auth/refresh", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(session) }),
  );
  await page.route("**/auth/logout", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "logged_out" }) }),
  );
}

async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(user.email);
  await page.getByLabel("Password", { exact: true }).fill("a-strong-password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Library", exact: true })).toBeVisible();
}

async function mockDocuments(page: Page) {
  await page.route((url) => apiPath(url, "/documents"), async (route: Route) => {
    if (route.request().method() !== "GET") return route.fallback();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([{
        id: 4,
        title: "Course.pdf",
        status: "ready",
        progress: 100,
        error_message: null,
        page_count: 8,
        language: "en",
        created_at: "2026-01-01T00:00:00Z",
        is_private: false,
      }]),
    });
  });
}

test("creates a partial quiz, takes it, and opens the cited source", async ({ page }) => {
  await mockApi(page);
  await mockDocuments(page);
  await page.route((url) => apiPath(url, "/quizzes"), async (route: Route) => {
    if (route.request().method() === "POST") {
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({
          id: 31,
          title: "Course.pdf practice",
          engine: "classic",
          questions: 1,
          report: { accepted: 1, requested_engine: "llm", fallback_reason: "rate_limited" },
        }),
      });
      return;
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  });
  await page.route((url) => apiPath(url, "/quizzes/31"), (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: 31,
        title: "Course.pdf practice",
        engine: "classic",
        report: { accepted: 1, fallback_reason: "rate_limited", requested_engine: "llm" },
        questions: [quizQuestion],
      }),
    }),
  );
  await page.route((url) => apiPath(url, "/quizzes/31/attempts"), (route) =>
    route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({ quiz_id: 31, attempt_id: 91 }) }),
  );
  await page.route((url) => apiPath(url, "/quizzes/31/attempts/91/submit"), async (route) => {
    const body = route.request().postDataJSON() as { answers: Array<{ question_id: number; answer: string }> };
    expect(body.answers).toEqual([{ question_id: 41, answer: "Alpha" }]);
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        attempt_id: 91,
        score: 1,
        correct: 1,
        total: 1,
        topic_breakdown: { "Unit II": { correct: 1, total: 1 } },
        results: [{
          question_id: 41,
          is_correct: true,
          correct_answer: "Alpha",
          explanation: "The source page defines Alpha.",
          source_page_url: "/documents/4/pages/6",
        }],
      }),
    });
  });
  await page.route((url) => apiPath(url, "/quizzes/31/results/91"), (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        attempt_id: 91,
        score: 1,
        topic_breakdown: { "Unit II": { correct: 1, total: 1 } },
        answers: [{
          question_id: 41,
          is_correct: true,
          explanation: "The source page defines Alpha.",
          source_page_url: "/documents/4/pages/6",
        }],
      }),
    }),
  );

  await login(page);
  await page.goto("/quizzes/new");
  await page.getByLabel("Quiz title").fill("Course.pdf practice");
  await page.getByRole("button", { name: "Generate quiz" }).click();
  await expect(page.getByText(/Generated 1 of 10 questions: the AI provider was rate limited/)).toBeVisible();
  await page.getByRole("link", { name: "Accept quiz" }).click();
  await page.getByRole("link", { name: "Start quiz" }).click();
  await expect(page.getByText(quizQuestion.question)).toBeVisible();
  await page.getByLabel("Alpha").check();
  await page.getByRole("button", { name: "Submit quiz" }).click();
  await page.getByRole("button", { name: "Confirm submission" }).click();
  await expect(page.getByRole("heading", { name: "Quiz results" })).toBeVisible();
  await expect(page.getByRole("link", { name: "View source on page 6" }))
    .toHaveAttribute("href", "/chat/4?page=6");
});

test("retakes only missed questions returned for the completed attempt", async ({ page }) => {
  await mockApi(page);
  await page.route((url) => apiPath(url, "/quizzes/31"), (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: 31,
        title: "Course quiz",
        engine: "classic",
        report: {},
        questions: [quizQuestion, { ...quizQuestion, id: 42, question: "A question answered incorrectly?" }],
      }),
    }),
  );
  await page.route((url) => apiPath(url, "/quizzes/31/results/90"), (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        attempt_id: 90,
        score: 0.5,
        topic_breakdown: { "Unit II": { correct: 1, total: 2 } },
        answers: [
          { question_id: 41, is_correct: true, explanation: "Right.", source_page_url: "/documents/4/pages/6" },
          { question_id: 42, is_correct: false, explanation: "Review this.", source_page_url: "/documents/4/pages/6" },
        ],
      }),
    }),
  );
  await page.route((url) => apiPath(url, "/quizzes/31/retake"), async (route) => {
    expect(new URL(route.request().url()).searchParams.get("attempt_id")).toBe("90");
    await route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify({
        id: 32,
        source_quiz_id: 31,
        title: "Course quiz — retake",
        questions: [{ ...quizQuestion, id: 142, question: "A question answered incorrectly?" }],
      }),
    });
  });
  await page.route((url) => apiPath(url, "/quizzes/32"), (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: 32,
        title: "Course quiz — retake",
        engine: "classic",
        report: {},
        questions: [{ ...quizQuestion, id: 142, question: "A question answered incorrectly?" }],
      }),
    }),
  );
  await page.route((url) => apiPath(url, "/quizzes/32/attempts"), (route) =>
    route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({ quiz_id: 32, attempt_id: 93 }) }),
  );

  await login(page);
  await page.goto("/quizzes/31/results/90");
  await page.getByRole("button", { name: "Retake only the questions I missed" }).click();
  await expect(page).toHaveURL(/\/quizzes\/32$/);
  await page.getByRole("link", { name: "Start quiz" }).click();
  await expect(page.getByText("A question answered incorrectly?")).toBeVisible();
  await expect(page.getByText(quizQuestion.question)).toHaveCount(0);
});

test("flips and rates three flashcards with keyboard ratings", async ({ page }) => {
  await mockApi(page);
  const ratings: string[] = [];
  await page.route((url) => apiPath(url, "/study/flashcards/due"), (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([1, 2, 3].map((id) => ({
        id,
        front: `Prompt ${id}`,
        back: `Answer ${id}`,
        source_page: id + 2,
        document_id: 4,
        deck: "Course.pdf",
        due_at: "2026-11-08T00:00:00Z",
        interval: 0,
        repetitions: 0,
        suspended: false,
      }))),
    }),
  );
  await page.route((url) => url.hostname === "localhost" && url.port === "8000" && /^\/study\/flashcards\/\d+\/review$/.test(url.pathname), async (route) => {
    const body = route.request().postDataJSON() as { rating: string };
    ratings.push(body.rating);
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ rating: body.rating, card: { interval: 2 } }),
    });
  });
  await login(page);
  await page.goto("/flashcards/review");

  for (const [index, key] of ["1", "2", "3"].entries()) {
    const cardNumber = index + 1;
    await expect(page.getByText(`Prompt ${cardNumber}`)).toBeVisible();
    await page.keyboard.press("Space");
    await expect(page.getByText(`Answer ${cardNumber}`)).toBeVisible();
    await expect(page.getByRole("link", { name: `Open source page ${cardNumber + 2}` }))
      .toHaveAttribute("href", `/chat/4?page=${cardNumber + 2}`);
    await page.keyboard.press(key);
  }
  await expect(page.getByText("Session complete")).toBeVisible();
  expect(ratings).toEqual(["Again", "Hard", "Good"]);
});
