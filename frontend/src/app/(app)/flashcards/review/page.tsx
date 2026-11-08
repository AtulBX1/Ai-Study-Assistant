import { FlashcardReviewPage } from "@/components/study/flashcard-pages";

export default async function FlashcardReviewRoute({
  searchParams,
}: {
  searchParams: Promise<{ documentId?: string }>;
}) {
  const { documentId } = await searchParams;
  const parsedId = documentId ? Number(documentId) : undefined;
  return <FlashcardReviewPage documentId={Number.isInteger(parsedId) ? parsedId : undefined} />;
}
