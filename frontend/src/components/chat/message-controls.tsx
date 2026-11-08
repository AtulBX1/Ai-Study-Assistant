"use client";

import { useEffect, useRef, useState } from "react";
import { BookOpen, Pause, Play, ThumbsDown, ThumbsUp, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import type { ChatExplanation, EvidenceChunk } from "@/lib/chat";
import { getChatSession, submitChatFeedback } from "@/lib/chat";
import { groundingLevel, speechLanguage, stripMarkdownAndCitations } from "@/lib/study-utils";

export function GroundingBadge({ score }: { score: number }) {
  const grounding = groundingLevel(score);
  const exactScore = String(score);
  return (
    <span
      className={`inline-flex rounded-full border px-2 py-1 text-[11px] font-medium ${grounding.className}`}
      title={`Grounding score: ${exactScore}`}
      aria-label={`Grounding score ${exactScore}: ${grounding.label}`}
    >
      {grounding.label}
    </span>
  );
}

export function FeedbackControls({
  messageId,
  storedFeedback,
  storedReason,
  onSaved,
}: {
  messageId?: number;
  storedFeedback?: "thumbs_up" | "thumbs_down" | null;
  storedReason?: string | null;
  onSaved: (feedback: "thumbs_up" | "thumbs_down", reason?: string) => void;
}) {
  const [dialogOpen, setDialogOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submitting = useRef(false);

  const send = async (feedback: "thumbs_up" | "thumbs_down", feedbackReason?: string) => {
    if (messageId === undefined || storedFeedback || submitting.current) return;
    submitting.current = true;
    setPending(true);
    setError(null);
    try {
      await submitChatFeedback(messageId, feedback, feedbackReason);
      onSaved(feedback, feedbackReason);
      setDialogOpen(false);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not save your feedback.");
    } finally {
      submitting.current = false;
      setPending(false);
    }
  };

  return (
    <div className="mt-3 flex flex-wrap items-center gap-1 border-t border-border/70 pt-2">
      <Button
        type="button"
        size="sm"
        variant={storedFeedback === "thumbs_up" ? "default" : "ghost"}
        aria-label="Helpful answer"
        aria-pressed={storedFeedback === "thumbs_up"}
        disabled={messageId === undefined || Boolean(storedFeedback) || pending}
        onClick={() => void send("thumbs_up")}
      >
        <ThumbsUp size={15} aria-hidden="true" />
        Helpful
      </Button>
      <Button
        type="button"
        size="sm"
        variant={storedFeedback === "thumbs_down" ? "default" : "ghost"}
        aria-label="Not helpful answer"
        aria-pressed={storedFeedback === "thumbs_down"}
        disabled={messageId === undefined || Boolean(storedFeedback) || pending}
        onClick={() => setDialogOpen(true)}
      >
        <ThumbsDown size={15} aria-hidden="true" />
        Not helpful
      </Button>
      {storedFeedback ? (
        <span className="text-xs text-muted-foreground" role="status">
          Feedback saved{storedFeedback === "thumbs_down" && storedReason ? `: ${storedReason}` : "."}
        </span>
      ) : null}
      {error ? <p role="alert" className="w-full text-xs text-danger">{error}</p> : null}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen} title="What was wrong with this answer?">
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            void send("thumbs_down", reason.trim() || undefined);
          }}
        >
          <label className="block text-sm" htmlFor={`feedback-reason-${messageId}`}>
            Optional reason
            <textarea
              id={`feedback-reason-${messageId}`}
              value={reason}
              maxLength={1000}
              onChange={(event) => setReason(event.target.value)}
              className="mt-2 min-h-24 w-full rounded-md border border-border bg-background p-3"
            />
          </label>
          {error ? <p role="alert" className="text-sm text-danger">{error}</p> : null}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={() => setDialogOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={pending}>
              {pending ? "Saving…" : "Send feedback"}
            </Button>
          </div>
        </form>
      </Dialog>
    </div>
  );
}

function score(value: number | null | undefined): string {
  return value === undefined || value === null ? "Not available" : String(value);
}

export function ExplanationDrawer({
  sessionId,
  messageId,
  explanation,
  onChunkClick,
}: {
  sessionId: number | null;
  messageId?: number;
  explanation: ChatExplanation;
  onChunkClick: (page: number, title: string | undefined, text: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [loaded, setLoaded] = useState<ChatExplanation | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || loaded || sessionId === null || messageId === undefined) return;
    let active = true;
    setLoading(true);
    void getChatSession(sessionId)
      .then((session) => {
        const message = session.messages.find((item) => item.id === messageId);
        if (!message) throw new Error("The saved explanation is unavailable for this answer.");
        if (active) setLoaded(message.explanation);
      })
      .catch((caught: unknown) => {
        if (active) setError(caught instanceof Error ? caught.message : "Could not load the explanation.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [loaded, messageId, open, sessionId]);

  useEffect(() => {
    if (!open) return;
    const closeOnEscape = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [open]);

  const data = loaded ?? explanation;
  return (
    <>
      <Button
        type="button"
        size="sm"
        variant="ghost"
        aria-label="Why this answer"
        onClick={() => {
          setOpen(true);
          setError(null);
        }}
      >
        <BookOpen size={15} aria-hidden="true" />
        Why this answer
      </Button>
      {open ? (
        <aside
          role="dialog"
          aria-label="Why this answer"
          className="fixed inset-y-0 right-0 z-40 w-full max-w-md overflow-y-auto border-l border-border bg-card p-5 text-card-foreground shadow-2xl"
        >
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-lg font-semibold">Why this answer</h2>
            <Button type="button" variant="ghost" size="sm" aria-label="Close drawer" onClick={() => setOpen(false)}>
              <X size={18} aria-hidden="true" />
            </Button>
          </div>
          {loading ? <p role="status" className="mt-4 text-sm">Loading explanation…</p> : null}
          {error ? <p role="alert" className="mt-4 text-sm text-danger">{error}</p> : null}
          <dl className="mt-4 grid grid-cols-2 gap-3 text-sm">
            <div><dt className="text-muted-foreground">Provider</dt><dd>{data.provider ?? "Not available"}</dd></div>
            <div><dt className="text-muted-foreground">Answer mode</dt><dd>{data.mode ?? "Not available"}</dd></div>
            <div><dt className="text-muted-foreground">Retrieval mode</dt><dd>hybrid</dd></div>
            <div><dt className="text-muted-foreground">Latency</dt><dd>{data.latency_ms === undefined ? "Not available" : `${data.latency_ms.toFixed(2)} ms`}</dd></div>
          </dl>
          <section className="mt-6">
            <h3 className="font-semibold">Retrieved evidence</h3>
            {data.chunks?.length ? (
              <ul className="mt-2 space-y-3">
                {data.chunks.map((chunk, index) => (
                  <EvidenceItem
                    key={`${chunk.chunk_id ?? index}-${index}`}
                    chunk={chunk}
                    onChunkClick={onChunkClick}
                  />
                ))}
              </ul>
            ) : (
              <p className="mt-2 text-sm text-muted-foreground">No retrieved chunks were saved.</p>
            )}
          </section>
          <section className="mt-6">
            <h3 className="font-semibold">Sentences used for grounding</h3>
            {data.chunks?.some((chunk) => chunk.used_sentences?.length) ? (
              <ul className="mt-2 space-y-2 text-sm">
                {data.chunks.flatMap((chunk, chunkIndex) =>
                  (chunk.used_sentences ?? []).map((sentence, sentenceIndex) => (
                    <li key={`${chunk.chunk_id ?? chunkIndex}-${sentenceIndex}`}>
                      <span className="font-medium">
                        {sentence.supported ? "Supported by evidence" : "Not supported"}
                      </span>
                      <p className="mt-1">{sentence.sentence}</p>
                    </li>
                  )),
                )}
              </ul>
            ) : (
              <p className="mt-2 text-sm text-muted-foreground">
                Sentence-to-chunk usage was not included in the saved explanation.
              </p>
            )}
          </section>
          <section className="mt-6">
            <h3 className="font-semibold">Answer sentences</h3>
            {data.answer_sentences?.length ? (
              <ul className="mt-2 list-disc space-y-2 pl-5 text-sm">
                {data.answer_sentences.map((sentence, index) => <li key={`${index}-${sentence}`}>{sentence}</li>)}
              </ul>
            ) : (
              <p className="mt-2 text-sm text-muted-foreground">No sentence-level usage data was saved.</p>
            )}
          </section>
        </aside>
      ) : null}
    </>
  );
}

function EvidenceItem({
  chunk,
  onChunkClick,
}: {
  chunk: EvidenceChunk;
  onChunkClick: (page: number, title: string | undefined, text: string) => void;
}) {
  return (
    <li className="rounded-md border border-border p-3 text-sm">
      <p className="font-medium">
        {chunk.document_title ?? "Source"} · Page {chunk.page ?? "—"}
        {` · Section: ${chunk.section ?? "Not provided by the backend"}`}
      </p>
      <p className="mt-2 whitespace-pre-wrap text-muted-foreground">{chunk.text ?? "No passage text available."}</p>
      <dl className="mt-2 grid grid-cols-2 gap-2 text-xs">
        <div><dt className="text-muted-foreground">Retrieval score</dt><dd>{score(chunk.retrieval_score)}</dd></div>
        <div><dt className="text-muted-foreground">Rerank score</dt><dd>{score(chunk.rerank_score)}</dd></div>
      </dl>
      {chunk.page !== undefined && chunk.text ? (
        <button
          type="button"
          data-keep-pdf-highlight
          className="mt-3 text-primary underline underline-offset-2"
          onClick={() => onChunkClick(chunk.page!, chunk.document_title, chunk.text!)}
        >
          Go to page {chunk.page} and highlight
        </button>
      ) : null}
    </li>
  );
}

type RecognitionResult = { transcript: string };
type RecognitionEvent = { resultIndex: number; results: ArrayLike<ArrayLike<RecognitionResult> & { isFinal: boolean }> };
type RecognitionErrorEvent = { error: string };
type BrowserRecognition = {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  onresult: ((event: RecognitionEvent) => void) | null;
  onerror: ((event: RecognitionErrorEvent) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
};
type RecognitionConstructor = new () => BrowserRecognition;

declare global {
  interface Window {
    SpeechRecognition?: RecognitionConstructor;
    webkitSpeechRecognition?: RecognitionConstructor;
  }
}

export function VoiceInput({
  language,
  onTranscript,
}: {
  language: "English" | "Hindi" | "Punjabi";
  onTranscript: (value: string) => void;
}) {
  const [recognitionConstructor, setRecognitionConstructor] = useState<RecognitionConstructor | null>(null);
  const [recognition, setRecognition] = useState<BrowserRecognition | null>(null);
  const [listening, setListening] = useState(false);
  const [privacyOpen, setPrivacyOpen] = useState(false);
  const [pendingStart, setPendingStart] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setRecognitionConstructor(
      () => window.SpeechRecognition ?? window.webkitSpeechRecognition ?? null,
    );
  }, []);

  const start = () => {
    if (!recognitionConstructor) return;
    setError(null);
    const activeRecognition = new recognitionConstructor();
    activeRecognition.lang = speechLanguage(language);
    activeRecognition.interimResults = true;
    activeRecognition.continuous = false;
    activeRecognition.onresult = (event) => {
      const transcript = Array.from(event.results)
        .map((result) => result[0]?.transcript ?? "")
        .join("");
      onTranscript(transcript);
    };
    activeRecognition.onerror = (event) => {
      setListening(false);
      setError(
        event.error === "not-allowed" || event.error === "service-not-allowed"
          ? "Microphone permission was denied. Allow microphone access in your browser and try again."
          : `Speech recognition failed: ${event.error}.`,
      );
    };
    activeRecognition.onend = () => setListening(false);
    setRecognition(activeRecognition);
    try {
      activeRecognition.start();
      setListening(true);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not start speech recognition.");
    }
  };

  if (!recognitionConstructor) return null;
  return (
    <>
      <div className="flex items-center gap-2">
        <Button
          type="button"
          variant="outline"
          aria-label={listening ? "Stop voice input" : "Start voice input"}
          onClick={() => {
            if (listening) {
              recognition?.stop();
              setListening(false);
            } else if (window.localStorage.getItem("study-voice-notice-seen") === "1") {
              start();
            } else {
              setPendingStart(true);
              setPrivacyOpen(true);
            }
          }}
        >
          {listening ? "Stop microphone" : "Speak"}
        </Button>
        {error ? <span role="alert" className="text-xs text-danger">{error}</span> : null}
        <span className="sr-only">
          Voice input uses your browser; some browsers send recognition audio to their vendor&apos;s servers.
        </span>
      </div>
      <Dialog open={privacyOpen} onOpenChange={setPrivacyOpen} title="Browser voice privacy">
        <p className="text-sm">
          Voice uses your browser. On some browsers, speech recognition sends audio to the browser
          vendor&apos;s servers. Audio is not sent to this study assistant&apos;s server.
        </p>
        <div className="mt-4 flex justify-end gap-2">
          <Button type="button" variant="outline" onClick={() => setPendingStart(false)}>
            Cancel
          </Button>
          <Button
            type="button"
            onClick={() => {
              window.localStorage.setItem("study-voice-notice-seen", "1");
              setPrivacyOpen(false);
              if (pendingStart) start();
              setPendingStart(false);
            }}
          >
            Continue
          </Button>
        </div>
      </Dialog>
    </>
  );
}

export function ReadAloud({ content, language }: { content: string; language: "English" | "Hindi" | "Punjabi" }) {
  const [available, setAvailable] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [paused, setPaused] = useState(false);
  const lang = speechLanguage(language);

  useEffect(() => {
    setAvailable(
      typeof window.speechSynthesis?.speak === "function" &&
        typeof window.SpeechSynthesisUtterance === "function",
    );
    return () => {
      if (typeof window.speechSynthesis?.cancel === "function") {
        window.speechSynthesis.cancel();
      }
    };
  }, []);

  if (!available) return null;
  const speak = () => {
    const text = stripMarkdownAndCitations(content);
    if (!text) return;
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = lang;
    const voices = window.speechSynthesis.getVoices();
    utterance.voice =
      voices.find((voice) => voice.lang.toLocaleLowerCase() === lang.toLocaleLowerCase()) ??
      voices.find((voice) => voice.lang.toLocaleLowerCase().startsWith(lang.slice(0, 2))) ??
      null;
    utterance.onend = () => {
      setPlaying(false);
      setPaused(false);
    };
    utterance.onerror = () => {
      setPlaying(false);
      setPaused(false);
    };
    window.speechSynthesis.speak(utterance);
    setPlaying(true);
    setPaused(false);
  };
  const stop = () => {
    window.speechSynthesis.cancel();
    setPlaying(false);
    setPaused(false);
  };

  return (
    <div className="flex items-center gap-1">
      {!playing ? (
        <Button type="button" size="sm" variant="ghost" aria-label="Read aloud" onClick={speak}>
          <Play size={14} aria-hidden="true" /> Read aloud
        </Button>
      ) : (
        <>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            aria-label={paused ? "Resume reading" : "Pause reading"}
            onClick={() => {
              if (paused) window.speechSynthesis.resume();
              else window.speechSynthesis.pause();
              setPaused(!paused);
            }}
          >
            {paused ? <Play size={14} aria-hidden="true" /> : <Pause size={14} aria-hidden="true" />}
            {paused ? "Resume" : "Pause"}
          </Button>
          <Button type="button" size="sm" variant="ghost" aria-label="Stop reading" onClick={stop}>
            Stop
          </Button>
        </>
      )}
    </div>
  );
}
