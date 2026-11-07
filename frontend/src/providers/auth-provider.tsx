"use client";

import { useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { toast } from "sonner";
import {
  getCurrentUser,
  isAuthenticated,
  restoreSession,
  subscribeToSessionChanges,
  type User,
} from "@/lib/session";

type AuthStatus = "loading" | "authenticated" | "unauthenticated";
type AuthContextValue = {
  status: AuthStatus;
  user: User | null;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [user, setUser] = useState<User | null>(null);
  const queryClient = useQueryClient();

  const syncSession = useCallback(() => {
    const activeUser = getCurrentUser();
    const authenticated = isAuthenticated() && activeUser !== null;
    setUser(activeUser);
    setStatus(authenticated ? "authenticated" : "unauthenticated");
    queryClient.setQueryData(["me"], activeUser);
  }, [queryClient]);

  useEffect(() => {
    const unsubscribe = subscribeToSessionChanges(syncSession);
    restoreSession()
      .then(syncSession)
      .catch((error: unknown) => {
        syncSession();
        toast.error(
          error instanceof Error ? error.message : "Could not restore your session.",
        );
      });
    return unsubscribe;
  }, [syncSession]);

  const value = useMemo(() => ({ status, user }), [status, user]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used within AuthProvider.");
  return context;
}
