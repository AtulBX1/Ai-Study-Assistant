import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { NavigationLinks } from "@/components/app/app-shell";

vi.mock("next/navigation", () => ({
  usePathname: () => "/",
  useRouter: () => ({ replace: vi.fn() }),
}));

describe("main navigation", () => {
  it("shows Admin only for an administrator", () => {
    const { rerender } = render(
      <NavigationLinks isAdmin={false} onNavigate={vi.fn()} />,
    );
    expect(screen.queryByRole("link", { name: "Admin" })).toBeNull();

    rerender(<NavigationLinks isAdmin onNavigate={vi.fn()} />);
    expect(screen.getByRole("link", { name: "Admin" })).toBeTruthy();
  });
});
