import { QuizAttemptPage } from "@/components/study/quiz-pages";

export default async function QuizAttemptRoute({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <QuizAttemptPage quizId={Number(id)} />;
}
