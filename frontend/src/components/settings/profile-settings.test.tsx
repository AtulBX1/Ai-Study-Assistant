import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { getPublicProfile, updatePublicProfile } = vi.hoisted(() => ({
  getPublicProfile: vi.fn(),
  updatePublicProfile: vi.fn(),
}));

vi.mock("@/lib/documents", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/documents")>();
  return { ...actual, getPublicProfile, updatePublicProfile };
});

import { ProfileSettings } from "@/components/settings/profile-settings";

describe("public profile settings", () => {
  beforeEach(() => {
    getPublicProfile.mockResolvedValue({
      public_handle: "learner-1234",
      show_on_leaderboards: true,
    });
    updatePublicProfile.mockRejectedValue(new Error("Public handle is unavailable."));
  });

  it("shows backend handle validation errors", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={client}>
        <ProfileSettings />
      </QueryClientProvider>,
    );

    const input = await screen.findByLabelText("Public handle");
    fireEvent.change(input, { target: { value: "taken-handle" } });
    fireEvent.click(screen.getByRole("button", { name: "Save profile settings" }));

    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toContain(
        "Public handle is unavailable.",
      ),
    );
  });
});
