import createClient, { type Middleware } from "openapi-fetch";
import type { paths } from "@/lib/api/schema";
import {
  clearSession,
  getAccessToken,
  redirectToLogin,
  refreshSession,
} from "@/lib/session";
import { ApiError, normalizeApiError } from "@/lib/errors";

export interface ApiHealth {
  status: string;
}

export const apiBaseUrl =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const requestSnapshots = new WeakMap<Request, Request>();
const requestAccessTokens = new WeakMap<Request, string | null>();

const authMiddleware: Middleware = {
  async onRequest({ request }) {
    const headers = new Headers(request.headers);
    const token = getAccessToken();
    if (token) headers.set("Authorization", `Bearer ${token}`);
    const authenticatedRequest = new Request(request, { headers });
    requestSnapshots.set(authenticatedRequest, authenticatedRequest.clone());
    requestAccessTokens.set(authenticatedRequest, token);
    return authenticatedRequest;
  },
  async onResponse({ request, response }) {
    if (response.status !== 401) return response;

    const requestToken = requestAccessTokens.get(request);
    const currentToken = getAccessToken();
    let refreshed = Boolean(currentToken && currentToken !== requestToken);
    if (!refreshed) {
      try {
        refreshed = await refreshSession();
      } catch {
        clearSession();
      }
    }
    if (!refreshed) {
      redirectToLogin();
      return response;
    }

    const snapshot = requestSnapshots.get(request);
    if (!snapshot) return response;
    const headers = new Headers(snapshot.headers);
    const token = getAccessToken();
    if (token) headers.set("Authorization", `Bearer ${token}`);
    return fetch(new Request(snapshot, { headers }));
  },
};

export const apiClient = createClient<paths>({
  baseUrl: apiBaseUrl,
  fetch: (request: Request) => globalThis.fetch(request),
});
apiClient.use(authMiddleware);

type ApiResult<T> = {
  data?: T;
  error?: unknown;
  response: Response;
};

export function unwrapApiResult<T>(result: ApiResult<T>): T {
  if (!result.response.ok || result.data === undefined) {
    throw normalizeApiError(result.response.status, result.error);
  }
  return result.data;
}

export async function getHealth(): Promise<ApiHealth> {
  const result = await apiClient.GET("/health");
  const data = unwrapApiResult(result);
  if (
    typeof data !== "object" ||
    data === null ||
    !("status" in data) ||
    typeof data.status !== "string"
  ) {
    throw new ApiError(502, "The health response did not contain a valid status.");
  }
  return { status: data.status };
}
