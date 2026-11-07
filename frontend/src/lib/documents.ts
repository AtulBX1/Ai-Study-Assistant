import { apiClient, unwrapApiResult } from "@/lib/api";
import type { components } from "@/lib/api/schema";
import { normalizeApiError } from "@/lib/errors";

export type DocumentRecord = components["schemas"]["DocumentResponse"] & {
  is_private?: boolean;
};

export type DocumentPageRecord = components["schemas"]["DocumentPageResponse"];
export type DocumentStatusEvent = {
  document_id: number;
  status: string;
  progress: number;
  error_message: string | null;
};

export type KeyTerm = {
  term: string;
  page: number;
  definition?: string;
};

export const DOCUMENT_PAGE_SIZE = 20;

export async function listDocuments(
  offset: number,
  limit = DOCUMENT_PAGE_SIZE,
): Promise<DocumentRecord[]> {
  const result = await apiClient.GET("/documents", {
    params: { query: { limit, offset } },
  });
  return unwrapApiResult(result);
}

export async function getDocument(id: number): Promise<DocumentRecord> {
  const result = await apiClient.GET("/documents/{document_id}", {
    params: { path: { document_id: id } },
  });
  return unwrapApiResult(result);
}

export async function getDocumentStatus(id: number): Promise<DocumentRecord> {
  const result = await apiClient.GET("/documents/{document_id}/status", {
    params: { path: { document_id: id } },
  });
  return unwrapApiResult(result);
}

export async function deleteDocument(id: number): Promise<void> {
  const result = await apiClient.DELETE("/documents/{document_id}", {
    params: { path: { document_id: id } },
  });
  if (!result.response.ok) {
    throw normalizeApiError(result.response.status, result.error);
  }
}

export async function reindexDocument(id: number): Promise<void> {
  const result = await apiClient.POST("/documents/{document_id}/reindex", {
    params: { path: { document_id: id } },
  });
  unwrapApiResult(result);
}

export async function getDocumentPage(
  documentId: number,
  pageNumber: number,
): Promise<DocumentPageRecord> {
  const result = await apiClient.GET(
    "/documents/{document_id}/pages/{page_number}",
    { params: { path: { document_id: documentId, page_number: pageNumber } } },
  );
  return unwrapApiResult(result);
}

type GlossaryResponse = {
  items: Array<{
    term: string;
    definition?: string;
    page?: number;
    pages?: number[];
  }>;
  total: number;
  limit: number;
  offset: number;
};

function isGlossaryResponse(value: unknown): value is GlossaryResponse {
  return (
    typeof value === "object" &&
    value !== null &&
    "items" in value &&
    Array.isArray(value.items) &&
    "total" in value &&
    typeof value.total === "number"
  );
}

export async function getDocumentKeyTerms(
  documentId: number,
): Promise<KeyTerm[]> {
  const result = await apiClient.GET(
    "/study/documents/{document_id}/glossary",
    {
      params: {
        path: { document_id: documentId },
        query: { limit: 100, offset: 0 },
      },
    },
  );
  const payload: unknown = unwrapApiResult(result);
  if (!isGlossaryResponse(payload)) {
    throw new Error("The document glossary response was invalid.");
  }
  return payload.items.flatMap((item) => {
    const pages = item.pages ?? (typeof item.page === "number" ? [item.page] : []);
    return pages
      .filter((page) => Number.isInteger(page) && page > 0)
      .map((page) => ({
        term: item.term,
        page,
        ...(item.definition ? { definition: item.definition } : {}),
      }));
  });
}

export async function downloadDocument(
  id: number,
  signal?: AbortSignal,
): Promise<Blob> {
  const response = await authorizedDocumentFetch(
    `/documents/${id}/download`,
    signal,
  );
  if (!response.ok) {
    let detail: unknown;
    try {
      detail = await response.json();
    } catch {
      detail = undefined;
    }
    throw normalizeApiError(response.status, detail);
  }
  return response.blob();
}

export async function getDocumentPageImage(
  id: number,
  pageNumber: number,
  signal?: AbortSignal,
): Promise<Blob> {
  const response = await authorizedDocumentFetch(
    `/documents/${id}/pages/${pageNumber}/image`,
    signal,
  );
  if (!response.ok) {
    let detail: unknown;
    try {
      detail = await response.json();
    } catch {
      detail = undefined;
    }
    throw normalizeApiError(response.status, detail);
  }
  return response.blob();
}

async function authorizedDocumentFetch(
  path: string,
  signal?: AbortSignal,
): Promise<Response> {
  const { apiBaseUrl } = await import("@/lib/api");
  const { getAccessToken, refreshSession } = await import("@/lib/session");
  const request = () => {
    const headers = new Headers();
    const token = getAccessToken();
    if (token) headers.set("Authorization", `Bearer ${token}`);
    return fetch(`${apiBaseUrl}${path}`, { headers, signal });
  };
  let response = await request();
  if (response.status === 401 && (await refreshSession())) {
    response = await request();
  }
  return response;
}

export async function getPublicProfile(): Promise<{
  public_handle: string;
  show_on_leaderboards: boolean;
}> {
  const result = await apiClient.GET("/auth/profile");
  const payload: unknown = unwrapApiResult(result);
  if (
    typeof payload !== "object" ||
    payload === null ||
    !("public_handle" in payload) ||
    typeof payload.public_handle !== "string" ||
    !("show_on_leaderboards" in payload) ||
    typeof payload.show_on_leaderboards !== "boolean"
  ) {
    throw new Error("The profile response was invalid.");
  }
  return {
    public_handle: payload.public_handle,
    show_on_leaderboards: payload.show_on_leaderboards,
  };
}

export async function updatePublicProfile(input: {
  public_handle?: string;
  show_on_leaderboards?: boolean;
}) {
  const result = await apiClient.PATCH("/auth/profile", { body: input });
  return unwrapApiResult(result);
}
