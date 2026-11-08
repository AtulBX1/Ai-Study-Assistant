import { apiClient, unwrapApiResult } from "@/lib/api";
import type { components } from "@/lib/api/schema";
import { normalizeApiError } from "@/lib/errors";

type JsonRecord = Record<string, unknown>;

export type QuizQuestion = {
  id: number;
  question: string;
  type: string;
  options: string[] | null;
  explanation: string | null;
  page: number;
  difficulty: string;
  engine: string;
  provider: string | null;
  topic: string | null;
  sourcePageUrl: string | null;
};

export type QuizRecord = {
  id: number;
  title: string;
  engine: string;
  report: JsonRecord;
  questions: QuizQuestion[];
};

export type QuizSummary = {
  id: number;
  title: string;
  engine: string;
  report: JsonRecord;
};

export type QuizGenerationResult = QuizSummary & {
  questionCount: number;
};

export type QuizAnswerResult = {
  questionId: number;
  isCorrect: boolean;
  correctAnswer: string | null;
  explanation: string | null;
  sourcePageUrl: string | null;
  answer: string;
};

export type QuizAttemptResult = {
  attemptId: number;
  score: number;
  correct: number | null;
  total: number | null;
  topicBreakdown: Record<string, { correct: number; total: number }>;
  answers: QuizAnswerResult[];
};

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function requiredNumber(value: unknown, label: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`The quiz response did not contain a valid ${label}.`);
  }
  return value;
}

function optionalString(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function questionFrom(value: unknown): QuizQuestion {
  if (!isRecord(value)) throw new Error("The quiz contained an invalid question.");
  const options = Array.isArray(value.options)
    ? value.options.filter((option): option is string => typeof option === "string")
    : null;
  return {
    id: requiredNumber(value.id, "question id"),
    question: typeof value.question === "string" ? value.question : "",
    type: typeof value.type === "string" ? value.type : "short_answer",
    options,
    explanation: optionalString(value.explanation),
    page: requiredNumber(value.page, "source page"),
    difficulty: typeof value.difficulty === "string" ? value.difficulty : "mixed",
    engine: typeof value.engine === "string" ? value.engine : "unknown",
    provider: optionalString(value.provider),
    topic: optionalString(value.topic),
    sourcePageUrl: optionalString(value.source_page_url),
  };
}

function summaryFrom(value: unknown): QuizSummary {
  if (!isRecord(value)) throw new Error("The quiz response was invalid.");
  return {
    id: requiredNumber(value.id, "quiz id"),
    title: typeof value.title === "string" ? value.title : "Untitled quiz",
    engine: typeof value.engine === "string" ? value.engine : "unknown",
    report: isRecord(value.report)
      ? value.report
      : isRecord(value.generation_report)
        ? value.generation_report
        : {},
  };
}

function breakdownFrom(value: unknown): QuizAttemptResult["topicBreakdown"] {
  if (!isRecord(value)) return {};
  return Object.fromEntries(
    Object.entries(value).flatMap(([topic, counts]) => {
      if (!isRecord(counts)) return [];
      if (
        typeof counts.correct !== "number" ||
        typeof counts.total !== "number"
      ) {
        return [];
      }
      return [[topic, { correct: counts.correct, total: counts.total }]];
    }),
  );
}

export async function listQuizzes(): Promise<QuizSummary[]> {
  const result = await apiClient.GET("/quizzes", {
    params: { query: { limit: 100, offset: 0 } },
  });
  const data: unknown = unwrapApiResult(result);
  if (!Array.isArray(data)) throw new Error("The quiz list response was invalid.");
  return data.map(summaryFrom);
}

export async function getQuiz(quizId: number): Promise<QuizRecord> {
  const result = await apiClient.GET("/quizzes/{quiz_id}", {
    params: { path: { quiz_id: quizId } },
  });
  const data: unknown = unwrapApiResult(result);
  if (!isRecord(data) || !Array.isArray(data.questions)) {
    throw new Error("The quiz details response was invalid.");
  }
  const summary = summaryFrom(data);
  return { ...summary, questions: data.questions.map(questionFrom) };
}

export async function createQuiz(
  input: components["schemas"]["app__services__quiz__schemas__GenerationRequest"],
): Promise<QuizGenerationResult> {
  const result = await apiClient.POST("/quizzes", { body: input });
  const data: unknown = unwrapApiResult(result);
  const summary = summaryFrom(data);
  if (!isRecord(data)) throw new Error("The quiz generation response was invalid.");
  return {
    ...summary,
    questionCount: requiredNumber(data.questions, "generated question count"),
  };
}

export async function startQuizAttempt(
  quizId: number,
): Promise<{ attemptId: number }> {
  const result = await apiClient.POST("/quizzes/{quiz_id}/attempts", {
    params: { path: { quiz_id: quizId } },
  });
  const data: unknown = unwrapApiResult(result);
  if (!isRecord(data)) throw new Error("The attempt response was invalid.");
  return { attemptId: requiredNumber(data.attempt_id, "attempt id") };
}

export async function submitQuizAttempt(
  quizId: number,
  attemptId: number,
  answers: Array<{ question_id: number; answer: string }>,
): Promise<QuizAttemptResult> {
  const result = await apiClient.POST(
    "/quizzes/{quiz_id}/attempts/{attempt_id}/submit",
    {
      params: { path: { quiz_id: quizId, attempt_id: attemptId } },
      body: { answers },
    },
  );
  const data: unknown = unwrapApiResult(result);
  if (!isRecord(data) || !Array.isArray(data.results)) {
    throw new Error("The quiz submission response was invalid.");
  }
  return {
    attemptId: requiredNumber(data.attempt_id, "attempt id"),
    score: requiredNumber(data.score, "score"),
    correct: typeof data.correct === "number" ? data.correct : null,
    total: typeof data.total === "number" ? data.total : null,
    topicBreakdown: breakdownFrom(data.topic_breakdown),
    answers: data.results.flatMap((item) => {
      if (!isRecord(item) || typeof item.question_id !== "number") return [];
      return [
        {
          questionId: item.question_id,
          isCorrect: item.is_correct === true,
          correctAnswer: optionalString(item.correct_answer),
          explanation: optionalString(item.explanation),
          sourcePageUrl: optionalString(item.source_page_url),
          answer: "",
        },
      ];
    }),
  };
}

export async function getQuizResults(
  quizId: number,
  attemptId: number,
): Promise<QuizAttemptResult> {
  const result = await apiClient.GET("/quizzes/{quiz_id}/results/{attempt_id}", {
    params: { path: { quiz_id: quizId, attempt_id: attemptId } },
  });
  const data: unknown = unwrapApiResult(result);
  if (!isRecord(data)) throw new Error("The quiz results response was invalid.");
  const rows = Array.isArray(data.answers)
    ? data.answers
    : Array.isArray(data.results)
      ? data.results
      : [];
  return {
    attemptId: requiredNumber(data.attempt_id, "attempt id"),
    score: typeof data.score === "number" ? data.score : 0,
    correct: typeof data.correct === "number" ? data.correct : null,
    total: typeof data.total === "number" ? data.total : null,
    topicBreakdown: breakdownFrom(data.topic_breakdown),
    answers: rows.flatMap((item) => {
      if (!isRecord(item) || typeof item.question_id !== "number") return [];
      return [
        {
          questionId: item.question_id,
          isCorrect: item.is_correct === true,
          correctAnswer: optionalString(item.correct_answer),
          explanation: optionalString(item.explanation),
          sourcePageUrl: optionalString(item.source_page_url),
          answer: optionalString(item.answer) ?? "",
        },
      ];
    }),
  };
}

export async function retakeMissedQuestions(
  quizId: number,
  attemptId: number,
): Promise<QuizRecord> {
  const result = await apiClient.POST("/quizzes/{quiz_id}/retake", {
    params: { path: { quiz_id: quizId }, query: { attempt_id: attemptId } },
  });
  const data: unknown = unwrapApiResult(result);
  if (!isRecord(data) || !Array.isArray(data.questions)) {
    throw new Error("The missed-question retake response was invalid.");
  }
  const summary = summaryFrom(data);
  return { ...summary, questions: data.questions.map(questionFrom) };
}

export async function downloadExamPaper(
  quizId: number,
  format: "pdf" | "docx",
): Promise<Blob> {
  const result = await apiClient.GET("/export/{kind}/{item_id}", {
    params: {
      path: { kind: "quiz", item_id: quizId },
      query: { format, include_answers: false },
    },
    parseAs: "blob",
  });
  if (!result.response.ok || result.data === undefined) {
    throw normalizeApiError(result.response.status, result.error);
  }
  return result.data;
}

export function reportSummary(
  report: JsonRecord,
  requestedCount?: number,
  actualCount?: number,
  engineCounts?: Record<string, number>,
): string | null {
  const accepted = typeof report.accepted === "number" ? report.accepted : null;
  const rejected = isRecord(report.rejected) ? report.rejected : null;
  const fallbackReason =
    typeof report.fallback_reason === "string" ? report.fallback_reason : null;
  const requested = typeof report.requested_engine === "string"
    ? report.requested_engine
    : null;
  const rejectedCount = rejected
    ? Object.values(rejected).reduce<number>(
        (sum, count) => sum + (typeof count === "number" ? count : 0),
        0,
      )
    : 0;
  if (accepted === null) return fallbackReason;
  if (fallbackReason) {
    const reason =
      fallbackReason === "rate_limited"
        ? "the AI provider was rate limited"
        : fallbackReason.replaceAll("_", " ");
    const count = actualCount ?? accepted;
    const partial =
      requestedCount !== undefined
        ? `Generated ${count} of ${requestedCount} questions`
        : `Generated ${count} question${count === 1 ? "" : "s"}`;
    const engines = engineCounts
      ? Object.entries(engineCounts)
          .map(([engine, amount]) => `${engineLabel(engine)} ${amount}`)
          .join(", ")
      : null;
    const validation =
      rejectedCount > 0
        ? ` ${rejectedCount} candidate${rejectedCount === 1 ? "" : "s"} did not pass validation.`
        : "";
    return `${partial}: ${reason}.${validation}${engines ? ` Question engines: ${engines}.` : " The backend used its reported fallback."}`;
  }
  if (rejectedCount > 0) {
    const count = actualCount ?? accepted;
    const partial =
      requestedCount !== undefined && count < requestedCount
        ? `Generated ${count} of ${requestedCount} questions`
        : `Generated ${count} question${count === 1 ? "" : "s"}`;
    return `${partial}; ${rejectedCount} candidate${rejectedCount === 1 ? "" : "s"} did not pass validation.`;
  }
  if (requested === "llm") return `AI provider: ${accepted} question${accepted === 1 ? "" : "s"}.`;
  return null;
}

export function engineLabel(engine: string, provider?: string | null): string {
  if (engine === "classic") return "Offline (classic)";
  if (engine === "llm") return provider ? `AI provider: ${provider}` : "AI provider";
  return engine;
}
