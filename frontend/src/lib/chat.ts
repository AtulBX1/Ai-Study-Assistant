import { apiClient, unwrapApiResult } from "@/lib/api";
import type { components } from "@/lib/api/schema";

export type ChatOptions = components["schemas"]["PostMessageRequest"];

export type ChatSession = {
  id: number;
  title: string;
};

function isChatSession(value: unknown): value is ChatSession {
  return (
    typeof value === "object" &&
    value !== null &&
    "id" in value &&
    typeof value.id === "number" &&
    "title" in value &&
    typeof value.title === "string"
  );
}

export async function createChatSession(title: string): Promise<ChatSession> {
  const result = await apiClient.POST("/chat/sessions", { body: { title } });
  const value: unknown = unwrapApiResult(result);
  if (!isChatSession(value)) {
    throw new Error("The chat session response was invalid.");
  }
  return value;
}

export function chatMessageUrl(sessionId: number): string {
  return `/chat/sessions/${sessionId}/messages`;
}

export function parseChatEvent(data: string):
  | { token: string }
  | { done: true; provider?: string; message?: string }
  | { message: string } {
  let payload: unknown;
  try {
    payload = JSON.parse(data);
  } catch {
    return { message: data };
  }
  if (typeof payload !== "object" || payload === null) {
    return { message: data };
  }
  if ("token" in payload && typeof payload.token === "string") {
    return { token: payload.token };
  }
  if ("done" in payload && payload.done === true) {
    return {
      done: true,
      ...("provider" in payload && typeof payload.provider === "string"
        ? { provider: payload.provider }
        : {}),
      ...("message" in payload && typeof payload.message === "string"
        ? { message: payload.message }
        : {}),
    };
  }
  if ("message" in payload && typeof payload.message === "string") {
    return { message: payload.message };
  }
  return { message: data };
}
