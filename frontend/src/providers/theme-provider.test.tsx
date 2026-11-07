import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { ThemeToggle } from "@/components/theme-toggle";
import { ThemeProvider } from "@/providers/theme-provider";

describe("theme preference", () => {
  beforeEach(() => {
    localStorage.clear();
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
      value: () => ({ matches: false }),
    });
  });

  it("persists the selected theme and applies its class", async () => {
    render(
      <ThemeProvider>
        <ThemeToggle />
      </ThemeProvider>,
    );
    await waitFor(() => expect(screen.getByText("Dark mode")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "Switch to dark mode" }));
    expect(localStorage.getItem("study-assistant-theme")).toBe("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(screen.getByText("Light mode")).toBeTruthy();
  });
});
