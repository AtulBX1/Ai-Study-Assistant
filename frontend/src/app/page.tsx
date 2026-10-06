"use client";

import { useEffect, useState } from "react";
import { ArrowRight, BookOpenText, BrainCircuit, Layers3 } from "lucide-react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { getHealth, type ApiHealth } from "@/lib/api";

export default function Home() {
  const [health, setHealth] = useState<ApiHealth | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    getHealth()
      .then((result) => {
        if (active) setHealth(result);
      })
      .catch((error: unknown) => {
        if (active) {
          setApiError(
            error instanceof Error ? error.message : "The API is unavailable.",
          );
        }
      });
    return () => {
      active = false;
    };
  }, []);

  return (
    <main className="min-h-screen overflow-hidden">
      <div className="mx-auto flex min-h-screen max-w-7xl flex-col px-6">
        <header className="flex h-20 items-center justify-between border-b border-border/70">
          <Link href="/" className="flex items-center gap-2 font-semibold tracking-tight">
            <span className="grid size-9 place-items-center rounded-xl bg-primary text-primary-foreground">
              <BrainCircuit aria-hidden="true" size={20} />
            </span>
            <span>Study<span className="text-primary">Mate</span></span>
          </Link>
          <span className="rounded-full border border-border px-3 py-1 text-xs text-muted-foreground">
            NLP study companion
          </span>
        </header>

        <section className="grid flex-1 items-center gap-14 py-16 lg:grid-cols-[1.1fr_0.9fr] lg:py-24">
          <div>
            <p className="mb-6 inline-flex items-center gap-2 rounded-full bg-primary/10 px-3 py-1.5 text-sm font-medium text-primary">
              <BookOpenText size={16} aria-hidden="true" />
              Learn from your course material
            </p>
            <h1 className="max-w-2xl text-5xl font-semibold leading-[1.08] tracking-tight sm:text-6xl">
              Your PDFs, turned into{" "}
              <span className="text-primary">understanding.</span>
            </h1>
            <p className="mt-6 max-w-xl text-lg leading-8 text-muted-foreground">
              Ask questions grounded in your study documents and create focused
              quizzes to check what you know. Every answer will point back to
              its source.
            </p>
            <div className="mt-9 flex flex-wrap items-center gap-4">
              <Button disabled>
                Getting started soon
                <ArrowRight size={16} aria-hidden="true" />
              </Button>
              <span className="text-sm text-muted-foreground">
                Project scaffold · Step 1
              </span>
            </div>
            <div className="mt-8 flex items-center gap-2 text-sm">
              <span
                className={`size-2 rounded-full ${health?.status === "ok" ? "bg-emerald-500" : apiError ? "bg-rose-500" : "animate-pulse bg-amber-400"}`}
                aria-hidden="true"
              />
              <span className="text-muted-foreground">
                {health?.status === "ok"
                  ? "API connected"
                  : apiError
                    ? "API unavailable"
                    : "Connecting to API…"}
              </span>
            </div>
          </div>

          <div className="relative mx-auto w-full max-w-lg">
            <div className="absolute -inset-8 rounded-[3rem] bg-primary/10 blur-3xl" />
            <div className="relative rounded-3xl border border-border bg-white/80 p-6 shadow-xl shadow-slate-200/60 backdrop-blur sm:p-8">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-muted-foreground">Your study space</p>
                  <h2 className="mt-1 text-xl font-semibold">A little more clarity</h2>
                </div>
                <span className="grid size-11 place-items-center rounded-2xl bg-primary/10 text-primary">
                  <Layers3 size={22} aria-hidden="true" />
                </span>
              </div>
              <div className="mt-8 space-y-3">
                <div className="rounded-2xl border border-border bg-white p-4">
                  <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
                    Ask your material
                  </p>
                  <p className="mt-2 text-sm">
                    “What is the difference between attention and self-attention?”
                  </p>
                </div>
                <div className="ml-8 rounded-2xl bg-primary/5 p-4">
                  <p className="text-xs font-medium text-primary">Grounded answer</p>
                  <p className="mt-2 text-sm leading-6 text-slate-600">
                    Find an explanation in your notes, with the document and page
                    cited for you to verify.
                  </p>
                  <div className="mt-3 inline-flex rounded-md border border-primary/15 bg-white px-2 py-1 text-xs text-primary">
                    Source · page citation
                  </div>
                </div>
              </div>
              <div className="mt-6 flex items-center justify-between border-t border-border pt-5 text-sm">
                <span className="text-muted-foreground">Designed for learning, not guessing.</span>
                <BrainCircuit className="text-primary" size={20} aria-hidden="true" />
              </div>
            </div>
          </div>
        </section>

        <footer className="border-t border-border/70 py-5 text-center text-xs text-muted-foreground">
          Built for curious minds · AI Study Assistant
        </footer>
      </div>
    </main>
  );
}
