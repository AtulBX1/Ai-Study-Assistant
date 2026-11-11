import { QuizBuilderPage } from "@/components/study/quiz-pages";

export default async function NewQuizPage({
  searchParams,
}: {
  searchParams: Promise<{ documentId?: string; count?: string; title?: string; syllabusId?: string; topicId?: string }>;
}) {
  const { documentId, count, title, syllabusId, topicId } = await searchParams;
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
      prefillSyllabusId={syllabusId ? Number(syllabusId) : undefined}
      prefillTopicId={topicId ? Number(topicId) : undefined}
    />
  );
}
