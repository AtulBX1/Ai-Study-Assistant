import { ApiError } from "@/lib/errors";

export interface User {
  id: number;
  email: string;
  full_name: string;
  role: string;
  public_handle: string;
  show_on_leaderboards: boolean;
}

export interface SessionPayload {
  access_token: string;
  refresh_token: string;
  token_type: string;
  user: User;
}

const refreshStorageKey = "study-assistant-refresh-token";
const sessionEventName = "study-assistant-session-change";
const apiBaseUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
let accessToken: string | null = null;
let currentUser: User | null = null;
let refreshInFlight: Promise<boolean> | null = null;

function readRefreshToken(): string | null {
  try {
    return window.localStorage.getItem(refreshStorageKey);
  } catch {
    return null;
  }
}

function writeRefreshToken(token: string | null): void {
  try {
    if (token) window.localStorage.setItem(refreshStorageKey, token);
    else window.localStorage.removeItem(refreshStorageKey);
  } catch {
    // Access-token authentication remains available until this page is closed.
  }
}

function notifySessionChange(): void {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(sessionEventName));
  }
}

function isSessionPayload(value: unknown): value is SessionPayload {
  if (typeof value !== "object" || value === null) return false;
  const record = value as Record<string, unknown>;
  if (
    typeof record.access_token !== "string" ||
    typeof record.refresh_token !== "string" ||
    typeof record.user !== "object" ||
    record.user === null
  ) {
    return false;
  }
  const user = record.user as Record<string, unknown>;
  return (
    typeof user.id === "number" &&
    typeof user.email === "string" &&
    typeof user.public_handle === "string" &&
    typeof user.role === "string"
  );
}

export function setSession(session: SessionPayload): void {
  accessToken = session.access_token;
  currentUser = session.user;
  writeRefreshToken(session.refresh_token);
  notifySessionChange();
}

export function clearSession(): void {
  accessToken = null;
  currentUser = null;
  writeRefreshToken(null);
  notifySessionChange();
}

export function getAccessToken(): string | null {
  return accessToken;
}

export function getCurrentUser(): User | null {
  return currentUser;
}

export function updateCurrentUserProfile(
  profile: Partial<Pick<User, "public_handle" | "show_on_leaderboards">>,
): void {
  if (!currentUser) return;
  currentUser = { ...currentUser, ...profile };
  notifySessionChange();
}

export function isAuthenticated(): boolean {
  return accessToken !== null;
}

export function subscribeToSessionChanges(listener: () => void): () => void {
  if (typeof window === "undefined") return () => undefined;
  window.addEventListener(sessionEventName, listener);
  return () => window.removeEventListener(sessionEventName, listener);
}

export function redirectToLogin(): void {
  if (typeof window === "undefined" || window.location.pathname === "/login") {
    return;
  }
  const returnTo = `${window.location.pathname}${window.location.search}`;
  window.location.assign(`/login?next=${encodeURIComponent(returnTo)}`);
}

export function refreshSession(): Promise<boolean> {
  if (refreshInFlight) return refreshInFlight;
  const refreshToken =
    typeof window === "undefined" ? null : readRefreshToken();
  if (!refreshToken) {
    clearSession();
    return Promise.resolve(false);
  }

  refreshInFlight = (async () => {
    let response: Response;
    try {
      response = await fetch(`${apiBaseUrl}/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
    } catch (error) {
      clearSession();
      throw new ApiError(0, error instanceof Error ? error.message : undefined);
    }

    if (!response.ok) {
      clearSession();
      return false;
    }

    const payload: unknown = await response.json();
    if (!isSessionPayload(payload)) {
      clearSession();
      throw new ApiError(502, "The session refresh response was invalid.");
    }
    setSession(payload);
    return true;
  })().finally(() => {
    refreshInFlight = null;
  });
  return refreshInFlight;
}

export function restoreSession(): Promise<boolean> {
  return refreshSession();
}

export function getRefreshToken(): string | null {
  return typeof window === "undefined" ? null : readRefreshToken();
}
