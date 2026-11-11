import { FlashcardDecksPage } from "@/components/study/flashcard-pages";

export default async function FlashcardsPage({ searchParams }: { searchParams: Promise<{ documentId?: string; topic?: string }> }) {
  const params = await searchParams;
  return <FlashcardDecksPage prefillDocumentId={params.documentId ? Number(params.documentId) : undefined} prefillTopic={params.topic} />;
}
