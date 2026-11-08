import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MarkdownAnswer } from "@/components/chat/markdown-answer";
import { StudyScreen } from "@/components/chat/study-screen";

const mocks = vi.hoisted(() => ({
  getDocument: vi.fn(),
  getDocumentKeyTerms: vi.fn(),
  listDocuments: vi.fn(),
  createChatSession: vi.fn(),
  listChatSessions: vi.fn(),
  getChatSession: vi.fn(),
  deleteChatSession: vi.fn(),
  submitChatFeedback: vi.fn(),
  scrollToPage: vi.fn(),
  scrollToSource: vi.fn(),
  clearHighlight: vi.fn(),
}));

vi.mock("@/lib/documents", () => ({
  getDocument: mocks.getDocument,
  getDocumentKeyTerms: mocks.getDocumentKeyTerms,
  listDocuments: mocks.listDocuments,
}));

vi.mock("@/lib/chat", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/chat")>();
  return {
    ...actual,
    createChatSession: mocks.createChatSession,
    listChatSessions: mocks.listChatSessions,
    getChatSession: mocks.getChatSession,
    deleteChatSession: mocks.deleteChatSession,
    submitChatFeedback: mocks.submitChatFeedback,
  };
});

vi.mock("next/dynamic", async () => {
  const React = await import("react");
  return {
    default: () =>
      React.forwardRef(function FakePdfViewer(_props, ref) {
        React.useImperativeHandle(ref, () => ({
          scrollToPage: mocks.scrollToPage,
          scrollToSource: mocks.scrollToSource,
          clearHighlight: mocks.clearHighlight,
        }));
        return React.createElement("div", { "data-testid": "pdf-viewer" });
      }),
  };
});

const documentRecord = {
  id: 42,
  title: "Unit I",
  status: "ready",
  progress: 100,
  error_message: null,
  page_count: 5,
  language: "English",
  created_at: "2026-01-01T00:00:00Z",
  is_private: true,
};

function responseStream(
  chunks: string[],
  delayMs = 0,
  onCancel: () => void = () => undefined,
) {
  const encoder = new TextEncoder();
  return new ReadableStream<Uint8Array>({
    start(controller) {
      chunks.forEach((chunk, index) => {
        setTimeout(() => {
          try {
            controller.enqueue(encoder.encode(chunk));
            if (index === chunks.length - 1) controller.close();
          } catch {
            // The test may intentionally abort before the next chunk.
          }
        }, delayMs * index);
      });
    },
    cancel() {
      onCancel();
    },
  });
}

function renderScreen() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <StudyScreen documentId={42} />
    </QueryClientProvider>,
  );
}

describe("study screen", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    mocks.getDocument.mockResolvedValue(documentRecord);
    mocks.listDocuments.mockResolvedValue([documentRecord]);
    mocks.getDocumentKeyTerms.mockResolvedValue([
      { term: "attention", page: 2 },
      { term: "transformer", page: 3 },
      { term: "embedding", page: 4 },
    ]);
    mocks.createChatSession.mockResolvedValue({ id: 91, title: "Question" });
    mocks.listChatSessions.mockResolvedValue([]);
    mocks.getChatSession.mockResolvedValue({ id: 91, title: "Question", messages: [] });
    mocks.deleteChatSession.mockResolvedValue(undefined);
    mocks.submitChatFeedback.mockResolvedValue(undefined);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("streams tokens in order, sends supported options, shows provider/private state, and follows citations", async () => {
    const body = [
      `data: ${JSON.stringify({ token: "First " })}\n\n`,
      `data: ${JSON.stringify({ token: "second [Unit I, p.2]" })}\n\n`,
      `data: ${JSON.stringify({ done: true, provider: "answered by: extractive (fallback: private document)" })}\n\n`,
    ];
    const requestBodies: unknown[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
        const requestUrl =
          _input instanceof Request
            ? new URL(_input.url)
            : new URL(String(_input), "http://localhost:8000");
        if (requestUrl.pathname === "/chat/sessions" && !init?.body) {
          return Response.json([]);
        }
        requestBodies.push(JSON.parse(String(init?.body)));
        return new Response(responseStream(body, 70), {
          headers: { "Content-Type": "text/event-stream" },
        });
      }),
    );
    renderScreen();

    expect(
      await screen.findByText("This document is private: answers use local models only"),
    ).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Answer style"), {
      target: { value: "exam-style" },
    });
    fireEvent.change(screen.getByLabelText("Answer language"), {
      target: { value: "Punjabi" },
    });
    fireEvent.change(screen.getByRole("textbox", { name: "Ask a question about this document" }), {
      target: { value: "What is attention?" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send question" }));

    const input = screen.getByRole("textbox", {
      name: "Ask a question about this document",
    });
    await waitFor(() => expect(input.hasAttribute("disabled")).toBe(true));
    await waitFor(() => expect(input.hasAttribute("disabled")).toBe(false), {
      timeout: 3000,
    });
    expect(screen.getByText(/First second/)).toBeTruthy();
    expect(requestBodies).toEqual([
      {
        query: "What is attention?",
        mode: "exam-style",
        language: "Punjabi",
        doc_ids: [42],
      },
    ]);
    expect(
      screen.getByText("Answered by: extractive (fallback: private document)"),
    ).toBeTruthy();
    const citation = screen.getByRole("button", {
      name: "Go to Unit I, page 2",
    });
    expect(citation).toBeTruthy();
    fireEvent.click(citation);
    expect(mocks.scrollToPage).toHaveBeenCalledWith(2);
  });

  it("stops an active stream and keeps only tokens received before abort", async () => {
    const canceled = vi.fn();
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(
          new TextEncoder().encode(`data: ${JSON.stringify({ token: "partial answer" })}\n\n`),
        );
      },
      cancel: canceled,
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const requestUrl =
          input instanceof Request
            ? new URL(input.url)
            : new URL(String(input), "http://localhost:8000");
        if (requestUrl.pathname === "/chat/sessions") return Response.json([]);
        return new Response(stream, { headers: { "Content-Type": "text/event-stream" } });
      }),
    );
    renderScreen();
    fireEvent.change(
      await screen.findByRole("textbox", {
        name: "Ask a question about this document",
      }),
      { target: { value: "Explain this" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Send question" }));
    await screen.findByText("partial answer");
    fireEvent.click(screen.getByRole("button", { name: "Stop response" }));

    expect(await screen.findByText("Response stopped.")).toBeTruthy();
    expect(screen.getByText("partial answer")).toBeTruthy();
    await waitFor(() => expect(canceled).toHaveBeenCalled());
  });

  it("offers rephrase and the document switcher for the not-found refusal", async () => {
    const body = [
      `data: ${JSON.stringify({ token: "not found in the document" })}\n\n`,
      `data: ${JSON.stringify({
        done: true,
        provider: "answered by: retrieval guard",
        message_id: 101,
        grounding_score: 0,
        unsupported_sentences: [],
        explanation: { chunks: [], answer_sentences: ["not found in the document"], mode: "normal" },
      })}\n\n`,
    ];
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(responseStream(body), {
        headers: { "Content-Type": "text/event-stream" },
      })),
    );
    renderScreen();
    const input = await screen.findByRole("textbox", {
      name: "Ask a question about this document",
    });
    fireEvent.change(input, { target: { value: "Explain a missing topic" } });
    fireEvent.click(screen.getByRole("button", { name: "Send question" }));

    expect(await screen.findByRole("button", { name: "Rephrase" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Rephrase" }));
    expect(input).toHaveProperty("value", "Explain a missing topic");
    fireEvent.click(screen.getByRole("button", { name: "Search other documents" }));
    expect(document.activeElement).toBe(screen.getByRole("combobox", { name: "Switch document" }));
  });

  it("marks backend-flagged unsupported sentences in the answer", () => {
    render(
      <MarkdownAnswer
        content="This claim is unsupported."
        unsupportedSentences={["This claim is unsupported."]}
        onCitationClick={vi.fn()}
      />,
    );
    expect(screen.getByTitle("Not found in your document")).toBeTruthy();
  });

  it("loads, renames, opens, and confirms deletion of a document chat", async () => {
    const session = {
      id: 91,
      title: "Why is attention useful?",
      created_at: "2026-03-10T12:00:00Z",
      updated_at: "2026-03-10T12:00:00Z",
      messages: [
        {
          id: 1,
          session_id: 91,
          role: "user" as const,
          content: "Why is attention useful?",
          citations: [],
          unsupported_sentences: [],
          explanation: {},
          created_at: "2026-03-10T12:00:00Z",
        },
        {
          id: 2,
          session_id: 91,
          role: "assistant" as const,
          content: "Attention connects evidence. [Unit I, p.2]",
          citations: [{ document_title: "Unit I", page: 2, chunk_id: 7 }],
          grounding_score: 0.8,
          unsupported_sentences: [],
          explanation: {
            chunks: [{
              chunk_id: 7,
              document_id: 42,
              document_title: "Unit I",
              page: 2,
              text: "Attention connects evidence.",
              section: "Attention",
              retrieval_score: 0.7,
              rerank_score: 0.8,
            }],
            answer_sentences: ["Attention connects evidence."],
            provider: "answered by: mock",
            mode: "normal",
            latency_ms: 21,
          },
          provider: "answered by: mock",
          latency_ms: 21,
          feedback: null,
          feedback_reason: null,
          created_at: "2026-03-10T12:00:01Z",
        },
      ],
    };
    let remainingSessions = [{
      id: session.id,
      title: session.title,
      created_at: session.created_at,
      updated_at: session.updated_at,
    }];
    mocks.listChatSessions.mockImplementation(async () => remainingSessions);
    mocks.getChatSession.mockResolvedValue(session);
    mocks.deleteChatSession.mockImplementation(async () => {
      remainingSessions = [];
    });
    renderScreen();

    fireEvent.click(await screen.findByRole("button", { name: "History" }));
    fireEvent.click(await screen.findByRole("button", { name: "Open chat: Why is attention useful?" }));
    expect(await screen.findByText(/Attention connects evidence/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Why this answer" }));
    expect(await screen.findByText("Retrieved evidence")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Go to page 2 and highlight" }));
    expect(mocks.scrollToSource).toHaveBeenCalledWith(2, "Attention connects evidence.");

    fireEvent.click(screen.getByRole("button", { name: "History" }));
    fireEvent.click(screen.getByRole("button", { name: "Rename chat: Why is attention useful?" }));
    fireEvent.change(screen.getByRole("textbox", { name: "New chat title" }), {
      target: { value: "Attention review" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(screen.getByRole("button", { name: "Open chat: Attention review" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Delete chat: Attention review" }));
    fireEvent.click(await screen.findByRole("button", { name: /^Delete chat$/ }));
    await waitFor(() => expect(mocks.deleteChatSession).toHaveBeenCalledWith(91));
    await waitFor(() => expect(screen.getByText("No saved chats for this document yet.")).toBeTruthy());
  });
});

describe("safe markdown answers", () => {
  it("does not create script elements or javascript links and makes citations actionable", () => {
    const onCitation = vi.fn();
    const { container } = render(
      <MarkdownAnswer
        content={'<script>alert(1)</script> [unsafe](javascript:alert(1)) [doc, p.7]'}
        onCitationClick={onCitation}
      />,
    );
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector('a[href^="javascript:"]')).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Go to doc, page 7" }));
    expect(onCitation).toHaveBeenCalledWith(7, "doc");
  });
});
