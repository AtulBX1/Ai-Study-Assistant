"use client";

import { useEffect, useState } from "react";
import { fetchSSE, type SSEEvent } from "@/lib/sse";

export type SSEStatus = "connecting" | "open" | "closed" | "error";

export function useSSE(url: string | null, enabled = true) {
  const [status, setStatus] = useState<SSEStatus>("closed");
  const [events, setEvents] = useState<SSEEvent[]>([]);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    if (!url || !enabled) {
      setStatus("closed");
      return;
    }

    const controller = new AbortController();
    setEvents([]);
    setError(null);
    setStatus("connecting");
    fetchSSE(
      url,
      (event) => {
        if (controller.signal.aborted) return;
        setEvents((current) => [...current, event]);
      },
      controller.signal,
      () => setStatus("open"),
    )
      .then(() => setStatus("closed"))
      .catch((caught: unknown) => {
        if (controller.signal.aborted) return;
        setError(
          caught instanceof Error ? caught : new Error("The stream connection failed."),
        );
        setStatus("error");
      });

    return () => controller.abort();
  }, [enabled, url]);

  return { status, events, error };
}
