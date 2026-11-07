"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { BrainCircuit, Eye, EyeOff } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { ErrorState } from "@/components/ui/error-state";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { loginUser, registerUser } from "@/lib/auth";
import { useAuth } from "@/providers/auth-provider";

type AuthMode = "login" | "register";

function isValidEmail(email: string): boolean {
  const [local, domain, extra] = email.trim().split("@");
  return Boolean(local && domain && !extra && domain.includes("."));
}

function passwordStrength(password: string): string {
  if (password.length < 8) return "Use at least 8 characters.";
  let score = 0;
  if (/[a-z]/.test(password)) score += 1;
  if (/[A-Z]/.test(password)) score += 1;
  if (/\d/.test(password)) score += 1;
  if (/[^A-Za-z0-9]/.test(password)) score += 1;
  return score >= 3 ? "Strong password." : "Use a mix of letters, numbers, or symbols.";
}

function safeReturnPath(value: string | null): string {
  if (!value || !value.startsWith("/") || value.startsWith("//")) return "/";
  return value;
}

export function AuthForm({ mode }: { mode: AuthMode }) {
  const { status } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);
  const submittedAuth = useRef(false);
  const isRegister = mode === "register";

  useEffect(() => {
    if (status === "authenticated" && !submittedAuth.current) router.replace("/");
  }, [router, status]);

  if (status === "loading" || status === "authenticated") {
    return <div className="mx-auto mt-24 h-80 max-w-md animate-pulse rounded-xl bg-muted" />;
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setValidationError(null);
    const normalizedEmail = email.trim().toLowerCase();
    if (!isValidEmail(normalizedEmail) || normalizedEmail.length > 320) {
      setValidationError("Enter a valid email address.");
      return;
    }
    if (password.length < 8 || password.length > 256) {
      setValidationError("Password must be between 8 and 256 characters.");
      return;
    }
    if (isRegister && fullName.trim().length === 0) {
      setValidationError("Enter your name.");
      return;
    }
    if (isRegister && fullName.trim().length > 160) {
      setValidationError("Name must be 160 characters or fewer.");
      return;
    }
    if (isRegister && password !== confirmation) {
      setValidationError("Passwords do not match.");
      return;
    }

    setPending(true);
    try {
      if (isRegister) {
        submittedAuth.current = true;
        await registerUser({
          email: normalizedEmail,
          full_name: fullName.trim(),
          password,
        });
        toast.success("Your study space is ready.");
        router.replace("/");
      } else {
        submittedAuth.current = true;
        await loginUser({ email: normalizedEmail, password });
        const returnPath = safeReturnPath(searchParams.get("next"));
        router.replace(returnPath);
      }
    } catch (caught: unknown) {
      setError(
        caught instanceof Error
          ? caught.message
          : "We could not complete your request. Please try again.",
      );
    } finally {
      setPending(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center px-4 py-10">
      <Card className="w-full max-w-md">
        <CardHeader className="pb-3 text-center">
          <Link href="/" className="mx-auto mb-4 grid size-11 place-items-center rounded-xl bg-primary text-primary-foreground">
            <BrainCircuit size={22} aria-hidden="true" />
          </Link>
          <h1 className="text-2xl font-semibold tracking-tight">
            {isRegister ? "Create your study space" : "Welcome back"}
          </h1>
          <p className="text-sm text-muted-foreground">
            {isRegister
              ? "A calmer way to learn from your course material."
              : "Sign in to continue learning."}
          </p>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            {isRegister ? (
              <div className="space-y-2">
                <Label htmlFor="full-name">Full name</Label>
                <Input
                  id="full-name"
                  name="full_name"
                  autoComplete="name"
                  value={fullName}
                  onChange={(event) => setFullName(event.target.value)}
                  maxLength={160}
                  required
                />
              </div>
            ) : null}
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                name="email"
                type="email"
                autoComplete="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                maxLength={320}
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <div className="relative">
                <Input
                  id="password"
                  name="password"
                  type={showPassword ? "text" : "password"}
                  autoComplete={isRegister ? "new-password" : "current-password"}
                  aria-describedby={isRegister ? "password-hint" : undefined}
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  maxLength={256}
                  required
                  className="pr-12"
                />
                <button
                  type="button"
                  className="absolute inset-y-0 right-0 grid w-11 place-items-center rounded-r-md text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  onClick={() => setShowPassword((visible) => !visible)}
                >
                  {showPassword ? (
                    <EyeOff size={17} aria-hidden="true" />
                  ) : (
                    <Eye size={17} aria-hidden="true" />
                  )}
                </button>
              </div>
              {isRegister ? (
                <p id="password-hint" className="text-xs text-muted-foreground">
                  {passwordStrength(password)}
                </p>
              ) : null}
            </div>
            {isRegister ? (
              <div className="space-y-2">
                <Label htmlFor="confirm-password">Confirm password</Label>
                <Input
                  id="confirm-password"
                  name="confirm_password"
                  type={showPassword ? "text" : "password"}
                  autoComplete="new-password"
                  value={confirmation}
                  onChange={(event) => setConfirmation(event.target.value)}
                  maxLength={256}
                  required
                />
              </div>
            ) : null}
            {validationError ? (
              <ErrorState title="Check your details" description={validationError} />
            ) : null}
            {error ? <ErrorState title="Unable to sign in" description={error} /> : null}
            <Button type="submit" className="w-full" disabled={pending}>
              {pending
                ? isRegister
                  ? "Creating account…"
                  : "Signing in…"
                : isRegister
                  ? "Create account"
                  : "Sign in"}
            </Button>
          </form>
          <p className="mt-6 text-center text-sm text-muted-foreground">
            {isRegister ? "Already have an account?" : "New to StudyMate?"}{" "}
            <Link
              href={isRegister ? "/login" : "/register"}
              className="font-medium text-primary underline-offset-4 hover:underline"
            >
              {isRegister ? "Sign in" : "Create an account"}
            </Link>
          </p>
        </CardContent>
      </Card>
    </main>
  );
}
