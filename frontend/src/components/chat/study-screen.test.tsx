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
  scrollToPage: vi.fn(),
}));

vi.mock("@/lib/documents", () => ({
  getDocument: mocks.getDocument,
  getDocumentKeyTerms: mocks.getDocumentKeyTerms,
  listDocuments: mocks.listDocuments,
}));

vi.mock("@/lib/chat", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/chat")>();
  return { ...actual, createChatSession: mocks.createChatSession };
});

vi.mock("next/dynamic", async () => {
  const React = await import("react");
  return {
    default: () =>
      React.forwardRef(function FakePdfViewer(_props, ref) {
        React.useImperativeHandle(ref, () => ({
          scrollToPage: mocks.scrollToPage,
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
    mocks.getDocument.mockResolvedValue(documentRecord);
    mocks.listDocuments.mockResolvedValue([documentRecord]);
    mocks.getDocumentKeyTerms.mockResolvedValue([
      { term: "attention", page: 2 },
      { term: "transformer", page: 3 },
      { term: "embedding", page: 4 },
    ]);
    mocks.createChatSession.mockResolvedValue({ id: 91, title: "Question" });
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
      vi.fn(async () => new Response(stream, { headers: { "Content-Type": "text/event-stream" } })),
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
    expect(onCitation).toHaveBeenCalledWith(7);
  });
});
