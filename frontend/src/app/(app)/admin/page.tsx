"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { ComingSoonPage } from "@/components/app/coming-soon-page";
import { useAuth } from "@/providers/auth-provider";
import { Skeleton } from "@/components/ui/skeleton";

export default function AdminPage() {
  const { user, status } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (status === "authenticated" && user?.role !== "admin") {
      router.replace("/");
    }
  }, [router, status, user]);

  if (status !== "authenticated" || user?.role !== "admin") {
    return <Skeleton className="h-48 w-full" />;
  }
  return (
    <ComingSoonPage
      title="Admin"
      description="Administrative tools for managing the study platform."
    />
  );
}
