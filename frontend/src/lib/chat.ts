import { apiClient, unwrapApiResult } from "@/lib/api";
import type { components } from "@/lib/api/schema";

export type ChatOptions = components["schemas"]["PostMessageRequest"];

export type ChatSession = {
  id: number;
  title: string;
  created_at?: string;
  updated_at?: string;
};

export type GroundingSentence = {
  sentence: string;
  supported: boolean;
  similarity?: number;
  keyword_overlap?: number;
};

export type EvidenceChunk = {
  chunk_id?: number;
  document_id?: number;
  document_title?: string;
  page?: number;
  text?: string;
  section?: string | null;
  used_sentences?: GroundingSentence[];
  retrieval_score?: number | null;
  rerank_score?: number | null;
  score_components?: Record<string, unknown>;
};

export type ChatExplanation = {
  chunks?: EvidenceChunk[];
  answer_sentences?: string[];
  provider?: string;
  mode?: string;
  latency_ms?: number;
  retrieval_mode?: string;
};

export type ChatMessageRecord = {
  id: number;
  session_id: number;
  role: "user" | "assistant";
  content: string;
  citations: Array<{
    document_title?: string;
    page?: number;
    chunk_id?: number | null;
  }>;
  grounding_score?: number | null;
  unsupported_sentences: string[];
  explanation: ChatExplanation;
  provider?: string | null;
  latency_ms?: number | null;
  feedback?: "thumbs_up" | "thumbs_down" | null;
  feedback_reason?: string | null;
  created_at: string;
};

export type ChatSessionDetail = ChatSession & {
  messages: ChatMessageRecord[];
};

function isChatSession(value: unknown): value is ChatSession {
  return (
    typeof value === "object" &&
    value !== null &&
    "id" in value &&
    typeof value.id === "number" &&
    "title" in value &&
    typeof value.title === "string" &&
    (!("created_at" in value) || typeof value.created_at === "string") &&
    (!("updated_at" in value) || typeof value.updated_at === "string")
  );
}

function isChatSessionDetail(
  value: unknown,
): value is Record<string, unknown> & ChatSession & { messages: unknown[] } {
  return (
    isRecord(value) &&
    "messages" in value &&
    Array.isArray(value.messages) &&
    isChatSession(value)
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function parseEvidenceChunk(value: unknown): EvidenceChunk | null {
  if (!isRecord(value)) return null;
  return {
    ...(typeof value.chunk_id === "number" ? { chunk_id: value.chunk_id } : {}),
    ...(typeof value.document_id === "number" ? { document_id: value.document_id } : {}),
    ...(typeof value.document_title === "string"
      ? { document_title: value.document_title }
      : {}),
    ...(typeof value.page === "number" ? { page: value.page } : {}),
    ...(typeof value.text === "string" ? { text: value.text } : {}),
    ...(typeof value.section === "string" || value.section === null
      ? { section: value.section }
      : {}),
    ...(Array.isArray(value.used_sentences)
      ? {
          used_sentences: value.used_sentences
            .map(parseGroundingSentence)
            .filter((sentence): sentence is GroundingSentence => sentence !== null),
        }
      : {}),
    ...(typeof value.retrieval_score === "number" || value.retrieval_score === null
      ? { retrieval_score: value.retrieval_score }
      : {}),
    ...(typeof value.rerank_score === "number" || value.rerank_score === null
      ? { rerank_score: value.rerank_score }
      : {}),
    ...(isRecord(value.score_components) ? { score_components: value.score_components } : {}),
  };
}

function parseGroundingSentence(value: unknown): GroundingSentence | null {
  if (
    !isRecord(value) ||
    typeof value.sentence !== "string" ||
    typeof value.supported !== "boolean"
  ) {
    return null;
  }
  return {
    sentence: value.sentence,
    supported: value.supported,
    ...(typeof value.similarity === "number" ? { similarity: value.similarity } : {}),
    ...(typeof value.keyword_overlap === "number"
      ? { keyword_overlap: value.keyword_overlap }
      : {}),
  };
}

function parseExplanation(value: unknown): ChatExplanation {
  if (!isRecord(value)) return {};
  const chunks = Array.isArray(value.chunks)
    ? value.chunks.map(parseEvidenceChunk).filter((chunk): chunk is EvidenceChunk => chunk !== null)
    : undefined;
  return {
    ...(chunks ? { chunks } : {}),
    ...(Array.isArray(value.answer_sentences)
      ? { answer_sentences: value.answer_sentences.filter((item): item is string => typeof item === "string") }
      : {}),
    ...(typeof value.provider === "string" ? { provider: value.provider } : {}),
    ...(typeof value.mode === "string" ? { mode: value.mode } : {}),
    ...(typeof value.latency_ms === "number" ? { latency_ms: value.latency_ms } : {}),
    ...(typeof value.retrieval_mode === "string"
      ? { retrieval_mode: value.retrieval_mode }
      : {}),
  };
}

function parseMessage(value: unknown): ChatMessageRecord | null {
  if (
    !isRecord(value) ||
    typeof value.id !== "number" ||
    typeof value.session_id !== "number" ||
    (value.role !== "user" && value.role !== "assistant") ||
    typeof value.content !== "string"
  ) {
    return null;
  }
  const citations = Array.isArray(value.citations)
    ? value.citations.filter(isRecord).map((citation) => ({
        ...(typeof citation.document_title === "string"
          ? { document_title: citation.document_title }
          : {}),
        ...(typeof citation.page === "number" ? { page: citation.page } : {}),
        ...(typeof citation.chunk_id === "number" || citation.chunk_id === null
          ? { chunk_id: citation.chunk_id }
          : {}),
      }))
    : [];
  return {
    id: value.id,
    session_id: value.session_id,
    role: value.role,
    content: value.content,
    citations,
    ...(typeof value.grounding_score === "number" || value.grounding_score === null
      ? { grounding_score: value.grounding_score }
      : {}),
    unsupported_sentences: Array.isArray(value.unsupported_sentences)
      ? value.unsupported_sentences.filter((item): item is string => typeof item === "string")
      : [],
    explanation: parseExplanation(value.explanation),
    ...(typeof value.provider === "string" || value.provider === null
      ? { provider: value.provider }
      : {}),
    ...(typeof value.latency_ms === "number" || value.latency_ms === null
      ? { latency_ms: value.latency_ms }
      : {}),
    ...(value.feedback === "thumbs_up" || value.feedback === "thumbs_down" || value.feedback === null
      ? { feedback: value.feedback }
      : {}),
    ...(typeof value.feedback_reason === "string" || value.feedback_reason === null
      ? { feedback_reason: value.feedback_reason }
      : {}),
    created_at: typeof value.created_at === "string" ? value.created_at : "",
  };
}

export async function createChatSession(title: string): Promise<ChatSession> {
  const result = await apiClient.POST("/chat/sessions", { body: { title } });
  const value: unknown = unwrapApiResult(result);
  if (!isChatSession(value)) {
    throw new Error("The chat session response was invalid.");
  }
  return value;
}

export async function listChatSessions(): Promise<ChatSession[]> {
  const result = await apiClient.GET("/chat/sessions");
  const value: unknown = unwrapApiResult(result);
  if (!Array.isArray(value) || !value.every(isChatSession)) {
    throw new Error("The chat history response was invalid.");
  }
  return value;
}

export async function getChatSession(sessionId: number): Promise<ChatSessionDetail> {
  const result = await apiClient.GET("/chat/sessions/{session_id}", {
    params: { path: { session_id: sessionId } },
  });
  const value: unknown = unwrapApiResult(result);
  if (!isChatSessionDetail(value)) {
    throw new Error("The chat session response was invalid.");
  }
  const messages = value.messages.map(parseMessage);
  if (messages.some((message) => message === null)) {
    throw new Error("The chat session contained an invalid message.");
  }
  return {
    ...value,
    messages: messages.filter((message): message is ChatMessageRecord => message !== null),
  };
}

export async function deleteChatSession(sessionId: number): Promise<void> {
  const result = await apiClient.DELETE("/chat/sessions/{session_id}", {
    params: { path: { session_id: sessionId } },
  });
  if (!result.response.ok) {
    throw new Error(`Could not delete the chat session (${result.response.status}).`);
  }
}

export async function submitChatFeedback(
  messageId: number,
  feedback: "thumbs_up" | "thumbs_down",
  reason?: string,
): Promise<void> {
  const result = await apiClient.POST("/chat/messages/{message_id}/feedback", {
    params: { path: { message_id: messageId } },
    body: { feedback, ...(reason ? { reason } : {}) },
  });
  unwrapApiResult(result);
}

export function chatMessageUrl(sessionId: number): string {
  return `/chat/sessions/${sessionId}/messages`;
}

export type ChatCompletion = {
  done: true;
  provider?: string;
  message?: string;
  citations?: ChatMessageRecord["citations"];
  grounding_score?: number;
  unsupported_sentences?: string[];
  explanation?: ChatExplanation;
  message_id?: number;
  latency_ms?: number;
};

export function parseChatEvent(data: string):
  | { token: string }
  | ChatCompletion
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
      ...("citations" in payload && Array.isArray(payload.citations)
        ? {
            citations: payload.citations.filter(isRecord).map((citation) => ({
              ...(typeof citation.document_title === "string"
                ? { document_title: citation.document_title }
                : {}),
              ...(typeof citation.page === "number" ? { page: citation.page } : {}),
              ...(typeof citation.chunk_id === "number" || citation.chunk_id === null
                ? { chunk_id: citation.chunk_id }
                : {}),
            })),
          }
        : {}),
      ...("grounding_score" in payload && typeof payload.grounding_score === "number"
        ? { grounding_score: payload.grounding_score }
        : {}),
      ...("unsupported_sentences" in payload && Array.isArray(payload.unsupported_sentences)
        ? {
            unsupported_sentences: payload.unsupported_sentences.filter(
              (sentence): sentence is string => typeof sentence === "string",
            ),
          }
        : {}),
      ...("explanation" in payload ? { explanation: parseExplanation(payload.explanation) } : {}),
      ...("message_id" in payload && typeof payload.message_id === "number"
        ? { message_id: payload.message_id }
        : {}),
      ...("latency_ms" in payload && typeof payload.latency_ms === "number"
        ? { latency_ms: payload.latency_ms }
        : {}),
    };
  }
  if ("message" in payload && typeof payload.message === "string") {
    return { message: payload.message };
  }
  return { message: data };
}
