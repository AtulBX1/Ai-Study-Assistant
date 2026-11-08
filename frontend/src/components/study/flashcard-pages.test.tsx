import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  FlashcardDecksPage,
  FlashcardReviewPage,
} from "@/components/study/flashcard-pages";

const mocks = vi.hoisted(() => ({
  listDocuments: vi.fn(),
  getDueFlashcards: vi.fn(),
  getFlashcardDeckStats: vi.fn(),
  generateFlashcards: vi.fn(),
  reviewFlashcard: vi.fn(),
  suspendFlashcard: vi.fn(),
  deleteFlashcard: vi.fn(),
}));

vi.mock("@/lib/documents", () => ({
  listDocuments: mocks.listDocuments,
}));

vi.mock("@/lib/flashcard-study", () => ({
  getDueFlashcards: mocks.getDueFlashcards,
  getFlashcardDeckStats: mocks.getFlashcardDeckStats,
  generateFlashcards: mocks.generateFlashcards,
  reviewFlashcard: mocks.reviewFlashcard,
  suspendFlashcard: mocks.suspendFlashcard,
  deleteFlashcard: mocks.deleteFlashcard,
}));

function card(id: number) {
  return {
    id,
    front: `Card front ${id}`,
    back: `Card back ${id}`,
    sourcePage: id + 2,
    documentId: 4,
    deck: "Course.pdf",
    interval: 0,
    repetitions: 0,
    suspended: false,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.listDocuments.mockResolvedValue([]);
  mocks.getDueFlashcards.mockResolvedValue([]);
  mocks.getFlashcardDeckStats.mockResolvedValue({
    documentId: 4,
    deck: "Course.pdf",
    total: 0,
    due: 0,
    suspended: 0,
  });
  mocks.reviewFlashcard.mockResolvedValue({ interval: 3 });
});

afterEach(cleanup);

describe("flashcard screens", () => {
  it("uses Space to flip and keys 1-4 for the matching server ratings", async () => {
    mocks.getDueFlashcards.mockResolvedValue([card(1), card(2), card(3), card(4)]);
    render(<FlashcardReviewPage />);
    await screen.findByText("Card front 1");

    const expected = ["Again", "Hard", "Good", "Easy"] as const;
    for (let index = 0; index < expected.length; index += 1) {
      const current = index + 1;
      if (current > 1) await screen.findByText(`Card front ${current}`);
      fireEvent.keyDown(window, { code: "Space", key: " " });
      expect(await screen.findByText(`Card back ${current}`)).toBeTruthy();
      if (current === 1) {
        expect(screen.getByRole("link", { name: "Open source page 3" }).getAttribute("href"))
          .toBe("/chat/4?page=3");
      }
      fireEvent.keyDown(window, { key: String(current) });
      await waitFor(() => {
        expect(mocks.reviewFlashcard).toHaveBeenNthCalledWith(current, current, expected[index]);
      });
    }

    expect(await screen.findByText("Session complete")).toBeTruthy();
    expect(screen.getByText("Cards reviewed: 4")).toBeTruthy();
    expect(screen.getByText("Again: 1 · Hard: 1 · Good: 1 · Easy: 1")).toBeTruthy();
    expect(screen.getAllByText(/Next due in 3 days/).length).toBeGreaterThan(0);
  });

  it("shows a clear state when no cards are due", async () => {
    render(<FlashcardReviewPage />);
    expect(await screen.findByText("Nothing due today")).toBeTruthy();
  });

  it("shows the empty deck state when there are no ready documents", async () => {
    render(<FlashcardDecksPage />);
    expect(await screen.findByText("No ready documents")).toBeTruthy();
  });
});
