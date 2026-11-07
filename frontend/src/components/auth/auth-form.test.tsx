import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AuthForm } from "@/components/auth/auth-form";

const { loginUser } = vi.hoisted(() => ({ loginUser: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("@/providers/auth-provider", () => ({
  useAuth: () => ({ status: "unauthenticated", user: null }),
}));
vi.mock("@/lib/auth", () => ({
  loginUser: (...args: unknown[]) => loginUser(...args),
  registerUser: vi.fn(),
}));

describe("login form", () => {
  beforeEach(() => {
    loginUser.mockReset();
  });

  it("disables submit while pending and shows server errors", async () => {
    let rejectLogin!: (error: Error) => void;
    loginUser.mockImplementation(
      () =>
        new Promise((_, reject) => {
          rejectLogin = reject;
        }),
    );
    render(<AuthForm mode="login" />);

    fireEvent.change(screen.getByLabelText("Email"), {
      target: { value: "student@example.test" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "valid-password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    const pendingButton = screen.getByRole("button", { name: "Signing in…" });
    expect(pendingButton.hasAttribute("disabled")).toBe(true);

    rejectLogin(new Error("Invalid email or password."));
    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toContain(
        "Invalid email or password.",
      ),
    );
    expect(screen.getByRole("button", { name: "Sign in" }).hasAttribute("disabled")).toBe(
      false,
    );
  });
});
