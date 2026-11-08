import { QuizBuilderPage } from "@/components/study/quiz-pages";

export default async function NewQuizPage({
  searchParams,
}: {
  searchParams: Promise<{ documentId?: string; count?: string; title?: string }>;
}) {
  const { documentId, count, title } = await searchParams;
  const parsedDocumentId = documentId ? Number(documentId) : undefined;
  const parsedCount = count ? Number(count) : undefined;
  return (
    <QuizBuilderPage
      prefillDocumentId={Number.isInteger(parsedDocumentId) ? parsedDocumentId : undefined}
      prefillQuestionCount={
        parsedCount !== undefined && Number.isInteger(parsedCount) && parsedCount > 0
          ? parsedCount
          : undefined
      }
      prefillTitle={title}
    />
  );
}
