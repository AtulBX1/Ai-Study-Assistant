"use client";

import { useQuery } from "@tanstack/react-query";
import { getCurrentUser } from "@/lib/session";
import { useAuth } from "@/providers/auth-provider";

export function useMe() {
  const { status } = useAuth();
  return useQuery({
    queryKey: ["me"],
    queryFn: async () => getCurrentUser(),
    enabled: status === "authenticated",
    staleTime: 30_000,
  });
}
