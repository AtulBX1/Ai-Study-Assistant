"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { PageHeader } from "@/components/ui/page-header";
import { getDueFlashcards, getFlashcardDeckStats, generateFlashcards, reviewFlashcard, suspendFlashcard, deleteFlashcard, type Flashcard, type FlashcardDeckStats, type FlashcardRating } from "@/lib/flashcard-study";
import { listDocuments, type DocumentRecord } from "@/lib/documents";

const ratings: FlashcardRating[] = ["Again", "Hard", "Good", "Easy"];

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : "The flashcard request could not be completed.";
}

export function FlashcardDecksPage() {
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [decks, setDecks] = useState<Record<number, FlashcardDeckStats>>({});
  const [newCounts, setNewCounts] = useState<Record<number, number>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [generating, setGenerating] = useState<number | null>(null);
  const [notice, setNotice] = useState<Record<number, string>>({});

  const load = useCallback(async () => {
    setError(null);
    const docs = (await listDocuments(0, 100)).filter((document) => document.status === "ready");
    const [stats, dueCards] = await Promise.all([
      Promise.all(docs.map((document) => getFlashcardDeckStats(document.id))),
      getDueFlashcards(),
    ]);
    setDocuments(docs);
    setDecks(Object.fromEntries(stats.map((item) => [item.documentId, item])));
    setNewCounts(
      dueCards.reduce<Record<number, number>>((counts, card) => {
        if (card.repetitions === 0) counts[card.documentId] = (counts[card.documentId] ?? 0) + 1;
        return counts;
      }, {}),
    );
  }, []);

  useEffect(() => {
    let active = true;
    void load()
      .catch((reason: unknown) => { if (active) setError(messageOf(reason)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [load]);

  async function generate(document: DocumentRecord) {
    setGenerating(document.id);
    setNotice((current) => ({ ...current, [document.id]: "" }));
    try {
      const result = await generateFlashcards(document.id);
      setNotice((current) => ({
        ...current,
        [document.id]: result.created
          ? `Generated ${result.created} new card${result.created === 1 ? "" : "s"}.`
          : "No new cards could be generated from this document. It may not contain any new grounded facts.",
      }));
      await load();
    } catch (reason) {
      setNotice((current) => ({ ...current, [document.id]: messageOf(reason) }));
    } finally {
      setGenerating(null);
    }
  }

  return (
    <main className="mx-auto w-full max-w-5xl px-4 py-8 sm:px-6">
      <PageHeader
        title="Flashcards"
        description="Review grounded cards using spaced repetition."
        action={<Link href="/flashcards/review"><Button>Review due cards</Button></Link>}
      />
      {loading ? <p role="status" aria-live="polite">Loading flashcard decks…</p> : null}
      {error ? <ErrorState title="Could not load decks" description={error} /> : null}
      {!loading && !error && documents.length === 0 ? (
        <EmptyState title="No ready documents" description="Ready documents appear here as flashcard decks." />
      ) : null}
      {!loading && !error && documents.length > 0 && documents.every((document) => (decks[document.id]?.total ?? 0) === 0) ? (
        <EmptyState title="No flashcards yet" description="Generate cards from a document to start reviewing." />
      ) : null}
      <div className="grid gap-4 md:grid-cols-2">
        {documents.map((document) => {
          const stats = decks[document.id];
          return (
            <Card key={document.id}>
              <CardContent className="space-y-4 p-5">
                <h2 className="font-semibold">{document.title}</h2>
                <div className="grid grid-cols-3 gap-2 text-sm">
                  <p>Total <strong className="block">{stats?.total ?? "—"}</strong></p>
                  <p>Due today <strong className="block">{stats?.due ?? "—"}</strong></p>
                  <p>New <strong className="block">{newCounts[document.id] ?? 0}</strong></p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button disabled={generating === document.id} onClick={() => void generate(document)}>
                    {generating === document.id ? "Generating cards…" : "Generate cards"}
                  </Button>
                  <Link href={`/flashcards/review?documentId=${document.id}`}><Button variant="outline">Review this deck</Button></Link>
                </div>
                {generating === document.id ? (
                  <div role="progressbar" aria-label="Flashcard generation progress" aria-valuetext="Generating cards">
                    <div className="h-2 overflow-hidden rounded-full bg-muted">
                      <div className="h-full w-1/3 animate-pulse rounded-full bg-primary" />
                    </div>
                  </div>
                ) : null}
                <p className="text-sm" aria-live="polite">{notice[document.id]}</p>
              </CardContent>
            </Card>
          );
        })}
      </div>
    </main>
  );
}

export function FlashcardReviewPage({ documentId }: { documentId?: number }) {
  const [cards, setCards] = useState<Flashcard[]>([]);
  const [position, setPosition] = useState(0);
  const [flipped, setFlipped] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [intervalMessage, setIntervalMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [reviewed, setReviewed] = useState(0);
  const [ratingCounts, setRatingCounts] = useState<Record<FlashcardRating, number>>({
    Again: 0,
    Hard: 0,
    Good: 0,
    Easy: 0,
  });
  const reviewLock = useRef(false);
  const currentCard = cards[position];

  useEffect(() => {
    let active = true;
    void getDueFlashcards(documentId)
      .then((due) => { if (active) setCards(due); })
      .catch((reason: unknown) => { if (active) setError(messageOf(reason)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [documentId]);

  const flip = useCallback(() => setFlipped((value) => !value), []);

  const rate = useCallback(async (rating: FlashcardRating) => {
    if (!currentCard || reviewLock.current || !flipped) return;
    reviewLock.current = true;
    setBusy(true);
    setError(null);
    try {
      const result = await reviewFlashcard(currentCard.id, rating);
      setRatingCounts((counts) => ({ ...counts, [rating]: counts[rating] + 1 }));
      setReviewed((count) => count + 1);
      setIntervalMessage(
        result.interval === null
          ? `${rating} recorded. The next interval was not returned by the API.`
          : `${rating} recorded. Next due in ${result.interval} day${result.interval === 1 ? "" : "s"}.`,
      );
      setFlipped(false);
      setPosition((index) => index + 1);
    } catch (reason) {
      setError(messageOf(reason));
    } finally {
      reviewLock.current = false;
      setBusy(false);
    }
  }, [currentCard, flipped]);

  useEffect(() => {
    if (!currentCard || loading) return;
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target;
      if (target instanceof HTMLElement && ["INPUT", "TEXTAREA", "SELECT", "BUTTON", "A"].includes(target.tagName)) return;
      if (event.code === "Space") {
        event.preventDefault();
        flip();
      }
      if (flipped && /^[1-4]$/.test(event.key)) {
        const rating = ratings[Number(event.key) - 1];
        if (rating) void rate(rating);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [currentCard, flip, flipped, loading, rate]);

  async function suspend() {
    if (!currentCard || busy) return;
    setBusy(true);
    try {
      await suspendFlashcard(currentCard.id);
      setCards((items) => items.filter((item) => item.id !== currentCard.id));
      setFlipped(false);
    } catch (reason) {
      setError(messageOf(reason));
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!currentCard || busy || !window.confirm("Delete this flashcard and its review history?")) return;
    setBusy(true);
    try {
      await deleteFlashcard(currentCard.id);
      setCards((items) => items.filter((item) => item.id !== currentCard.id));
      setFlipped(false);
    } catch (reason) {
      setError(messageOf(reason));
    } finally {
      setBusy(false);
    }
  }

  const progress = cards.length ? Math.min(100, Math.round((reviewed / (reviewed + cards.length - position)) * 100)) : 100;

  return (
    <main className="mx-auto w-full max-w-3xl px-4 py-8 sm:px-6">
      <PageHeader title="Flashcard review" description="Recall first, then reveal the grounded answer." />
      {loading ? <p role="status" aria-live="polite">Loading due cards…</p> : null}
      {error && !currentCard ? <ErrorState title="Could not load cards" description={error} /> : null}
      {!loading && !error && cards.length === 0 ? (
        <EmptyState title="Nothing due today" description="You are all caught up. Generate cards or come back when a card is due." action={<Link href="/flashcards"><Button>Browse decks</Button></Link>} />
      ) : null}
      {!loading && cards.length > 0 && !currentCard ? (
        <Card>
          <CardContent className="space-y-3 p-6">
            <h2 className="text-xl font-semibold">Session complete</h2>
            <p aria-live="polite">Cards reviewed: {reviewed}</p>
            <p>Again: {ratingCounts.Again} · Hard: {ratingCounts.Hard} · Good: {ratingCounts.Good} · Easy: {ratingCounts.Easy}</p>
            {intervalMessage ? <p role="status" aria-live="polite">{intervalMessage}</p> : null}
            <Link href="/flashcards"><Button>Back to decks</Button></Link>
          </CardContent>
        </Card>
      ) : null}
      {currentCard ? (
        <>
          <div className="mb-4">
            <div className="h-2 overflow-hidden rounded-full bg-muted" role="progressbar" aria-label="Flashcard session progress" aria-valuenow={progress} aria-valuemin={0} aria-valuemax={100}>
              <div className="h-full bg-primary transition-all" style={{ width: `${progress}%` }} />
            </div>
            <p className="mt-1 text-xs text-muted-foreground" aria-live="polite">Card {Math.min(position + 1, cards.length)} of {cards.length}</p>
          </div>
          <button type="button" className="w-full text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary" aria-label={flipped ? "Show flashcard front" : "Flip flashcard to show answer"} onClick={flip}>
            <Card className="min-h-64">
              <CardContent className="grid min-h-64 place-items-center p-8 text-center">
                <div>
                  <p className="mb-4 text-xs uppercase tracking-wide text-muted-foreground">{flipped ? "Answer" : "Prompt"}</p>
                  <p className="text-xl font-medium">{flipped ? currentCard.back : currentCard.front}</p>
                  {!flipped ? <p className="mt-5 text-sm text-muted-foreground">Click or press Space to flip</p> : null}
                  {flipped ? <p className="mt-5 text-sm text-muted-foreground">Source: page {currentCard.sourcePage}</p> : null}
                </div>
              </CardContent>
            </Card>
          </button>
          {flipped ? (
            <div className="mt-4">
              <Link className="text-sm text-primary underline" href={`/chat/${currentCard.documentId}?page=${currentCard.sourcePage}`}>Open source page {currentCard.sourcePage}</Link>
              <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
                {ratings.map((rating, index) => (
                  <Button key={rating} disabled={busy} variant={index === 2 ? "default" : "outline"} onClick={() => void rate(rating)}>{rating} ({index + 1})</Button>
                ))}
              </div>
            </div>
          ) : null}
          <div className="mt-4 flex flex-wrap gap-2">
            <Button variant="outline" disabled={busy} onClick={() => void suspend()}>Suspend card</Button>
            <Button variant="outline" disabled={busy} onClick={() => void remove()}>Delete card</Button>
          </div>
          {intervalMessage ? <p className="mt-3 text-sm" role="status" aria-live="polite">{intervalMessage}</p> : null}
          {error ? <p className="mt-3 text-sm text-danger" role="alert">{error}</p> : null}
        </>
      ) : null}
    </main>
  );
}
