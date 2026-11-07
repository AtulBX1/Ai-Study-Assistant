import { Suspense } from "react";
import { AuthForm } from "@/components/auth/auth-form";

export default function LoginPage() {
  return (
    <Suspense fallback={<div className="min-h-screen animate-pulse bg-muted" />}>
      <AuthForm mode="login" />
    </Suspense>
  );
}
