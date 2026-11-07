"use client";

import { useEffect, type ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "@/providers/auth-provider";
import { Skeleton } from "@/components/ui/skeleton";

export function AuthGuard({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  const pathname = usePathname();
  const router = useRouter();

  useEffect(() => {
    if (status !== "unauthenticated") return;
    const returnTo =
      typeof window === "undefined"
        ? pathname
        : `${pathname}${window.location.search}`;
    router.replace(`/login?next=${encodeURIComponent(returnTo)}`);
  }, [pathname, router, status]);

  if (status !== "authenticated") {
    return (
      <main className="mx-auto max-w-7xl space-y-4 p-6" aria-label="Loading your study space">
        <Skeleton className="h-10 w-48" />
        <Skeleton className="h-48 w-full" />
      </main>
    );
  }
  return children;
}
