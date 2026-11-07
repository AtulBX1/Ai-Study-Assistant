import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DocumentRecord } from "@/lib/documents";

const { getDocumentStatus } = vi.hoisted(() => ({
  getDocumentStatus: vi.fn(),
}));

vi.mock("@/lib/documents", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/documents")>();
  return { ...actual, getDocumentStatus };
});

import { useDocumentStatus } from "@/lib/hooks/use-document-status";

const initial: DocumentRecord = {
  id: 41,
  title: "sample.pdf",
  status: "queued",
  progress: 0,
  error_message: null,
  page_count: 1,
  language: null,
  created_at: "2026-01-01T00:00:00Z",
};

function sseResponse(data: string): Response {
  const encoder = new TextEncoder();
  return new Response(
    new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode(`data: ${data}\n\n`));
        controller.close();
      },
    }),
    { status: 200, headers: { "Content-Type": "text/event-stream" } },
  );
}

describe("document ingestion status monitoring", () => {
  beforeEach(() => {
    getDocumentStatus.mockReset();
    localStorage.clear();
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("applies status events from the SSE stream", async () => {
    vi.mocked(fetch).mockResolvedValue(
      sseResponse(
        JSON.stringify({
          document_id: 41,
          status: "ready",
          progress: 100,
          error_message: null,
        }),
      ),
    );
    const { result } = renderHook(() => useDocumentStatus(initial));

    await waitFor(() => expect(result.current.document.status).toBe("ready"));
    expect(getDocumentStatus).not.toHaveBeenCalled();
  });

  it.each([
    ["ready", 100, null],
    ["failed", 100, "The PDF could not be processed."],
  ] as const)(
    "falls back to polling and stops after %s",
    async (status, progress, errorMessage) => {
      vi.useFakeTimers();
      vi.mocked(fetch).mockRejectedValue(new Error("SSE unavailable"));
      getDocumentStatus.mockResolvedValue({
        ...initial,
        status,
        progress,
        error_message: errorMessage,
      });
      const { result, unmount } = renderHook(() => useDocumentStatus(initial));

      await act(async () => {
        await Promise.resolve();
        await Promise.resolve();
      });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(3000);
      });
      expect(result.current.document.status).toBe(status);
      expect(getDocumentStatus).toHaveBeenCalledTimes(1);

      await act(async () => {
        await vi.advanceTimersByTimeAsync(30_000);
      });
      expect(getDocumentStatus).toHaveBeenCalledTimes(1);
      unmount();
    },
  );
});
