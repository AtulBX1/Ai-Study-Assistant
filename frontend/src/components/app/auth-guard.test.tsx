import { render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AuthGuard } from "@/components/app/auth-guard";

const { replace, useAuth } = vi.hoisted(() => ({
  replace: vi.fn(),
  useAuth: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/chat",
  useRouter: () => ({ replace }),
}));
vi.mock("@/providers/auth-provider", () => ({ useAuth: () => useAuth() }));

describe("protected route guard", () => {
  beforeEach(() => {
    replace.mockClear();
    useAuth.mockReturnValue({ status: "unauthenticated", user: null });
  });

  it("redirects unauthenticated visitors to login with their destination", async () => {
    render(
      <AuthGuard>
        <div>Protected content</div>
      </AuthGuard>,
    );
    await waitFor(() =>
      expect(replace).toHaveBeenCalledWith(
        "/login?next=%2Fchat",
      ),
    );
  });
});
