import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/session", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/session")>();
  return { ...actual, redirectToLogin: vi.fn() };
});

import { getHealth } from "@/lib/api";
import {
  clearSession,
  getAccessToken,
  redirectToLogin,
  setSession,
  type SessionPayload,
} from "@/lib/session";
import { ApiError } from "@/lib/errors";

const session: SessionPayload = {
  access_token: "new-access",
  refresh_token: "new-refresh",
  token_type: "bearer",
  user: {
    id: 8,
    email: "student@example.test",
    full_name: "Student",
    role: "student",
    public_handle: "learner-1234",
    show_on_leaderboards: true,
  },
};

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("typed API client session refresh", () => {
  beforeEach(() => {
    localStorage.clear();
    clearSession();
    vi.mocked(redirectToLogin).mockClear();
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("refreshes once after a 401 and retries with the new access token", async () => {
    setSession({ ...session, access_token: "old-access", refresh_token: "old-refresh" });
    const fetchMock = vi.mocked(fetch);
    fetchMock
      .mockResolvedValueOnce(new Response(null, { status: 401 }))
      .mockResolvedValueOnce(jsonResponse(session))
      .mockResolvedValueOnce(jsonResponse({ status: "ok" }));

    await expect(getHealth()).resolves.toEqual({ status: "ok" });
    expect(fetchMock).toHaveBeenCalledTimes(3);
    const retryRequest = fetchMock.mock.calls[2][0] as Request;
    expect(retryRequest.headers.get("Authorization")).toBe("Bearer new-access");
  });

  it("shares one refresh request between concurrent 401 responses", async () => {
    setSession({ ...session, access_token: "old-access", refresh_token: "old-refresh" });
    let resolveRefresh!: (response: Response) => void;
    const refreshResponse = new Promise<Response>((resolve) => {
      resolveRefresh = resolve;
    });
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockImplementation((input) => {
      const requestUrl = input instanceof Request ? input.url : String(input);
      if (requestUrl.endsWith("/auth/refresh")) return refreshResponse;
      if (requestUrl.endsWith("/health")) {
        if (
          input instanceof Request &&
          input.headers.get("Authorization") === "Bearer new-access"
        ) {
          return Promise.resolve(jsonResponse({ status: "ok" }));
        }
        return Promise.resolve(new Response(null, { status: 401 }));
      }
      return Promise.resolve(jsonResponse({ status: "ok" }));
    });

    const first = getHealth();
    const second = getHealth();
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    resolveRefresh(jsonResponse(session));
    await expect(Promise.all([first, second])).resolves.toEqual([
      { status: "ok" },
      { status: "ok" },
    ]);
    expect(fetchMock).toHaveBeenCalledTimes(5);
  });

  it("clears the session and redirects when refresh fails", async () => {
    setSession({ ...session, access_token: "old-access", refresh_token: "old-refresh" });
    const fetchMock = vi.mocked(fetch);
    fetchMock
      .mockResolvedValueOnce(new Response(null, { status: 401 }))
      .mockResolvedValueOnce(new Response(null, { status: 401 }));

    await expect(getHealth()).rejects.toBeInstanceOf(ApiError);
    expect(getAccessToken()).toBeNull();
    expect(localStorage.getItem("study-assistant-refresh-token")).toBeNull();
    expect(redirectToLogin).toHaveBeenCalledOnce();
  });

  it("normalizes API errors for the UI", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ detail: "Invalid email or password." }, 401),
    );
    await expect(getHealth()).rejects.toMatchObject({
      message: "Invalid email or password.",
      status: 401,
    });
  });
});
