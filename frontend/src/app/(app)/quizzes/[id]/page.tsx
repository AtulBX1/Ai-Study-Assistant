import { QuizDetailPage } from "@/components/study/quiz-pages";

export default async function QuizPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <QuizDetailPage quizId={Number(id)} />;
}
