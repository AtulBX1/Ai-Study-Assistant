import { Suspense } from "react";
import { AuthForm } from "@/components/auth/auth-form";

export default function RegisterPage() {
  return (
    <Suspense fallback={<div className="min-h-screen animate-pulse bg-muted" />}>
      <AuthForm mode="register" />
    </Suspense>
  );
}
