"use client";

import { useEffect, useState } from "react";
import { fetchSSE, type SSEEvent, type SSERequest } from "@/lib/sse";

export type SSEStatus = "connecting" | "open" | "closed" | "error";

type SSESnapshot = {
  key: string;
  status: SSEStatus;
  events: SSEEvent[];
  error: Error | null;
};

export function useSSE(
  url: string | null,
  enabled = true,
  request?: SSERequest,
) {
  const method = request?.method;
  const body = request?.body;
  const requestKey = request?.key;
  const key = `${url ?? ""}:${enabled}:${requestKey ?? ""}:${method ?? ""}:${body ?? ""}`;
  const [snapshot, setSnapshot] = useState<SSESnapshot>({
    key: "",
    status: "closed",
    events: [],
    error: null,
  });
  const current =
    snapshot.key === key
      ? snapshot
      : {
          key,
          status: url && enabled ? ("connecting" as const) : ("closed" as const),
          events: [],
          error: null,
        };

  useEffect(() => {
    if (!url || !enabled) {
      setSnapshot({ key, status: "closed", events: [], error: null });
      return;
    }

    const controller = new AbortController();
    setSnapshot({ key, status: "connecting", events: [], error: null });
    fetchSSE(
      url,
      (event) => {
        if (controller.signal.aborted) return;
        setSnapshot((previous) =>
          previous.key === key
            ? { ...previous, events: [...previous.events, event] }
            : previous,
        );
      },
      controller.signal,
      () => {
        setSnapshot((previous) =>
          previous.key === key ? { ...previous, status: "open" } : previous,
        );
      },
      method === undefined && body === undefined
        ? undefined
        : { method, body, key: requestKey },
    )
      .then(() => {
        setSnapshot((previous) =>
          previous.key === key ? { ...previous, status: "closed" } : previous,
        );
      })
      .catch((caught: unknown) => {
        if (controller.signal.aborted) return;
        setSnapshot((previous) =>
          previous.key === key
            ? {
                ...previous,
                status: "error",
                error:
                  caught instanceof Error
                    ? caught
                    : new Error("The stream connection failed."),
              }
            : previous,
        );
      });

    return () => controller.abort();
  }, [body, enabled, key, method, requestKey, url]);

  return {
    status: current.status,
    events: current.events,
    error: current.error,
  };
}
