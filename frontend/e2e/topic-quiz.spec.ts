import { expect, test, type Page, type Route } from "@playwright/test";

const user = { id: 8, email: "student@example.test", full_name: "Student", role: "student", public_handle: "learner-1234", show_on_leaderboards: true };
const session = { access_token: "mock-access-token", refresh_token: "mock-refresh-token", token_type: "bearer", user };
const match = (url: URL, path: string) => url.hostname === "localhost" && url.port === "8000" && url.pathname === path;

test("builds a quiz scoped to a syllabus topic", async ({ page }) => {
  await page.route("http://localhost:8000/**", (route) => route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: "No mock for this API request." }) }));
  await page.route("**/auth/login", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(session) }));
  await page.route("**/auth/refresh", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(session) }));
  await page.route((url) => match(url, "/documents"), (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([{ id: 4, title: "Course.pdf", status: "ready", progress: 100, error_message: null, page_count: 8, language: "en", created_at: "2026-01-01T00:00:00Z", is_private: false }]) }));
  await page.route((url) => match(url, "/syllabi"), (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([{ id: 2, title: "Networks" }]) }));
  await page.route((url) => match(url, "/syllabi/2"), (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ id: 2, title: "Networks", tree: [{ id: 7, title: "Routing", order: 0, keywords: [], sub_topics: [], children: [] }] }) }));
  let payload: Record<string, unknown> | undefined;
  await page.route((url) => match(url, "/quizzes"), async (route: Route) => {
    if (route.request().method() === "POST") { payload = route.request().postDataJSON() as Record<string, unknown>; await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({ id: 31, title: "Routing", engine: "offline", questions: 1, report: { accepted: 1 } }) }); }
    else await route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  });
  await page.route((url) => match(url, "/quizzes/31"), (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ id: 31, title: "Routing", engine: "offline", report: {}, questions: [] }) }));
  await page.goto("/login"); await page.getByLabel("Email").fill(user.email); await page.getByLabel("Password", { exact: true }).fill("a-strong-password"); await page.getByRole("button", { name: "Sign in" }).click();
  await page.goto("/quizzes/new?syllabusId=2&topicId=7&title=Routing");
  await page.getByLabel("Document", { exact: true }).selectOption("4");
  await page.getByRole("button", { name: "Generate quiz" }).click();
  await expect.poll(() => payload).toMatchObject({ syllabus_id: 2, topic_ids: [7], question_types: ["multiple_choice", "true_false", "fill_in_the_blank", "short_answer"] });
});
