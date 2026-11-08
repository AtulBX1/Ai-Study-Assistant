"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
} from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { PageHeader } from "@/components/ui/page-header";
import type { DocumentRecord } from "@/lib/documents";
import { listDocuments } from "@/lib/documents";
import {
  createQuiz,
  downloadExamPaper,
  engineLabel,
  getQuiz,
  getQuizResults,
  listQuizzes,
  reportSummary,
  retakeMissedQuestions,
  startQuizAttempt,
  submitQuizAttempt,
  type QuizAttemptResult,
  type QuizRecord,
  type QuizSummary,
} from "@/lib/quiz-study";

type JsonRecord = Record<string, unknown>;

const questionTypes = [
  ["multiple_choice", "Multiple choice"],
  ["true_false", "True / false"],
  ["fill_in_the_blank", "Fill in the blank"],
  ["short_answer", "Short answer"],
] as const;

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function sourceDocumentId(url: string | null): number | null {
  const match = url?.match(/^\/documents\/(\d+)\/pages\/\d+$/);
  return match ? Number(match[1]) : null;
}

function reportQuestionCount(report: JsonRecord): number | null {
  if (typeof report.accepted === "number") return report.accepted;
  return null;
}

function quizAnswersKey(quizId: number) {
  return `quiz-${quizId}-answers`;
}

function attemptSnapshotKey(quizId: number, attemptId: number) {
  return `quiz-${quizId}-attempt-${attemptId}`;
}

function readAnswerSnapshot(quizId: number): Record<string, string> {
  try {
    const stored = sessionStorage.getItem(quizAnswersKey(quizId));
    const parsed: unknown = stored ? JSON.parse(stored) : {};
    if (!isRecord(parsed)) return {};
    return Object.fromEntries(
      Object.entries(parsed).filter(
        (entry): entry is [string, string] => typeof entry[1] === "string",
      ),
    );
  } catch {
    return {};
  }
}

function writeAnswerSnapshot(
  quizId: number,
  answers: Record<string, string>,
): void {
  try {
    sessionStorage.setItem(quizAnswersKey(quizId), JSON.stringify(answers));
  } catch {
    // The active attempt remains usable in component memory.
  }
}

function writeAttemptSnapshot(
  quizId: number,
  attemptId: number,
  answers: Record<string, string>,
  result: QuizAttemptResult,
): void {
  try {
    sessionStorage.setItem(
      attemptSnapshotKey(quizId, attemptId),
      JSON.stringify({ answers, result }),
    );
  } catch {
    // Results remain available from the server when session storage is disabled.
  }
}

function readAttemptSnapshot(
  quizId: number,
  attemptId: number,
): { answers: Record<string, string>; result: QuizAttemptResult | null } {
  try {
    const stored = sessionStorage.getItem(attemptSnapshotKey(quizId, attemptId));
    const parsed: unknown = stored ? JSON.parse(stored) : null;
    if (!isRecord(parsed)) return { answers: {}, result: null };
    const answers = isRecord(parsed.answers)
      ? Object.fromEntries(
          Object.entries(parsed.answers).filter(
            (entry): entry is [string, string] => typeof entry[1] === "string",
          ),
        )
      : {};
    const rawResult = parsed.result;
    const result =
      isRecord(rawResult) &&
      typeof rawResult.attemptId === "number" &&
      typeof rawResult.score === "number" &&
      Array.isArray(rawResult.answers)
        ? {
            attemptId: rawResult.attemptId,
            score: rawResult.score,
            correct: typeof rawResult.correct === "number" ? rawResult.correct : null,
            total: typeof rawResult.total === "number" ? rawResult.total : null,
            topicBreakdown: isRecord(rawResult.topicBreakdown)
              ? Object.fromEntries(
                  Object.entries(rawResult.topicBreakdown).flatMap(([topic, value]) =>
                    isRecord(value) &&
                    typeof value.correct === "number" &&
                    typeof value.total === "number"
                      ? [[topic, { correct: value.correct, total: value.total }]]
                      : [],
                  ),
                )
              : {},
            answers: rawResult.answers.flatMap((item): QuizAttemptResult["answers"] => {
              if (!isRecord(item) || typeof item.questionId !== "number") return [];
              return [{
                questionId: item.questionId,
                isCorrect: item.isCorrect === true,
                correctAnswer: typeof item.correctAnswer === "string" ? item.correctAnswer : null,
                explanation: typeof item.explanation === "string" ? item.explanation : null,
                sourcePageUrl: typeof item.sourcePageUrl === "string" ? item.sourcePageUrl : null,
                answer: typeof item.answer === "string" ? item.answer : "",
              }];
            }),
          }
        : null;
    return { answers, result };
  } catch {
    return { answers: {}, result: null };
  }
}

function ErrorMessage({ message }: { message: string }) {
  return <p className="text-sm text-danger" role="alert">{message}</p>;
}

function EngineBadge({
  engine,
  provider,
}: {
  engine: string;
  provider?: string | null;
}) {
  return (
    <span className="inline-flex rounded-full border border-border px-2.5 py-1 text-xs font-medium">
      {engineLabel(engine, provider)}
    </span>
  );
}

export function QuizListPage() {
  const [quizzes, setQuizzes] = useState<QuizSummary[]>([]);
  const [details, setDetails] = useState<Record<number, QuizRecord>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const items = await listQuizzes();
        const quizDetails = await Promise.all(
          items.map(async (quiz) => [quiz.id, await getQuiz(quiz.id)] as const),
        );
        if (!active) return;
        setQuizzes(items);
        setDetails(Object.fromEntries(quizDetails));
      } catch (reason) {
        if (active) setError(reason instanceof Error ? reason.message : "Could not load quizzes.");
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  return (
    <main className="mx-auto w-full max-w-5xl px-4 py-8 sm:px-6">
      <PageHeader
        title="Quizzes"
        description="Practice with questions grounded in your documents."
        action={<Link href="/quizzes/new"><Button>Create quiz</Button></Link>}
      />
      {loading ? <p role="status" aria-live="polite">Loading quizzes…</p> : null}
      {error ? <ErrorState title="Could not load quizzes" description={error} /> : null}
      {!loading && !error && quizzes.length === 0 ? (
        <EmptyState
          title="No quizzes yet"
          description="Build your first quiz from a ready document."
          action={<Link href="/quizzes/new"><Button>Create a quiz</Button></Link>}
        />
      ) : null}
      <div className="grid gap-4">
        {quizzes.map((quiz) => {
          const questions = details[quiz.id]?.questions ?? [];
          const documentId = sourceDocumentId(questions[0]?.sourcePageUrl ?? null);
          const count = reportQuestionCount(quiz.report) ?? questions.length;
          const mix = isRecord(quiz.report.difficulty_mix)
            ? Object.entries(quiz.report.difficulty_mix)
                .map(([difficulty, amount]) => `${difficulty}: ${amount}`)
                .join(" · ")
            : "Difficulty mix not reported";
          return (
            <Card key={quiz.id}>
              <CardContent className="flex flex-col gap-3 p-5 sm:flex-row sm:items-center">
                <div className="min-w-0 flex-1">
                  <h2 className="font-semibold">{quiz.title}</h2>
                  <p className="mt-1 text-sm text-muted-foreground">
                    Document: {documentId ? `Document ${documentId}` : "Not included in quiz list"}
                    {" · "}{count} questions
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {mix} · Created date and last score are not provided by this API.
                  </p>
                </div>
                <EngineBadge engine={quiz.engine} />
                <Link href={`/quizzes/${quiz.id}`}><Button variant="outline">Open quiz</Button></Link>
              </CardContent>
            </Card>
          );
        })}
      </div>
    </main>
  );
}

export function QuizBuilderPage({
  prefillDocumentId,
  prefillQuestionCount,
  prefillTitle,
}: {
  prefillDocumentId?: number;
  prefillQuestionCount?: number;
  prefillTitle?: string;
}) {
  const router = useRouter();
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [documentLoading, setDocumentLoading] = useState(true);
  const [documentError, setDocumentError] = useState<string | null>(null);
  const [documentId, setDocumentId] = useState("");
  const [title, setTitle] = useState("");
  const [scope, setScope] = useState<"whole" | "pages" | "topic">("whole");
  const [pageStart, setPageStart] = useState("1");
  const [pageEnd, setPageEnd] = useState("");
  const [topic, setTopic] = useState("");
  const [questionCount, setQuestionCount] = useState(String(prefillQuestionCount ?? 10));
  const [difficulty, setDifficulty] = useState<"mixed" | "easy" | "medium" | "hard">("mixed");
  const [engine, setEngine] = useState<"auto" | "classic" | "llm">("auto");
  const [status, setStatus] = useState<"idle" | "generating" | "complete">("idle");
  const [generated, setGenerated] = useState<{
    id: number;
    actual: number;
    requested: number;
    report: JsonRecord;
    engine: string;
    engineCounts: Record<string, number>;
    engineDetailsError: string | null;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    void listDocuments(0, 100)
      .then((items) => {
        if (!active) return;
        const ready = items.filter((item) => item.status === "ready");
        setDocuments(ready);
        if (ready[0]) {
          setDocumentId(
            String(ready.some((item) => item.id === prefillDocumentId)
              ? prefillDocumentId
              : ready[0].id),
          );
        }
      })
      .catch((reason: unknown) => {
        if (active) setDocumentError(reason instanceof Error ? reason.message : "Could not load documents.");
      })
      .finally(() => {
        if (active) setDocumentLoading(false);
      });
    return () => {
      active = false;
    };
  }, [prefillDocumentId]);

  useEffect(() => {
    if (prefillTitle) setTitle(prefillTitle);
  }, [prefillTitle]);

  const selectedDocument = documents.find((item) => String(item.id) === documentId);
  const aiUnavailable = selectedDocument?.is_private !== false;

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setStatus("generating");
    const requested = Number(questionCount);
    try {
      const result = await createQuiz({
        title: title.trim() || "Study quiz",
        document_ids: [Number(documentId)],
        ...(scope === "pages"
          ? { page_start: Number(pageStart), ...(pageEnd ? { page_end: Number(pageEnd) } : {}) }
          : {}),
        ...(scope === "topic" && topic.trim() ? { topics: [topic.trim()] } : {}),
        question_count: requested,
        engine: engine === "llm" ? "llm" : "classic",
        difficulty: difficulty === "mixed" ? null : difficulty,
      });
      let engineCounts: Record<string, number> = {};
      let engineDetailsError: string | null = null;
      try {
        const detail = await getQuiz(result.id);
        engineCounts = detail.questions.reduce<Record<string, number>>((counts, question) => {
          counts[question.engine] = (counts[question.engine] ?? 0) + 1;
          return counts;
        }, {});
      } catch (reason) {
        engineDetailsError = reason instanceof Error ? reason.message : "Question engine details could not be loaded.";
      }
      setGenerated({
        id: result.id,
        actual: result.questionCount,
        requested,
        report: result.report,
        engine: result.engine,
        engineCounts,
        engineDetailsError,
      });
      setStatus("complete");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Quiz generation failed.");
      setStatus("idle");
    }
  }

  const summary = generated
    ? reportSummary(generated.report, generated.requested, generated.actual, generated.engineCounts)
    : null;

  return (
    <main className="mx-auto w-full max-w-3xl px-4 py-8 sm:px-6">
      <PageHeader title="Build a quiz" description="Choose a source and generation settings." />
      {documentError ? <ErrorState title="Could not load documents" description={documentError} /> : null}
      <form className="space-y-5" onSubmit={(event) => void onSubmit(event)}>
        <label className="block space-y-2 text-sm font-medium">
          Quiz title
          <input className="w-full rounded-md border border-border bg-background px-3 py-2" value={title} onChange={(event) => setTitle(event.target.value)} />
        </label>
        <label className="block space-y-2 text-sm font-medium">
          Document
          <select
            className="w-full rounded-md border border-border bg-background px-3 py-2"
            aria-label="Document"
            value={documentId}
            disabled={documentLoading || documents.length === 0}
            onChange={(event) => setDocumentId(event.target.value)}
            required
          >
            {documents.map((document) => <option key={document.id} value={document.id}>{document.title}</option>)}
          </select>
        </label>
        {documentLoading ? <p role="status">Loading ready documents…</p> : null}
        {!documentLoading && documents.length === 0 ? (
          <p className="text-sm text-muted-foreground">No ready documents are available. Upload a PDF and wait for it to finish processing.</p>
        ) : null}
        <fieldset className="space-y-2">
          <legend className="text-sm font-medium">Scope</legend>
          <div className="flex flex-wrap gap-4 text-sm">
            {(["whole", "pages", "topic"] as const).map((value) => (
              <label key={value} className="inline-flex items-center gap-2">
                <input type="radio" name="scope" value={value} checked={scope === value} onChange={() => setScope(value)} />
                {value === "whole" ? "Whole document" : value === "pages" ? "Page range" : "Chapter / topic"}
              </label>
            ))}
          </div>
        </fieldset>
        {scope === "pages" ? (
          <div className="grid grid-cols-2 gap-3">
            <label className="space-y-2 text-sm">Page from
              <input aria-label="Page from" type="number" min="1" max={selectedDocument?.page_count ?? undefined} required value={pageStart} onChange={(event) => setPageStart(event.target.value)} className="w-full rounded-md border border-border bg-background px-3 py-2" />
            </label>
            <label className="space-y-2 text-sm">Page to
              <input aria-label="Page to" type="number" min={pageStart || "1"} max={selectedDocument?.page_count ?? undefined} value={pageEnd} onChange={(event) => setPageEnd(event.target.value)} className="w-full rounded-md border border-border bg-background px-3 py-2" />
            </label>
          </div>
        ) : null}
        {scope === "topic" ? (
          <label className="block space-y-2 text-sm">Chapter or topic
            <input className="w-full rounded-md border border-border bg-background px-3 py-2" value={topic} onChange={(event) => setTopic(event.target.value)} placeholder="For example, Unit II — Word2Vec" />
          </label>
        ) : null}
        <fieldset className="space-y-2">
          <legend className="text-sm font-medium">Question types</legend>
          <div className="grid gap-2 sm:grid-cols-2">
            {questionTypes.map(([value, label]) => (
              <label key={value} className="flex items-center gap-2 text-sm">
                <input type="checkbox" disabled aria-label={label} />
                {label}
              </label>
            ))}
          </div>
          <p className="text-xs text-muted-foreground">The current generation API selects validated question types automatically; type filtering is not supported yet.</p>
        </fieldset>
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="space-y-2 text-sm">Question count
            <input type="number" min="1" max="50" value={questionCount} onChange={(event) => setQuestionCount(event.target.value)} className="w-full rounded-md border border-border bg-background px-3 py-2" />
          </label>
          <label className="space-y-2 text-sm">Difficulty
            <select value={difficulty} onChange={(event) => {
              const value = event.target.value;
              setDifficulty(value === "easy" || value === "medium" || value === "hard" ? value : "mixed");
            }} className="w-full rounded-md border border-border bg-background px-3 py-2">
              <option value="mixed">Mixed</option><option value="easy">Easy</option><option value="medium">Medium</option><option value="hard">Hard</option>
            </select>
          </label>
        </div>
        <fieldset className="space-y-2">
          <legend className="text-sm font-medium">Generation engine</legend>
          <div className="grid gap-2">
            <label className="flex items-center gap-2 text-sm"><input type="radio" name="engine" checked={engine === "auto"} onChange={() => setEngine("auto")} />Auto (default)</label>
            <label className="flex items-center gap-2 text-sm"><input type="radio" name="engine" checked={engine === "classic"} onChange={() => setEngine("classic")} />Offline (classic, never leaves this computer)</label>
            <label className={`flex items-center gap-2 text-sm ${aiUnavailable ? "text-muted-foreground" : ""}`}>
              <input
                type="radio"
                name="engine"
                checked={engine === "llm"}
                disabled={aiUnavailable}
                onChange={() => setEngine("llm")}
                aria-label="AI provider"
              />
              AI provider
              {aiUnavailable ? <span>(disabled)</span> : null}
            </label>
          </div>
          <p className="text-xs text-muted-foreground">AI provider sends this document&apos;s text to an online service.</p>
          {aiUnavailable ? (
            <p className="text-xs text-muted-foreground" role="status">
              {selectedDocument?.is_private
                ? "AI provider is disabled because this document is private."
                : "AI provider is disabled because the API does not expose this document's privacy setting; it stays local until privacy can be verified."}
            </p>
          ) : null}
          <p className="text-xs text-muted-foreground">This API accepts Offline or AI provider engines; Auto uses the documented offline default.</p>
        </fieldset>
        {error ? <ErrorMessage message={error} /> : null}
        <Button type="submit" disabled={status === "generating" || !documentId || documentError !== null}>
          {status === "generating" ? "Generating quiz…" : "Generate quiz"}
        </Button>
      </form>
      <div aria-live="polite" className="mt-5 space-y-4">
        {status === "generating" ? <p role="status">Generating and validating questions. This may take a little while…</p> : null}
        {generated ? (
          <Card>
            <CardContent className="space-y-3 p-5">
              <h2 className="font-semibold">Generation complete</h2>
              <EngineBadge engine={generated.engine} />
              {summary ? <p className="text-sm">{summary}</p> : null}
              {generated.engineDetailsError ? <p className="text-sm text-muted-foreground" role="status">Question engine details could not be verified: {generated.engineDetailsError}</p> : null}
              <p className="text-sm text-muted-foreground">
                {generated.actual < generated.requested
                  ? `The backend returned ${generated.actual} of ${generated.requested} requested questions. You can accept the shorter quiz or generate the remaining questions as a separate quiz; the API cannot append to an existing quiz.`
                  : `${generated.actual} questions are ready.`}
              </p>
              <div className="flex flex-wrap gap-2">
                <Link href={`/quizzes/${generated.id}`}><Button>Accept quiz</Button></Link>
                {generated.actual < generated.requested ? (
                  <Button
                    variant="outline"
                    onClick={() => router.push(
                      `/quizzes/new?documentId=${documentId}&count=${generated.requested - generated.actual}&title=${encodeURIComponent(`${title.trim() || "Study quiz"} (additional)`)}`,
                    )}
                  >
                    Add more (new quiz)
                  </Button>
                ) : null}
                <Link href="/quizzes"><Button variant="outline">Retry later</Button></Link>
              </div>
            </CardContent>
          </Card>
        ) : null}
      </div>
    </main>
  );
}

export function QuizDetailPage({ quizId }: { quizId: number }) {
  const [quiz, setQuiz] = useState<QuizRecord | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);

  useEffect(() => {
    let active = true;
    void getQuiz(quizId)
      .then((item) => { if (active) setQuiz(item); })
      .catch((reason: unknown) => { if (active) setError(reason instanceof Error ? reason.message : "Could not load this quiz."); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [quizId]);

  async function exportPaper(format: "pdf" | "docx") {
    setDownloading(true);
    setDownloadError(null);
    try {
      const blob = await downloadExamPaper(quizId, format);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `quiz-${quizId}.${format}`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (reason) {
      setDownloadError(reason instanceof Error ? reason.message : "The exam paper could not be downloaded.");
    } finally {
      setDownloading(false);
    }
  }

  return (
    <main className="mx-auto w-full max-w-4xl px-4 py-8 sm:px-6">
      {loading ? <p role="status" aria-live="polite">Loading quiz…</p> : null}
      {error ? <ErrorState title="Could not load quiz" description={error} /> : null}
      {quiz ? (
        <>
          <PageHeader title={quiz.title} description={`${quiz.questions.length} questions`} action={<EngineBadge engine={quiz.engine} />} />
          {reportSummary(quiz.report) ? <p className="mb-4 text-sm" role="status">{reportSummary(quiz.report)}</p> : null}
          <Card><CardContent className="space-y-4 p-5">
            <p>Correct answers are hidden during the attempt and shown only after submission.</p>
            <div className="flex flex-wrap gap-2">
              <Link href={`/quizzes/${quizId}/attempt`}><Button>Start quiz</Button></Link>
              <Button variant="outline" disabled={downloading} onClick={() => void exportPaper("pdf")}>Export exam paper (PDF)</Button>
              <Button variant="outline" disabled={downloading} onClick={() => void exportPaper("docx")}>Export exam paper (DOCX)</Button>
            </div>
            {downloadError ? <ErrorMessage message={downloadError} /> : null}
          </CardContent></Card>
        </>
      ) : null}
    </main>
  );
}

export function QuizAttemptPage({ quizId }: { quizId: number }) {
  const router = useRouter();
  const [quiz, setQuiz] = useState<QuizRecord | null>(null);
  const [attemptId, setAttemptId] = useState<number | null>(null);
  const [answers, setAnswers] = useState<Record<number, string>>({});
  const [flags, setFlags] = useState<Record<number, boolean>>({});
  const [current, setCurrent] = useState(0);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submitLock = useRef(false);

  useEffect(() => {
    let active = true;
    void Promise.all([getQuiz(quizId), startQuizAttempt(quizId)])
      .then(([quizData, attempt]) => {
        if (!active) return;
        setQuiz(quizData);
        setAttemptId(attempt.attemptId);
        setAnswers(
          Object.fromEntries(
            Object.entries(readAnswerSnapshot(quizId)).map(([id, answer]) => [Number(id), answer]),
          ),
        );
      })
      .catch((reason: unknown) => { if (active) setError(reason instanceof Error ? reason.message : "Could not start this quiz."); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [quizId]);

  useEffect(() => {
    if (quiz) {
      writeAnswerSnapshot(quizId, Object.fromEntries(
        Object.entries(answers).map(([id, answer]) => [String(id), answer]),
      ));
    }
  }, [answers, quiz, quizId]);

  const setAnswer = useCallback((questionId: number, answer: string) => {
    setAnswers((previous) => ({ ...previous, [questionId]: answer }));
  }, []);

  useEffect(() => {
    if (!quiz) return;
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target;
      if (target instanceof HTMLElement && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return;
      if (event.key.toLowerCase() === "n") setCurrent((index) => Math.min(index + 1, quiz.questions.length - 1));
      if (event.key.toLowerCase() === "p") setCurrent((index) => Math.max(index - 1, 0));
      if (event.key.toLowerCase() === "f") {
        const question = quiz.questions[current];
        setFlags((previous) => ({ ...previous, [question.id]: !previous[question.id] }));
      }
      if (/^[1-4]$/.test(event.key)) {
        const question = quiz.questions[current];
        const option = question.options?.[Number(event.key) - 1];
        if (option) setAnswer(question.id, option);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [current, quiz, setAnswer]);

  async function submit() {
    if (submitLock.current || !quiz || attemptId === null) return;
    submitLock.current = true;
    setSubmitting(true);
    setError(null);
    try {
      const submission = await submitQuizAttempt(
        quizId,
        attemptId,
        quiz.questions.map((question) => ({
          question_id: question.id,
          answer: answers[question.id] ?? "",
        })),
      );
      const completed = {
        ...submission,
        answers: submission.answers.map((answer) => ({
          ...answer,
          answer: answers[answer.questionId] ?? "",
        })),
      };
      writeAttemptSnapshot(quizId, attemptId, answersToStringMap(answers), completed);
      router.push(`/quizzes/${quizId}/results/${attemptId}`);
    } catch (reason) {
      submitLock.current = false;
      setSubmitting(false);
      setError(reason instanceof Error ? reason.message : "Could not submit this quiz.");
    }
  }

  const question = quiz?.questions[current];
  const unanswered = quiz?.questions.filter((item) => !answers[item.id]?.trim()) ?? [];
  const progress = quiz?.questions.length
    ? Math.round((Object.keys(answers).filter((key) => answers[Number(key)]?.trim()).length / quiz.questions.length) * 100)
    : 0;

  return (
    <main className="mx-auto w-full max-w-4xl px-4 py-8 sm:px-6">
      {loading ? <p role="status" aria-live="polite">Preparing quiz…</p> : null}
      {error && !quiz ? <ErrorState title="Could not start quiz" description={error} /> : null}
      {quiz && question ? (
        <>
          <PageHeader title={quiz.title} description={`Question ${current + 1} of ${quiz.questions.length}`} action={<EngineBadge engine={quiz.engine} />} />
          <div className="mb-5">
            <div className="h-2 overflow-hidden rounded-full bg-muted" role="progressbar" aria-label="Quiz progress" aria-valuenow={progress} aria-valuemin={0} aria-valuemax={100}>
              <div className="h-full bg-primary transition-all" style={{ width: `${progress}%` }} />
            </div>
            <p className="mt-1 text-xs text-muted-foreground" aria-live="polite">{progress}% answered</p>
          </div>
          <Card><CardContent className="space-y-5 p-5 sm:p-7">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-lg font-semibold">{question.question}</h2>
              <EngineBadge engine={question.engine} provider={question.provider} />
            </div>
            {question.options?.length ? (
              <fieldset className="grid gap-2">
                <legend className="sr-only">Answer choices</legend>
                {question.options.map((option, index) => (
                  <label key={`${question.id}-${option}`} className="flex cursor-pointer items-start gap-3 rounded-lg border border-border p-3 hover:bg-muted">
                    <input type="radio" name={`question-${question.id}`} checked={answers[question.id] === option} onChange={() => setAnswer(question.id, option)} />
                    <span><span className="mr-2 text-muted-foreground">{index + 1}.</span>{option}</span>
                  </label>
                ))}
              </fieldset>
            ) : (
              <label className="block space-y-2 text-sm">
                Your answer
                <textarea rows={3} value={answers[question.id] ?? ""} onChange={(event) => setAnswer(question.id, event.target.value)} className="w-full rounded-md border border-border bg-background px-3 py-2" />
              </label>
            )}
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" onClick={() => setFlags((previous) => ({ ...previous, [question.id]: !previous[question.id] }))}>
                {flags[question.id] ? "Unflag for review (F)" : "Flag for review (F)"}
              </Button>
              {question.topic ? <span className="self-center text-xs text-muted-foreground">Topic: {question.topic}</span> : null}
            </div>
          </CardContent></Card>
          <nav className="my-4 grid grid-cols-5 gap-2 sm:grid-cols-8" aria-label="Question navigator">
            {quiz.questions.map((item, index) => (
              <button
                key={item.id}
                type="button"
                aria-label={`Question ${index + 1}${flags[item.id] ? ", flagged for review" : ""}`}
                aria-current={current === index ? "step" : undefined}
                onClick={() => setCurrent(index)}
                className={`min-h-10 rounded-md border text-sm ${current === index ? "border-primary bg-primary/10" : "border-border"} ${flags[item.id] ? "font-bold text-warning" : ""}`}
              >
                {index + 1}{flags[item.id] ? " !" : ""}
              </button>
            ))}
          </nav>
          <div className="flex flex-wrap justify-between gap-2">
            <Button variant="outline" disabled={current === 0} onClick={() => setCurrent((index) => index - 1)}>Previous (P)</Button>
            {current < quiz.questions.length - 1 ? (
              <Button onClick={() => setCurrent((index) => index + 1)}>Next (N)</Button>
            ) : (
              <Button disabled={submitting} onClick={() => setConfirmOpen(true)}>{submitting ? "Submitting…" : "Submit quiz"}</Button>
            )}
          </div>
          {error ? <ErrorMessage message={error} /> : null}
          {confirmOpen ? (
            <div className="fixed inset-0 z-50 grid place-items-center bg-black/50 p-4" role="alertdialog" aria-modal="true" aria-labelledby="submit-confirm-title">
              <div className="w-full max-w-md rounded-xl bg-background p-6 shadow-xl">
                <h2 id="submit-confirm-title" className="text-lg font-semibold">Submit this quiz?</h2>
                {unanswered.length ? (
                  <div className="mt-3">
                    <p className="text-sm">These questions are unanswered:</p>
                    <ul className="mt-2 list-inside list-disc text-sm">{unanswered.map((item) => <li key={item.id}>Question {quiz.questions.indexOf(item) + 1}</li>)}</ul>
                  </div>
                ) : <p className="mt-3 text-sm">You have answered every question.</p>}
                <div className="mt-5 flex justify-end gap-2">
                  <Button variant="outline" onClick={() => setConfirmOpen(false)}>Continue quiz</Button>
                  <Button disabled={submitting} onClick={() => void submit()}>{submitting ? "Submitting…" : "Confirm submission"}</Button>
                </div>
              </div>
            </div>
          ) : null}
        </>
      ) : null}
    </main>
  );
}

function answersToStringMap(answers: Record<number, string>): Record<string, string> {
  return Object.fromEntries(Object.entries(answers).map(([id, answer]) => [String(id), answer]));
}

export function QuizResultsPage({
  quizId,
  attemptId,
}: {
  quizId: number;
  attemptId: number;
}) {
  const router = useRouter();
  const [quiz, setQuiz] = useState<QuizRecord | null>(null);
  const [result, setResult] = useState<QuizAttemptResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [retaking, setRetaking] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    void Promise.all([getQuiz(quizId), getQuizResults(quizId, attemptId)])
      .then(([quizData, resultData]) => {
        if (!active) return;
        const snapshot = readAttemptSnapshot(quizId, attemptId);
        const cached = snapshot.result;
        setQuiz(quizData);
        setResult({
          ...resultData,
          answers: resultData.answers.map((answer) => {
            const cachedAnswer = cached?.answers.find((item) => item.questionId === answer.questionId);
            return {
              ...answer,
              answer: snapshot.answers[String(answer.questionId)] ?? cachedAnswer?.answer ?? answer.answer,
              correctAnswer: answer.correctAnswer ?? cachedAnswer?.correctAnswer ?? null,
            };
          }),
          topicBreakdown: Object.keys(resultData.topicBreakdown).length
            ? resultData.topicBreakdown
            : cached?.topicBreakdown ?? {},
        });
      })
      .catch((reason: unknown) => { if (active) setError(reason instanceof Error ? reason.message : "Could not load results."); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [attemptId, quizId]);

  const chartData = useMemo(
    () => Object.entries(result?.topicBreakdown ?? {}).map(([topic, value]) => ({
      topic,
      accuracy: value.total ? Math.round((value.correct / value.total) * 100) : 0,
    })),
    [result],
  );
  const strongest = [...chartData].sort((a, b) => b.accuracy - a.accuracy)[0];
  const weakest = [...chartData].sort((a, b) => a.accuracy - b.accuracy)[0];

  async function retakeMissed() {
    setRetaking(true);
    setError(null);
    try {
      const retryQuiz = await retakeMissedQuestions(quizId, attemptId);
      router.push(`/quizzes/${retryQuiz.id}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not prepare missed questions.");
    } finally {
      setRetaking(false);
    }
  }

  async function exportPaper(format: "pdf" | "docx") {
    setExportError(null);
    try {
      const blob = await downloadExamPaper(quizId, format);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `quiz-${quizId}.${format}`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (reason) {
      setExportError(reason instanceof Error ? reason.message : "The exam paper could not be downloaded.");
    }
  }

  const percent = result ? Math.round(result.score * 100) : 0;
  const correctCount =
    result?.correct ?? result?.answers.filter((answer) => answer.isCorrect).length ?? 0;
  const totalCount =
    result?.total ?? (result?.answers.length || quiz?.questions.length || 0);

  return (
    <main className="mx-auto w-full max-w-5xl px-4 py-8 sm:px-6">
      {loading ? <p role="status" aria-live="polite">Loading results…</p> : null}
      {error && !result ? <ErrorState title="Could not load results" description={error} /> : null}
      {quiz && result ? (
        <>
          <PageHeader title="Quiz results" description={quiz.title} action={<EngineBadge engine={quiz.engine} />} />
          <Card><CardContent className="p-5">
            <p className="text-3xl font-semibold" aria-live="polite">{correctCount} / {totalCount} correct</p>
            <p className="mt-1 text-lg">{percent}%</p>
          </CardContent></Card>
          <section className="my-6" aria-labelledby="topic-accuracy">
            <h2 id="topic-accuracy" className="mb-3 text-lg font-semibold">Per-topic accuracy</h2>
            {chartData.length ? (
              <div className="h-64 w-full" role="img" aria-label="Per-topic accuracy chart">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={chartData} margin={{ top: 8, right: 12, bottom: 8, left: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="topic" />
                    <YAxis domain={[0, 100]} unit="%" />
                    <Tooltip formatter={(value) => [`${value}%`, "Accuracy"]} />
                    <Bar dataKey="accuracy" fill="hsl(var(--primary))" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            ) : <p className="text-sm text-muted-foreground">Topic accuracy was not provided for this attempt.</p>}
            <p className="text-sm" aria-live="polite">
              Strongest topic: {strongest ? `${strongest.topic} (${strongest.accuracy}%)` : "not available"}.
              {" "}Weakest topic: {weakest ? `${weakest.topic} (${weakest.accuracy}%)` : "not available"}.
            </p>
          </section>
          <section className="space-y-4" aria-label="Question review">
            {quiz.questions.map((question, index) => {
              const answer = result.answers.find((item) => item.questionId === question.id);
              const documentId = sourceDocumentId(question.sourcePageUrl) ?? sourceDocumentId(answer?.sourcePageUrl ?? null);
              const href = documentId ? `/chat/${documentId}?page=${question.page}` : null;
              return (
                <Card key={question.id}>
                  <CardContent className="space-y-3 p-5">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <h3 className="font-semibold">Question {index + 1}: {question.question}</h3>
                      <EngineBadge engine={question.engine} provider={question.provider} />
                    </div>
                    <p className="text-sm">Your answer: {answer?.answer?.trim() || "Unanswered"}</p>
                    <p className="text-sm">Correct answer: {answer?.correctAnswer ?? "Not returned by the results API."}</p>
                    <p className="text-sm text-muted-foreground">{answer?.explanation ?? "No explanation was provided."}</p>
                    <p className="text-sm">{answer?.isCorrect ? "Correct" : "Incorrect"}</p>
                    {href ? <Link className="text-sm text-primary underline" href={href}>View source on page {question.page}</Link> : <p className="text-sm text-muted-foreground">Source document link is not available.</p>}
                  </CardContent>
                </Card>
              );
            })}
          </section>
          <div className="mt-6 flex flex-wrap gap-2">
            <Button disabled={retaking} onClick={() => void retakeMissed()}>{retaking ? "Preparing…" : "Retake only the questions I missed"}</Button>
            <Link href={`/quizzes/${quizId}/attempt`}><Button variant="outline">Retake whole quiz</Button></Link>
            <Link href="/study-tools"><Button variant="outline">Study Planner (coming soon)</Button></Link>
            <Button variant="outline" onClick={() => void exportPaper("pdf")}>Export exam paper PDF</Button>
            <Button variant="outline" onClick={() => void exportPaper("docx")}>Export exam paper DOCX</Button>
          </div>
          {exportError ? <ErrorMessage message={exportError} /> : null}
          {error ? <ErrorMessage message={error} /> : null}
        </>
      ) : null}
    </main>
  );
}

export function QuizLoadingState({ title }: { title: string }) {
  return <p role="status" aria-live="polite">{title}</p>;
}
