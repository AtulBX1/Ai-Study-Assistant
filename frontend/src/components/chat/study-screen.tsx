"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowLeft,
  CircleHelp,
  ChevronLeft,
  ChevronRight,
  History,
  LoaderCircle,
  MessageSquarePlus,
  Pencil,
  Send,
  Square,
  Trash2,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Skeleton } from "@/components/ui/skeleton";
import {
  createChatSession,
  chatMessageUrl,
  deleteChatSession,
  getChatSession,
  listChatSessions,
  parseChatEvent,
  type ChatExplanation,
  type ChatCompletion,
  type ChatMessageRecord,
  type ChatOptions,
  type ChatSessionDetail,
} from "@/lib/chat";
import { getDocument, getDocumentKeyTerms, listDocuments, type DocumentRecord } from "@/lib/documents";
import { useSSE } from "@/lib/hooks/use-sse";
import { MarkdownAnswer } from "@/components/chat/markdown-answer";
import {
  ExplanationDrawer,
  FeedbackControls,
  GroundingBadge,
  ReadAloud,
  VoiceInput,
} from "@/components/chat/message-controls";
import type { PdfViewerHandle } from "@/components/chat/pdf-viewer";
import { findCitationPassage, isNotFoundRefusal } from "@/lib/study-utils";

const PdfViewer = dynamic(
  () => import("@/components/chat/pdf-viewer").then((module) => module.PdfViewer),
  { ssr: false, loading: () => <Skeleton className="h-full min-h-96 w-full" /> },
);

type ChatMessage = {
  id: string;
  messageId?: number;
  role: "user" | "assistant";
  content: string;
  provider?: string;
  stopped?: boolean;
  groundingScore?: number | null;
  unsupportedSentences?: string[];
  explanation?: ChatExplanation;
  feedback?: "thumbs_up" | "thumbs_down" | null;
  feedbackReason?: string | null;
  createdAt?: string;
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

const HISTORY_PAGE_SIZE = 8;

function isStringRecord(value: unknown): value is Record<string, string> {
  return (
    typeof value === "object" &&
    value !== null &&
    Object.values(value).every((item) => typeof item === "string")
  );
}

function readStoredTitles(): Record<string, string> {
  const raw = window.localStorage.getItem("study-chat-renamed-sessions");
  if (!raw) return {};
  const value: unknown = JSON.parse(raw);
  return isStringRecord(value) ? value : {};
}

function readStoredDocuments(): Record<string, string> {
  const raw = window.localStorage.getItem("study-chat-session-documents");
  if (!raw) return {};
  const value: unknown = JSON.parse(raw);
  return isStringRecord(value) ? value : {};
}

function toChatMessage(message: ChatMessageRecord): ChatMessage {
  return {
    id: `saved-${message.id}`,
    messageId: message.id,
    role: message.role,
    content: message.content,
    provider: message.provider ?? undefined,
    groundingScore: message.grounding_score,
    unsupportedSentences: message.unsupported_sentences,
    explanation: message.explanation,
    feedback: message.feedback,
    feedbackReason: message.feedback_reason,
    createdAt: message.created_at,
  };
}

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
  const historyQuery = useQuery({
    queryKey: ["chat-history", documentId],
    queryFn: async () => {
      const [sessions, documentMap] = await Promise.all([
        listChatSessions(),
        Promise.resolve(readStoredDocuments()),
      ]);
      const details = await Promise.all(sessions.map((session) => getChatSession(session.id)));
      return details.filter(
        (session) =>
          documentMap[String(session.id)] === String(documentId) ||
          session.messages.some((message) =>
            message.explanation.chunks?.some((chunk) => chunk.document_id === documentId),
          ),
      );
    },
    enabled: Number.isInteger(documentId) && documentId > 0,
  });
  const refetchHistory = historyQuery.refetch;
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
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyPage, setHistoryPage] = useState(0);
  const [historyTitles, setHistoryTitles] = useState<Record<string, string>>({});
  const [renamingSession, setRenamingSession] = useState<number | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [deleteSessionId, setDeleteSessionId] = useState<number | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [helpOpen, setHelpOpen] = useState(false);
  const messagesElement = useRef<HTMLDivElement>(null);
  const inputElement = useRef<HTMLTextAreaElement>(null);
  const switcherElement = useRef<HTMLSelectElement>(null);
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
    setHistoryTitles(readStoredTitles());
  }, []);

  useEffect(() => {
    const handleShortcut = (event: globalThis.KeyboardEvent) => {
      if (event.key === "/" && !event.ctrlKey && !event.metaKey && !event.altKey) {
        const target = event.target;
        if (
          target instanceof HTMLElement &&
          (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))
        ) {
          return;
        }
        event.preventDefault();
        inputElement.current?.focus();
      } else if (event.key === "Escape") {
        setHelpOpen(false);
        setHistoryOpen(false);
        viewer.current?.clearHighlight();
      }
    };
    window.addEventListener("keydown", handleShortcut);
    return () => window.removeEventListener("keydown", handleShortcut);
  }, []);

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
      (event): event is ChatCompletion => "done" in event && event.done,
    );
    if (completion) {
      setMessages((current) => [
        ...current,
        {
          id: `assistant-${Date.now()}`,
          role: "assistant",
          content: answer || completion.message || "",
          ...(completion.message_id !== undefined
            ? { messageId: completion.message_id }
            : {}),
          ...(completion.provider ? { provider: completion.provider } : {}),
          ...(completion.grounding_score !== undefined
            ? { groundingScore: completion.grounding_score }
            : {}),
          ...(completion.unsupported_sentences
            ? { unsupportedSentences: completion.unsupported_sentences }
            : {}),
          ...(completion.explanation ? { explanation: completion.explanation } : {}),
        },
      ]);
      setStreamError(null);
      setRequest(null);
      void refetchHistory();
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
  }, [refetchHistory, request, stream.error, stream.events, stream.status]);
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
      const sessionDocuments = readStoredDocuments();
      sessionDocuments[String(session.id)] = String(documentId);
      window.localStorage.setItem(
        "study-chat-session-documents",
        JSON.stringify(sessionDocuments),
      );
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
  const jumpToSource = (
    page: number,
    title: string | undefined,
    explanation: ChatExplanation | undefined,
  ) => {
    const passage = findCitationPassage(
      page,
      title,
      explanation?.chunks ?? [],
      explanation?.answer_sentences ?? [],
    );
    setMobileTab("pdf");
    if (passage) viewer.current?.scrollToSource(page, passage);
    else viewer.current?.scrollToPage(page);
  };
  const historySessions = historyQuery.data ?? [];
  const historyPageCount = Math.max(1, Math.ceil(historySessions.length / HISTORY_PAGE_SIZE));
  const visibleHistory = historySessions.slice(
    historyPage * HISTORY_PAGE_SIZE,
    (historyPage + 1) * HISTORY_PAGE_SIZE,
  );
  const openHistorySession = (session: ChatSessionDetail) => {
    setSessionId(session.id);
    setMessages(session.messages.map(toChatMessage));
    setLastQuestion([...session.messages].reverse().find((item) => item.role === "user")?.content ?? "");
    setStreamError(null);
    setHistoryOpen(false);
  };
  const saveRename = (sessionIdToRename: number) => {
    const title = renameValue.trim();
    if (!title) return;
    const titles = readStoredTitles();
    titles[String(sessionIdToRename)] = title;
    window.localStorage.setItem("study-chat-renamed-sessions", JSON.stringify(titles));
    setHistoryTitles(titles);
    setRenamingSession(null);
  };
  const confirmDelete = async () => {
    if (deleteSessionId === null) return;
    setDeleteError(null);
    try {
      await deleteChatSession(deleteSessionId);
      const titles = readStoredTitles();
      delete titles[String(deleteSessionId)];
      window.localStorage.setItem("study-chat-renamed-sessions", JSON.stringify(titles));
      const documents = readStoredDocuments();
      delete documents[String(deleteSessionId)];
      window.localStorage.setItem("study-chat-session-documents", JSON.stringify(documents));
      setHistoryTitles(titles);
      if (sessionId === deleteSessionId) newChat();
      await refetchHistory();
      setDeleteSessionId(null);
    } catch (caught) {
      setDeleteError(caught instanceof Error ? caught.message : "Could not delete the chat.");
    }
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
                ref={switcherElement}
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
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            aria-expanded={historyOpen}
            onClick={() => setHistoryOpen((open) => !open)}
          >
            <History size={16} aria-hidden="true" />
            History
          </Button>
          <Button type="button" variant="outline" size="sm" onClick={() => setHelpOpen(true)}>
            <CircleHelp size={16} aria-hidden="true" />
            Shortcuts
          </Button>
          <Button type="button" variant="outline" size="sm" onClick={newChat}>
            <MessageSquarePlus size={16} aria-hidden="true" />
            New chat
          </Button>
        </div>
      </header>

      {historyOpen ? (
        <aside
          aria-label="Chat history"
          className="rounded-lg border border-border bg-card p-4 shadow-sm"
        >
          <div className="flex items-center justify-between gap-3">
            <h2 className="font-semibold">Chats for this document</h2>
            <Button type="button" size="sm" variant="ghost" onClick={() => setHistoryOpen(false)}>
              Close history
            </Button>
          </div>
          {historyQuery.isLoading ? (
            <p role="status" className="mt-3 text-sm text-muted-foreground">Loading chat history…</p>
          ) : historyQuery.isError ? (
            <div className="mt-3 flex items-center gap-3 text-sm">
              <p role="alert">{historyQuery.error.message}</p>
              <Button type="button" size="sm" variant="outline" onClick={() => void historyQuery.refetch()}>
                Retry
              </Button>
            </div>
          ) : !historySessions.length ? (
            <p className="mt-3 text-sm text-muted-foreground">No saved chats for this document yet.</p>
          ) : (
            <>
              <ul className="mt-3 space-y-2">
                {visibleHistory.map((session) => {
                  const firstQuestion = session.messages.find((item) => item.role === "user")?.content;
                  const title =
                    historyTitles[String(session.id)] ??
                    firstQuestion?.slice(0, 40) ??
                    session.title;
                  return (
                    <li
                      key={session.id}
                      className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-border p-3"
                    >
                      {renamingSession === session.id ? (
                        <form
                          className="flex min-w-0 flex-1 items-center gap-2"
                          onSubmit={(event) => {
                            event.preventDefault();
                            saveRename(session.id);
                          }}
                        >
                          <input
                            autoFocus
                            aria-label="New chat title"
                            value={renameValue}
                            maxLength={255}
                            onChange={(event) => setRenameValue(event.target.value)}
                            className="h-9 min-w-0 flex-1 rounded border border-border bg-background px-2 text-sm"
                          />
                          <Button type="submit" size="sm" disabled={!renameValue.trim()}>
                            Save
                          </Button>
                          <Button type="button" size="sm" variant="ghost" onClick={() => setRenamingSession(null)}>
                            Cancel
                          </Button>
                        </form>
                      ) : (
                        <>
                          <button
                            type="button"
                            className="min-w-0 flex-1 text-left"
                            aria-label={`Open chat: ${title}`}
                            onClick={() => openHistorySession(session)}
                          >
                            <span className="block truncate text-sm font-medium">{title}</span>
                            <span className="text-xs text-muted-foreground">
                              {session.created_at
                                ? new Date(session.created_at).toLocaleDateString()
                                : "Date unavailable"}
                            </span>
                          </button>
                          <div className="flex items-center">
                            <Button
                              type="button"
                              size="sm"
                              variant="ghost"
                              aria-label={`Rename chat: ${title}`}
                              onClick={() => {
                                setRenamingSession(session.id);
                                setRenameValue(title);
                              }}
                            >
                              <Pencil size={15} aria-hidden="true" />
                            </Button>
                            <Button
                              type="button"
                              size="sm"
                              variant="ghost"
                              aria-label={`Delete chat: ${title}`}
                              onClick={() => {
                                setDeleteSessionId(session.id);
                                setDeleteError(null);
                              }}
                            >
                              <Trash2 size={15} aria-hidden="true" />
                            </Button>
                          </div>
                        </>
                      )}
                    </li>
                  );
                })}
              </ul>
              {historyPageCount > 1 ? (
                <div className="mt-3 flex items-center justify-end gap-2 text-xs">
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    aria-label="Previous history page"
                    disabled={historyPage === 0}
                    onClick={() => setHistoryPage((page) => page - 1)}
                  >
                    <ChevronLeft size={15} aria-hidden="true" />
                  </Button>
                  <span>Page {historyPage + 1} of {historyPageCount}</span>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    aria-label="Next history page"
                    disabled={historyPage + 1 >= historyPageCount}
                    onClick={() => setHistoryPage((page) => page + 1)}
                  >
                    <ChevronRight size={15} aria-hidden="true" />
                  </Button>
                </div>
              ) : null}
            </>
          )}
        </aside>
      ) : null}

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
                    : isNotFoundRefusal(message.content)
                      ? "mr-auto border border-amber-600/50 bg-amber-500/10"
                      : "mr-auto border border-border bg-background"
                }`}
              >
                {message.role === "assistant" ? (
                  <MarkdownAnswer
                    content={message.content}
                    unsupportedSentences={message.unsupportedSentences}
                    onCitationClick={(page, title) =>
                      jumpToSource(page, title, message.explanation)
                    }
                  />
                ) : (
                  <p className="whitespace-pre-wrap">{message.content}</p>
                )}
                {message.role === "assistant" && isNotFoundRefusal(message.content) ? (
                  <div className="mt-3 flex flex-wrap gap-2 border-t border-amber-600/30 pt-3">
                    <p className="w-full text-xs font-medium text-amber-900 dark:text-amber-100">
                      This document did not contain enough evidence for an answer.
                    </p>
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      onClick={() => {
                        setInput(lastQuestion);
                        inputElement.current?.focus();
                      }}
                    >
                      Rephrase
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      onClick={() => switcherElement.current?.focus()}
                    >
                      Search other documents
                    </Button>
                  </div>
                ) : null}
                {message.provider ? (
                  <p className="mt-3 border-t border-border/70 pt-2 text-xs text-muted-foreground">
                    {providerLabel(message.provider)}
                  </p>
                ) : message.stopped ? (
                  <p className="mt-3 border-t border-border/70 pt-2 text-xs text-muted-foreground">
                    Response stopped.
                  </p>
                ) : null}
                {message.role === "assistant" ? (
                  <>
                    {typeof message.groundingScore === "number" &&
                    Number.isFinite(message.groundingScore) ? (
                      <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-border/70 pt-2">
                        <GroundingBadge score={message.groundingScore} />
                        <ExplanationDrawer
                          sessionId={sessionId}
                          messageId={message.messageId}
                          explanation={message.explanation ?? {}}
                          onChunkClick={(page, title, text) => {
                            jumpToSource(page, title, {
                              chunks: [{ page, document_title: title, text }],
                            });
                          }}
                        />
                        <ReadAloud content={message.content} language={language} />
                      </div>
                    ) : null}
                    {message.messageId !== undefined ? (
                      <FeedbackControls
                        messageId={message.messageId}
                        storedFeedback={message.feedback}
                        storedReason={message.feedbackReason}
                        onSaved={(feedback, reason) => {
                          setMessages((current) =>
                            current.map((item) =>
                              item.id === message.id
                                ? { ...item, feedback, feedbackReason: reason ?? null }
                                : item,
                            ),
                          );
                        }}
                      />
                    ) : null}
                  </>
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
                    onCitationClick={(page, title) =>
                      jumpToSource(page, title, undefined)
                    }
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
                ref={inputElement}
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
              <VoiceInput language={language} onTranscript={(value) => setInput(value)} />
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
            <p className="text-[11px] text-muted-foreground">
              Voice uses your browser; on some browsers, recognition audio is sent to the browser vendor&apos;s servers.
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
      <Dialog open={helpOpen} onOpenChange={setHelpOpen} title="Keyboard shortcuts">
        <ul className="list-disc space-y-2 pl-5 text-sm">
          <li><kbd className="rounded border border-border px-1">/</kbd> Focus the question input.</li>
          <li><kbd className="rounded border border-border px-1">Escape</kbd> Close drawers and clear the PDF highlight.</li>
        </ul>
      </Dialog>
      <Dialog
        open={deleteSessionId !== null}
        onOpenChange={(open) => {
          if (!open) {
            setDeleteSessionId(null);
            setDeleteError(null);
          }
        }}
        title="Delete chat history?"
      >
        <p className="text-sm">
          This permanently deletes the selected chat and its saved messages from your account.
        </p>
        {deleteError ? <p role="alert" className="mt-3 text-sm text-danger">{deleteError}</p> : null}
        <div className="mt-5 flex justify-end gap-2">
          <Button type="button" variant="outline" onClick={() => setDeleteSessionId(null)}>
            Cancel
          </Button>
          <Button type="button" onClick={() => void confirmDelete()}>
            Delete chat
          </Button>
        </div>
      </Dialog>
    </div>
  );
}
