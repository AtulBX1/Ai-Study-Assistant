import { apiClient, unwrapApiResult } from "@/lib/api";
import { clearSession, getRefreshToken, setSession } from "@/lib/session";
import type { User } from "@/lib/session";

export async function registerUser(input: {
  email: string;
  full_name: string;
  password: string;
}): Promise<User> {
  const result = await apiClient.POST("/auth/register", { body: input });
  const session = unwrapApiResult(result);
  setSession(session);
  return session.user;
}

export async function loginUser(input: {
  email: string;
  password: string;
}): Promise<User> {
  const result = await apiClient.POST("/auth/login", { body: input });
  const session = unwrapApiResult(result);
  setSession(session);
  return session.user;
}

export async function logoutUser(): Promise<void> {
  const refreshToken = getRefreshToken();
  try {
    if (refreshToken) {
      const result = await apiClient.POST("/auth/logout", {
        body: { refresh_token: refreshToken },
      });
      unwrapApiResult(result);
    }
  } finally {
    clearSession();
  }
}
