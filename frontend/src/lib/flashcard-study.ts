import { apiClient, unwrapApiResult } from "@/lib/api";
import { normalizeApiError } from "@/lib/errors";

type JsonRecord = Record<string, unknown>;

export type Flashcard = {
  id: number;
  front: string;
  back: string;
  sourcePage: number;
  documentId: number;
  deck: string | null;
  interval: number;
  repetitions: number;
  suspended: boolean;
};

export type FlashcardDeckStats = {
  documentId: number;
  deck: string;
  total: number;
  due: number;
  suspended: number;
};

export type FlashcardRating = "Again" | "Hard" | "Good" | "Easy";

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function requiredNumber(value: unknown, label: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`The flashcard response did not contain a valid ${label}.`);
  }
  return value;
}

function cardFrom(value: unknown): Flashcard {
  if (!isRecord(value)) throw new Error("The flashcard response was invalid.");
  return {
    id: requiredNumber(value.id, "card id"),
    front: typeof value.front === "string" ? value.front : "",
    back: typeof value.back === "string" ? value.back : "",
    sourcePage: requiredNumber(value.source_page, "source page"),
    documentId: requiredNumber(value.document_id, "document id"),
    deck: typeof value.deck === "string" ? value.deck : null,
    interval: typeof value.interval === "number" ? value.interval : 0,
    repetitions: typeof value.repetitions === "number" ? value.repetitions : 0,
    suspended: value.suspended === true,
  };
}

export async function getDueFlashcards(
  documentId?: number,
): Promise<Flashcard[]> {
  const result =
    documentId === undefined
      ? await apiClient.GET("/study/flashcards/due")
      : await apiClient.GET("/study/flashcards/due", {
          params: { query: { document_id: documentId } },
        });
  const data: unknown = unwrapApiResult(result);
  if (!Array.isArray(data)) throw new Error("The due flashcards response was invalid.");
  return data.map(cardFrom);
}

export async function getFlashcardDeckStats(
  documentId: number,
): Promise<FlashcardDeckStats> {
  const result = await apiClient.GET(
    "/study/documents/{document_id}/flashcards/stats",
    { params: { path: { document_id: documentId } } },
  );
  const data: unknown = unwrapApiResult(result);
  if (!isRecord(data)) throw new Error("The flashcard deck response was invalid.");
  return {
    documentId: requiredNumber(data.document_id, "document id"),
    deck: typeof data.deck === "string" ? data.deck : "Flashcards",
    total: requiredNumber(data.total, "card count"),
    due: requiredNumber(data.due, "due card count"),
    suspended: typeof data.suspended === "number" ? data.suspended : 0,
  };
}

export async function generateFlashcards(
  documentId: number,
): Promise<{ created: number }> {
  const result = await apiClient.POST(
    "/study/documents/{document_id}/flashcards/generate",
    { params: { path: { document_id: documentId } } },
  );
  const data: unknown = unwrapApiResult(result);
  if (!isRecord(data) || typeof data.created !== "number") {
    throw new Error("The flashcard generation response was invalid.");
  }
  return { created: data.created };
}

export async function reviewFlashcard(
  cardId: number,
  rating: FlashcardRating,
): Promise<{ interval: number | null }> {
  const result = await apiClient.POST(
    "/study/flashcards/{card_id}/review",
    {
      params: { path: { card_id: cardId } },
      body: { rating },
    },
  );
  const data: unknown = unwrapApiResult(result);
  if (!isRecord(data)) throw new Error("The flashcard review response was invalid.");
  const card = isRecord(data.card) ? data.card : null;
  return {
    interval: card && typeof card.interval === "number" ? card.interval : null,
  };
}

export async function suspendFlashcard(cardId: number): Promise<void> {
  const result = await apiClient.PATCH("/study/flashcards/{card_id}", {
    params: { path: { card_id: cardId } },
    body: { suspended: true },
  });
  unwrapApiResult(result);
}

export async function deleteFlashcard(cardId: number): Promise<void> {
  const result = await apiClient.DELETE("/study/flashcards/{card_id}", {
    params: { path: { card_id: cardId } },
  });
  if (!result.response.ok) {
    throw normalizeApiError(result.response.status, result.error);
  }
}
