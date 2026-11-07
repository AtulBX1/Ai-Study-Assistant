"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, LoaderCircle, MessageSquarePlus, Send, Square } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Skeleton } from "@/components/ui/skeleton";
import { createChatSession, chatMessageUrl, parseChatEvent, type ChatOptions } from "@/lib/chat";
import { getDocument, getDocumentKeyTerms, listDocuments, type DocumentRecord } from "@/lib/documents";
import { useSSE } from "@/lib/hooks/use-sse";
import { MarkdownAnswer } from "@/components/chat/markdown-answer";
import type { PdfViewerHandle } from "@/components/chat/pdf-viewer";

const PdfViewer = dynamic(
  () => import("@/components/chat/pdf-viewer").then((module) => module.PdfViewer),
  { ssr: false, loading: () => <Skeleton className="h-full min-h-96 w-full" /> },
);

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  provider?: string;
  stopped?: boolean;
};

type StreamState = {
  key: string;
  url: string;
  body: string;
};

const modeOptions: Array<ChatOptions["mode"]> = [
  "normal",
  "simple",
  "in-depth",
  "exam-style",
];
const languageOptions: Array<ChatOptions["language"]> = [
  "English",
  "Hindi",
  "Punjabi",
];

function providerLabel(provider: string): string {
  return `Answered by: ${provider.replace(/^answered by:\s*/i, "")}`;
}

function PrivateBadge({ document }: { document: DocumentRecord }) {
  return document.is_private ? (
    <Badge className="border-amber-500/40 bg-amber-500/10 text-amber-800 dark:text-amber-200">
      Private
    </Badge>
  ) : (
    <Badge title="The current document API does not expose a privacy field.">
      Privacy unavailable
    </Badge>
  );
}

export function DocumentPicker() {
  const documents = useQuery({
    queryKey: ["documents", "chat-picker"],
    queryFn: () => listDocuments(0, 100),
  });

  if (documents.isLoading) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-20 w-full" />
        <Skeleton className="h-20 w-full" />
      </div>
    );
  }
  if (documents.isError) {
    return (
      <ErrorState
        title="Could not load your documents"
        description={documents.error.message}
        action={
          <Button
            type="button"
            variant="outline"
            onClick={() => void documents.refetch()}
          >
            Retry
          </Button>
        }
      />
    );
  }
  const available = documents.data ?? [];
  if (!available.length) {
    return (
      <EmptyState
        title="Add a document to start studying"
        description="Upload a PDF in your library, then open it here to ask questions."
        action={
          <Link
            href="/library"
            className="inline-flex h-10 items-center rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground"
          >
            Open library
          </Link>
        }
      />
    );
  }
  return (
    <ul className="space-y-3">
      {available.map((document) => (
        <li key={document.id}>
          <Link
            href={`/chat/${document.id}`}
            className="flex items-center justify-between gap-4 rounded-lg border border-border bg-card p-4 hover:border-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
          >
            <span className="min-w-0">
              <span className="block truncate font-medium">{document.title}</span>
              <span className="text-sm text-muted-foreground">
                {document.page_count ?? "Unknown"} pages · {document.status}
              </span>
            </span>
            {document.is_private ? <Badge>Private</Badge> : null}
          </Link>
        </li>
      ))}
    </ul>
  );
}

export function StudyScreen({ documentId }: { documentId: number }) {
  const documentQuery = useQuery({
    queryKey: ["document", documentId],
    queryFn: () => getDocument(documentId),
    enabled: Number.isInteger(documentId) && documentId > 0,
  });
  const documentsQuery = useQuery({
    queryKey: ["documents", "chat-switcher"],
    queryFn: () => listDocuments(0, 100),
  });
  const termsQuery = useQuery({
    queryKey: ["document-terms", documentId],
    queryFn: () => getDocumentKeyTerms(documentId),
    enabled: Number.isInteger(documentId) && documentId > 0,
  });
  const [sessionId, setSessionId] = useState<number | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [mode, setMode] = useState<ChatOptions["mode"]>("normal");
  const [language, setLanguage] = useState<ChatOptions["language"]>("English");
  const [request, setRequest] = useState<StreamState | null>(null);
  const [preparing, setPreparing] = useState(false);
  const [streamError, setStreamError] = useState<string | null>(null);
  const [lastQuestion, setLastQuestion] = useState("");
  const [split, setSplit] = useState(46);
  const [splitReady, setSplitReady] = useState(false);
  const [mobileTab, setMobileTab] = useState<"chat" | "pdf">("chat");
  const [isNearBottom, setIsNearBottom] = useState(true);
  const messagesElement = useRef<HTMLDivElement>(null);
  const splitElement = useRef<HTMLDivElement>(null);
  const divider = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);
  const viewer = useRef<PdfViewerHandle>(null);
  const streamOpened = useRef(false);
  const streamSequence = useRef(0);
  const streamBody = useMemo(
    () =>
      request
        ? { method: "POST" as const, body: request.body, key: request.key }
        : undefined,
    [request],
  );
  const stream = useSSE(request?.url ?? null, request !== null, streamBody);

  useEffect(() => {
    try {
      const saved = window.localStorage.getItem("study-chat-split");
      if (saved) {
        const value = Number(saved);
        if (Number.isFinite(value) && value >= 25 && value <= 75) setSplit(value);
      }
    } catch {
      // The split position is a nonessential UI preference.
    }
    setSplitReady(true);
  }, []);
  useEffect(() => {
    if (!splitReady) return;
    try {
      window.localStorage.setItem("study-chat-split", String(split));
    } catch {
      // The split position is a nonessential UI preference.
    }
  }, [split, splitReady]);
  useEffect(() => {
    if (stream.status === "open") streamOpened.current = true;
  }, [stream.status]);
  useEffect(() => {
    if (!request) {
      streamOpened.current = false;
      return;
    }
    const parsed = stream.events.map((event) => parseChatEvent(event.data));
    const answer = parsed
      .map((event) =>
        "token" in event ? event.token : "message" in event ? event.message : "",
      )
      .join("");
    const completion = [...parsed].reverse().find(
      (event): event is { done: true; provider?: string; message?: string } =>
        "done" in event && event.done,
    );
    if (completion) {
      setMessages((current) => [
        ...current,
        {
          id: `assistant-${Date.now()}`,
          role: "assistant",
          content: answer || completion.message || "",
          ...(completion.provider ? { provider: completion.provider } : {}),
        },
      ]);
      setStreamError(null);
      setRequest(null);
      return;
    }
    if (stream.error) {
      setStreamError(stream.error.message);
      setRequest(null);
      return;
    }
    if (streamOpened.current && stream.status === "closed") {
      setStreamError("The response stream ended before an answer was complete.");
      setRequest(null);
    }
  }, [request, stream.error, stream.events, stream.status]);
  useEffect(() => {
    if (isNearBottom && messagesElement.current) {
      messagesElement.current.scrollTop = messagesElement.current.scrollHeight;
    }
  }, [isNearBottom, messages, request, stream.events]);

  if (!Number.isInteger(documentId) || documentId < 1) {
    return (
      <ErrorState
        title="Document not found"
        description="This document link is invalid."
      />
    );
  }
  if (documentQuery.isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-12 w-64" />
        <Skeleton className="h-[70vh] w-full" />
      </div>
    );
  }
  if (documentQuery.isError || !documentQuery.data) {
    return (
      <ErrorState
        title="Could not load this document"
        description={documentQuery.error?.message ?? "The document is unavailable."}
        action={
          <Link href="/chat" className="text-primary underline">
            Choose another document
          </Link>
        }
      />
    );
  }
  const document = documentQuery.data;
  const alternatives = documentsQuery.data ?? [];
  const activeParsed = stream.events.map((event) => parseChatEvent(event.data));
  const streamingText = activeParsed
    .map((event) =>
      "token" in event ? event.token : "message" in event ? event.message : "",
    )
    .join("");
  const isStreaming = request !== null;
  const examples = (termsQuery.data ?? [])
    .slice(0, 3)
    .map((term) => `Explain ${term.term} and why it matters in this document.`);

  const startQuestion = async (value: string, retry = false) => {
    const query = value.trim();
    if (!query || request || preparing) return;
    setPreparing(true);
    setStreamError(null);
    setLastQuestion(query);
    if (!retry) {
      setMessages((current) => [
        ...current,
        { id: `user-${Date.now()}`, role: "user", content: query },
      ]);
    }
    try {
      const session =
        sessionId === null
          ? await createChatSession(query.slice(0, 40) || "New chat")
          : { id: sessionId };
      setSessionId(session.id);
      const body: ChatOptions = {
        query,
        mode,
        language,
        doc_ids: [documentId],
      };
      setRequest({
        key: String(++streamSequence.current),
        url: chatMessageUrl(session.id),
        body: JSON.stringify(body),
      });
    } catch (caught) {
      setStreamError(
        caught instanceof Error ? caught.message : "Could not start this chat.",
      );
    } finally {
      setPreparing(false);
    }
  };
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void startQuestion(input);
    setInput("");
  };
  const handleInputKey = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      event.currentTarget.form?.requestSubmit();
    }
  };
  const stop = () => {
    setMessages((current) =>
      streamingText
        ? [
            ...current,
            {
              id: `stopped-${Date.now()}`,
              role: "assistant",
              content: streamingText,
              stopped: true,
            },
          ]
        : current,
    );
    setRequest(null);
    setStreamError(null);
  };
  const newChat = () => {
    setRequest(null);
    setMessages([]);
    setSessionId(null);
    setLastQuestion("");
    setStreamError(null);
    setInput("");
  };
  const updateSplit = (clientX: number) => {
    const bounds = splitElement.current?.getBoundingClientRect();
    if (!bounds || !bounds.width) return;
    setSplit(Math.max(25, Math.min(75, ((clientX - bounds.left) / bounds.width) * 100)));
  };

  return (
    <div className="space-y-3">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <Link
            href="/chat"
            aria-label="Choose another document"
            className="rounded-md p-2 hover:bg-muted"
          >
            <ArrowLeft size={18} aria-hidden="true" />
          </Link>
          <div className="min-w-0">
            <h1 className="truncate text-lg font-semibold">{document.title}</h1>
            <div className="mt-1 flex items-center gap-2">
              <PrivateBadge document={document} />
              <label className="sr-only" htmlFor="document-switcher">
                Switch document
              </label>
              <select
                id="document-switcher"
                aria-label="Switch document"
                value={document.id}
                onChange={(event) => {
                  window.location.assign(`/chat/${event.target.value}`);
                }}
                className="max-w-48 rounded border border-border bg-background px-2 py-1 text-xs"
              >
                {alternatives.some((item) => item.id === document.id) ? null : (
                  <option value={document.id}>{document.title}</option>
                )}
                {alternatives.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.title}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </div>
        <Button type="button" variant="outline" size="sm" onClick={newChat}>
          <MessageSquarePlus size={16} aria-hidden="true" />
          New chat
        </Button>
      </header>

      {document.is_private ? (
        <p role="status" className="rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-sm">
          This document is private: answers use local models only
        </p>
      ) : null}

      <div role="tablist" aria-label="Study panel" className="flex gap-2 lg:hidden">
        <Button
          type="button"
          variant={mobileTab === "chat" ? "default" : "outline"}
          role="tab"
          aria-selected={mobileTab === "chat"}
          onClick={() => setMobileTab("chat")}
        >
          Chat
        </Button>
        <Button
          type="button"
          variant={mobileTab === "pdf" ? "default" : "outline"}
          role="tab"
          aria-selected={mobileTab === "pdf"}
          onClick={() => setMobileTab("pdf")}
        >
          PDF
        </Button>
      </div>

      <div
        ref={splitElement}
        className="relative flex h-[calc(100dvh-14rem)] min-h-[34rem] w-full gap-0"
      >
        <section
          aria-label="Chat"
          className={`${mobileTab === "chat" ? "flex" : "hidden"} min-w-0 flex-col overflow-hidden rounded-lg border border-border bg-card lg:flex`}
          style={{ width: `${split}%` }}
        >
          <div
            ref={messagesElement}
            className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4"
            onScroll={(event) => {
              const { scrollTop, scrollHeight, clientHeight } = event.currentTarget;
              setIsNearBottom(scrollHeight - scrollTop - clientHeight < 60);
            }}
            aria-live="polite"
          >
            {!messages.length && !request ? (
              <div className="mx-auto max-w-lg py-8">
                <h2 className="text-lg font-semibold">Ask about this document</h2>
                <p className="mt-1 text-sm text-muted-foreground">
                  Answers are grounded in the selected PDF and include page citations.
                </p>
                {termsQuery.isLoading ? (
                  <p role="status" className="mt-6 text-sm text-muted-foreground">
                    Finding key terms…
                  </p>
                ) : examples.length ? (
                  <div className="mt-6 space-y-2">
                    {examples.map((question) => (
                      <button
                        key={question}
                        type="button"
                        disabled={preparing}
                        onClick={() => void startQuestion(question)}
                        className="block w-full rounded-md border border-border p-3 text-left text-sm hover:bg-muted disabled:opacity-50"
                      >
                        {question}
                      </button>
                    ))}
                  </div>
                ) : (
                  <p className="mt-6 text-sm text-muted-foreground">
                    Ask a question to get started.
                  </p>
                )}
              </div>
            ) : null}
            {messages.map((message) => (
              <article
                key={message.id}
                className={`max-w-[95%] rounded-lg p-3 text-sm ${
                  message.role === "user"
                    ? "ml-auto bg-primary text-primary-foreground"
                    : "mr-auto border border-border bg-background"
                }`}
              >
                {message.role === "assistant" ? (
                  <MarkdownAnswer
                    content={message.content}
                    onCitationClick={(page) => {
                      setMobileTab("pdf");
                      viewer.current?.scrollToPage(page);
                    }}
                  />
                ) : (
                  <p className="whitespace-pre-wrap">{message.content}</p>
                )}
                {message.provider ? (
                  <p className="mt-3 border-t border-border/70 pt-2 text-xs text-muted-foreground">
                    {providerLabel(message.provider)}
                  </p>
                ) : message.stopped ? (
                  <p className="mt-3 border-t border-border/70 pt-2 text-xs text-muted-foreground">
                    Response stopped.
                  </p>
                ) : null}
              </article>
            ))}
            {request ? (
              <article
                className="mr-auto max-w-[95%] rounded-lg border border-border bg-background p-3 text-sm"
                aria-label="Assistant response"
              >
                {streamingText ? (
                  <MarkdownAnswer
                    content={streamingText}
                    onCitationClick={(page) => {
                      setMobileTab("pdf");
                      viewer.current?.scrollToPage(page);
                    }}
                  />
                ) : (
                  <span className="inline-flex items-center gap-2 text-muted-foreground">
                    <LoaderCircle size={15} className="animate-spin" aria-hidden="true" />
                    Thinking…
                  </span>
                )}
              </article>
            ) : null}
            {streamError ? (
              <div role="alert" className="rounded-md border border-danger/40 bg-danger/5 p-3 text-sm">
                <p>{streamError}</p>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="mt-2"
                  onClick={() => void startQuestion(lastQuestion, true)}
                >
                  Retry
                </Button>
              </div>
            ) : null}
          </div>

          <form onSubmit={submit} className="space-y-2 border-t border-border p-3">
            <fieldset
              disabled={isStreaming || preparing}
              className="grid grid-cols-2 gap-2 sm:grid-cols-3"
            >
              <label className="text-xs text-muted-foreground">
                Answer style
                <select
                  aria-label="Answer style"
                  value={mode}
                  onChange={(event) => setMode(event.target.value as ChatOptions["mode"])}
                  className="mt-1 block h-8 w-full rounded border border-border bg-background px-2 text-xs text-foreground"
                >
                  {modeOptions.map((option) => (
                    <option key={option} value={option}>
                      {option}
                    </option>
                  ))}
                </select>
              </label>
              <label className="text-xs text-muted-foreground">
                Language
                <select
                  aria-label="Answer language"
                  value={language}
                  onChange={(event) =>
                    setLanguage(event.target.value as ChatOptions["language"])
                  }
                  className="mt-1 block h-8 w-full rounded border border-border bg-background px-2 text-xs text-foreground"
                >
                  {languageOptions.map((option) => (
                    <option key={option} value={option}>
                      {option}
                    </option>
                  ))}
                </select>
              </label>
              <label className="text-xs text-muted-foreground">
                Retrieval
                <select
                  aria-label="Retrieval method"
                  value="hybrid"
                  disabled
                  className="mt-1 block h-8 w-full rounded border border-border bg-muted px-2 text-xs text-foreground"
                >
                  <option value="keyword">Keyword</option>
                  <option value="dense">Dense</option>
                  <option value="hybrid">Hybrid (backend fixed)</option>
                </select>
              </label>
              <label className="col-span-2 flex items-center gap-2 text-xs text-muted-foreground sm:col-span-3">
                <input type="checkbox" checked disabled readOnly />
                Rerank when available (backend controlled)
              </label>
            </fieldset>
            <div className="flex items-end gap-2">
              <label className="sr-only" htmlFor="chat-input">
                Ask a question about this document
              </label>
              <textarea
                id="chat-input"
                value={input}
                disabled={isStreaming || preparing}
                onChange={(event) => setInput(event.target.value)}
                onKeyDown={handleInputKey}
                rows={2}
                maxLength={4000}
                placeholder="Ask a question…"
                className="max-h-36 min-h-16 flex-1 resize-y rounded-md border border-border bg-background p-3 text-sm"
              />
              {isStreaming ? (
                <Button
                  type="button"
                  variant="outline"
                  aria-label="Stop response"
                  onClick={stop}
                >
                  <Square size={16} aria-hidden="true" />
                  Stop
                </Button>
              ) : (
                <Button
                  type="submit"
                  aria-label="Send question"
                  disabled={!input.trim() || preparing}
                >
                  {preparing ? (
                    <LoaderCircle size={16} className="animate-spin" aria-hidden="true" />
                  ) : (
                    <Send size={16} aria-hidden="true" />
                  )}
                  Send
                </Button>
              )}
            </div>
            <p className="text-[11px] text-muted-foreground">
              Enter sends · Shift+Enter adds a line
            </p>
          </form>
        </section>

        <div
          ref={divider}
          role="separator"
          aria-label="Resize chat and PDF panels"
          aria-orientation="vertical"
          aria-valuemin={25}
          aria-valuemax={75}
          aria-valuenow={Math.round(split)}
          tabIndex={0}
          onKeyDown={(event) => {
            if (event.key === "ArrowLeft") {
              event.preventDefault();
              setSplit((value) => Math.max(25, value - 2));
            } else if (event.key === "ArrowRight") {
              event.preventDefault();
              setSplit((value) => Math.min(75, value + 2));
            } else if (event.key === "Home") setSplit(25);
            else if (event.key === "End") setSplit(75);
          }}
          onPointerDown={(event) => {
            dragging.current = true;
            event.currentTarget.setPointerCapture(event.pointerId);
          }}
          onPointerMove={(event) => {
            if (dragging.current) updateSplit(event.clientX);
          }}
          onPointerUp={() => {
            dragging.current = false;
          }}
          className="mx-1 hidden w-2 shrink-0 cursor-col-resize touch-none rounded bg-border hover:bg-primary/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary lg:block"
        />
        <section
          aria-label="PDF"
          className={`${mobileTab === "pdf" ? "flex" : "hidden"} min-w-0 flex-1 flex-col lg:flex`}
          style={{ width: `${100 - split}%` }}
        >
          <PdfViewer
            ref={viewer}
            documentId={document.id}
            pageCount={document.page_count}
          />
        </section>
      </div>
    </div>
  );
}
