import { QuizResultsPage } from "@/components/study/quiz-pages";

export default async function QuizResultsRoute({
  params,
}: {
  params: Promise<{ id: string; attemptId: string }>;
}) {
  const { id, attemptId } = await params;
  return <QuizResultsPage quizId={Number(id)} attemptId={Number(attemptId)} />;
}
