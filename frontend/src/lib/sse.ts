import { apiBaseUrl } from "@/lib/api";
import { normalizeApiError } from "@/lib/errors";
import { getAccessToken, refreshSession } from "@/lib/session";

export type SSEEvent = {
  data: string;
  event: string;
  id?: string;
};

function parseEventData(block: string): SSEEvent | null {
  const data: string[] = [];
  let event = "message";
  let id: string | undefined;

  for (const line of block.split(/\r?\n/)) {
    if (!line || line.startsWith(":")) continue;
    const separator = line.indexOf(":");
    const field = separator < 0 ? line : line.slice(0, separator);
    let value = separator < 0 ? "" : line.slice(separator + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "data") data.push(value);
    else if (field === "event") event = value;
    else if (field === "id" && !value.includes("\0")) id = value;
  }

  if (data.length === 0) return null;
  return { data: data.join("\n"), event, ...(id === undefined ? {} : { id }) };
}

export async function readSSEStream(
  stream: ReadableStream<Uint8Array>,
  onEvent: (event: SSEEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let eventBlock = "";

  const processLine = (line: string) => {
    if (line === "") {
      const event = parseEventData(eventBlock);
      if (event) onEvent(event);
      eventBlock = "";
    } else {
      eventBlock += `${line}\n`;
    }
  };
  const drainLines = (flush = false) => {
    let start = 0;
    for (let index = 0; index < buffer.length; index += 1) {
      const character = buffer[index];
      if (character !== "\n" && character !== "\r") continue;
      if (character === "\r" && index === buffer.length - 1 && !flush) break;
      processLine(buffer.slice(start, index));
      if (signal.aborted) {
        buffer = "";
        return;
      }
      if (character === "\r" && buffer[index + 1] === "\n") index += 1;
      start = index + 1;
    }
    buffer = buffer.slice(start);
  };

  const onAbort = () => {
    void reader.cancel();
  };
  signal.addEventListener("abort", onAbort, { once: true });

  try {
    while (!signal.aborted) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      drainLines();
    }
    buffer += decoder.decode();
    if (!signal.aborted) {
      drainLines(true);
      if (buffer) processLine(buffer);
    }
    if (!signal.aborted && eventBlock) {
      const event = parseEventData(eventBlock);
      if (event) onEvent(event);
    }
  } finally {
    signal.removeEventListener("abort", onAbort);
    reader.releaseLock();
  }
}

export async function fetchSSE(
  url: string,
  onEvent: (event: SSEEvent) => void,
  signal: AbortSignal,
  onOpen?: () => void,
): Promise<void> {
  const request = () => {
    const headers = new Headers({ Accept: "text/event-stream" });
    const token = getAccessToken();
    if (token) headers.set("Authorization", `Bearer ${token}`);
    return fetch(new URL(url, apiBaseUrl), { headers, signal });
  };
  let response = await request();
  if (response.status === 401 && (await refreshSession())) {
    response = await request();
  }
  if (!response.ok) {
    let detail: unknown;
    const responseText = await response.text();
    try {
      detail = JSON.parse(responseText);
    } catch {
      detail = responseText;
    }
    throw normalizeApiError(response.status, detail);
  }
  if (!response.body) {
    throw normalizeApiError(502, "The stream response did not contain a body.");
  }
  onOpen?.();
  await readSSEStream(response.body, onEvent, signal);
}
