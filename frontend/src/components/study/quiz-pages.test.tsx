import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  QuizAttemptPage,
  QuizBuilderPage,
  QuizListPage,
  QuizResultsPage,
} from "@/components/study/quiz-pages";

const mocks = vi.hoisted(() => ({
  push: vi.fn(),
  listDocuments: vi.fn(),
  listQuizzes: vi.fn(),
  getQuiz: vi.fn(),
  createQuiz: vi.fn(),
  getQuizResults: vi.fn(),
  startQuizAttempt: vi.fn(),
  submitQuizAttempt: vi.fn(),
  retakeMissedQuestions: vi.fn(),
  downloadExamPaper: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mocks.push }),
}));

vi.mock("@/lib/documents", () => ({
  listDocuments: mocks.listDocuments,
}));

vi.mock("@/lib/quiz-study", () => ({
  listQuizzes: mocks.listQuizzes,
  getQuiz: mocks.getQuiz,
  createQuiz: mocks.createQuiz,
  getQuizResults: mocks.getQuizResults,
  startQuizAttempt: mocks.startQuizAttempt,
  submitQuizAttempt: mocks.submitQuizAttempt,
  retakeMissedQuestions: mocks.retakeMissedQuestions,
  downloadExamPaper: mocks.downloadExamPaper,
  reportSummary: (report: Record<string, unknown>, requested?: number, actual?: number, counts?: Record<string, number>) =>
    report.fallback_reason === "rate_limited"
      ? `Generated ${actual} of ${requested} questions: the AI provider was rate limited. Question engines: Offline (classic) ${counts?.classic}.`
      : null,
  engineLabel: (engine: string, provider?: string | null) =>
    engine === "classic" ? "Offline (classic)" : provider ? `AI provider: ${provider}` : "AI provider",
}));

const question = {
  id: 11,
  question: "Which concept is stored in this source?",
  type: "multiple_choice",
  options: ["Term A", "Term B", "Term C", "Term D"],
  explanation: "Grounded explanation.",
  page: 6,
  difficulty: "medium",
  engine: "classic",
  provider: null,
  topic: "Unit II",
  sourcePageUrl: "/documents/4/pages/6",
  correct_answer: "Secret correct answer",
};

const quiz = {
  id: 3,
  title: "Unit II review",
  engine: "classic",
  report: { accepted: 1 },
  questions: [question],
};

beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  mocks.listDocuments.mockResolvedValue([]);
  mocks.listQuizzes.mockResolvedValue([]);
  mocks.getQuiz.mockResolvedValue(quiz);
  mocks.getQuizResults.mockResolvedValue({
    attemptId: 55,
    score: 0.5,
    correct: 1,
    total: 2,
    topicBreakdown: { "Unit II": { correct: 1, total: 2 } },
    answers: [{
      questionId: 11,
      isCorrect: false,
      correctAnswer: "Term A",
      explanation: "Grounded explanation.",
      sourcePageUrl: "/documents/4/pages/6",
      answer: "Term B",
    }],
  });
  mocks.startQuizAttempt.mockResolvedValue({ attemptId: 55 });
  mocks.submitQuizAttempt.mockResolvedValue({
    attemptId: 55,
    score: 1,
    correct: 1,
    total: 1,
    topicBreakdown: {},
    answers: [{
      questionId: 11,
      isCorrect: true,
      correctAnswer: "Term A",
      explanation: "Grounded explanation.",
      sourcePageUrl: "/documents/4/pages/6",
      answer: "",
    }],
  });
  mocks.retakeMissedQuestions.mockResolvedValue({
    id: 9,
    title: "Missed questions",
    engine: "classic",
    report: {},
    questions: [{ ...question, id: 33 }],
  });
});

afterEach(cleanup);

describe("quiz screens", () => {
  it("disables the AI provider for private documents", async () => {
    mocks.listDocuments.mockResolvedValue([{
      id: 4,
      title: "Private notes.pdf",
      status: "ready",
      is_private: true,
      page_count: 7,
    }]);
    render(<QuizBuilderPage />);
    const option = await screen.findByRole("radio", { name: "AI provider" });
    expect("disabled" in option && option.disabled).toBe(true);
    expect(screen.getByText("AI provider is disabled because this document is private.")).toBeTruthy();
  });

  it("shows partial-result transparency and per-question engine counts", async () => {
    mocks.listDocuments.mockResolvedValue([{
      id: 4,
      title: "Course.pdf",
      status: "ready",
      is_private: false,
      page_count: 7,
    }]);
    mocks.createQuiz.mockResolvedValue({
      id: 3,
      title: "Unit II review",
      engine: "classic",
      questionCount: 7,
      report: { accepted: 7, requested_engine: "llm", fallback_reason: "rate_limited" },
    });
    mocks.getQuiz.mockResolvedValue({
      ...quiz,
      questions: Array.from({ length: 7 }, (_, index) => ({ ...question, id: index + 1 })),
    });
    render(<QuizBuilderPage />);
    await screen.findByRole("button", { name: "Generate quiz" });
    fireEvent.click(screen.getByRole("button", { name: "Generate quiz" }));
    expect(await screen.findByText(/Generated 7 of 10 questions: the AI provider was rate limited/)).toBeTruthy();
    expect(screen.getByText(/Offline \(classic\) 7/)).toBeTruthy();
    expect(screen.getAllByText("Offline (classic)").length).toBeGreaterThan(0);
  });

  it("hides answers until submission, lists unanswered questions, and blocks a second submit", async () => {
    let finishSubmission: ((value: {
      attemptId: number;
      score: number;
      correct: number;
      total: number;
      topicBreakdown: Record<string, { correct: number; total: number }>;
      answers: Array<{
        questionId: number;
        isCorrect: boolean;
        correctAnswer: string;
        explanation: string;
        sourcePageUrl: string;
        answer: string;
      }>;
    }) => void) | undefined;
    mocks.getQuiz.mockResolvedValue({
      ...quiz,
      questions: [
        question,
        { ...question, id: 12, question: "What is another source fact?" },
      ],
    });
    mocks.submitQuizAttempt.mockImplementation(() => new Promise((resolve) => {
      finishSubmission = resolve;
    }));
    render(<QuizAttemptPage quizId={3} />);
    await screen.findByText(question.question);
    expect(screen.queryByText("Secret correct answer", { exact: true })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Next (N)" }));
    fireEvent.click(screen.getByRole("button", { name: "Submit quiz" }));
    expect(await screen.findByText("Question 1")).toBeTruthy();
    expect(screen.getByText("Question 2")).toBeTruthy();
    const confirm = screen.getByRole("button", { name: "Confirm submission" });
    fireEvent.click(confirm);
    fireEvent.click(confirm);
    await waitFor(() => expect(mocks.submitQuizAttempt).toHaveBeenCalledTimes(1));
    finishSubmission?.({
      attemptId: 55,
      score: 0,
      correct: 0,
      total: 2,
      topicBreakdown: {},
      answers: [],
    });
  });

  it("retakes only backend-selected missed questions and links each result to its source", async () => {
    render(<QuizResultsPage quizId={3} attemptId={55} />);
    await screen.findByText("Quiz results");
    const sourceLink = screen.getByRole("link", { name: "View source on page 6" });
    expect(sourceLink.getAttribute("href")).toBe("/chat/4?page=6");
    fireEvent.click(screen.getByRole("button", { name: "Retake only the questions I missed" }));
    await waitFor(() => {
      expect(mocks.retakeMissedQuestions).toHaveBeenCalledWith(3, 55);
      expect(mocks.push).toHaveBeenCalledWith("/quizzes/9");
    });
  });

  it("shows the quiz list empty state", async () => {
    render(<QuizListPage />);
    expect(await screen.findByText("No quizzes yet")).toBeTruthy();
  });
});
