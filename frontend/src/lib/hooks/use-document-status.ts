"use client";

import { useEffect, useState } from "react";
import { getDocumentStatus, type DocumentRecord } from "@/lib/documents";
import { useSSE } from "@/lib/hooks/use-sse";

const terminalStatuses = new Set(["ready", "failed"]);

function isStatusEvent(value: unknown): value is {
  document_id: number;
  status: string;
  progress: number;
  error_message: string | null;
} {
  return (
    typeof value === "object" &&
    value !== null &&
    "document_id" in value &&
    typeof value.document_id === "number" &&
    "status" in value &&
    typeof value.status === "string" &&
    "progress" in value &&
    typeof value.progress === "number"
  );
}

export function useDocumentStatus(initial: DocumentRecord) {
  const [document, setDocument] = useState(initial);
  const [pollingError, setPollingError] = useState<Error | null>(null);
  const terminal = terminalStatuses.has(document.status);
  const stream = useSSE(
    terminal ? null : `/documents/${document.id}/events`,
    !terminal,
  );

  useEffect(() => {
    setDocument((current) =>
      current.id === initial.id &&
      current.status === initial.status &&
      current.progress === initial.progress
        ? current
        : initial,
    );
  }, [initial]);

  useEffect(() => {
    for (const event of stream.events) {
      try {
        const parsed: unknown = JSON.parse(event.data);
        if (!isStatusEvent(parsed) || parsed.document_id !== initial.id) continue;
        setDocument((current) => ({
          ...current,
          status: parsed.status,
          progress: parsed.progress,
          error_message: parsed.error_message ?? null,
        }));
      } catch {
        continue;
      }
    }
  }, [initial.id, stream.events]);

  useEffect(() => {
    if (
      terminalStatuses.has(document.status) ||
      (stream.status !== "error" && stream.status !== "closed")
    ) {
      return;
    }

    let active = true;
    let timeout: ReturnType<typeof setTimeout> | undefined;
    let delay = 3000;
    const poll = async () => {
      try {
        const updated = await getDocumentStatus(document.id);
        if (!active) return;
        setDocument(updated);
        setPollingError(null);
        delay = 3000;
      } catch (error) {
        if (!active) return;
        setPollingError(
          error instanceof Error ? error : new Error("Status check failed."),
        );
        delay = Math.min(delay * 2, 30_000);
      }
      if (active) timeout = setTimeout(poll, delay);
    };

    timeout = setTimeout(poll, delay);
    return () => {
      active = false;
      if (timeout) clearTimeout(timeout);
    };
  }, [document.id, document.status, stream.status]);

  return {
    document,
    streamError: stream.error,
    pollingError,
    isTerminal: terminalStatuses.has(document.status),
  };
}
