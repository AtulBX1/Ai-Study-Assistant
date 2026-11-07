import { describe, expect, it, vi } from "vitest";
import { readSSEStream, type SSEEvent } from "@/lib/sse";

function streamFrom(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
}

describe("SSE stream parser", () => {
  it("parses split chunks and joins multi-line event data", async () => {
    const events: SSEEvent[] = [];
    const controller = new AbortController();
    await readSSEStream(
      streamFrom(["data: hel", "lo\r", "\ndata: wor", "ld\n\n", "event: note\nid: 5\ndata: second\n\n"]),
      (event) => events.push(event),
      controller.signal,
    );
    expect(events).toEqual([
      { data: "hello\nworld", event: "message" },
      { data: "second", event: "note", id: "5" },
    ]);
  });

  it("supports carriage-return-only line endings", async () => {
    const events: SSEEvent[] = [];
    await readSSEStream(
      streamFrom(["data: first\r", "data: second\r\r"]),
      (event) => events.push(event),
      new AbortController().signal,
    );
    expect(events).toEqual([{ data: "first\nsecond", event: "message" }]);
  });

  it("cancels the reader and stops parsing after abort", async () => {
    const events: SSEEvent[] = [];
    const abort = new AbortController();
    const canceled = vi.fn();
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode("data: first\n\n"));
      },
      cancel: canceled,
    });
    await readSSEStream(
      stream,
      (event) => {
        events.push(event);
        abort.abort();
      },
      abort.signal,
    );
    expect(events).toEqual([{ data: "first", event: "message" }]);
    expect(canceled).toHaveBeenCalledOnce();
  });
});
