import { afterEach, describe, expect, it, vi } from "vitest";
import { getHealth } from "./api";

describe("getHealth", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns the API health payload", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ status: "ok" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    await expect(getHealth()).resolves.toEqual({ status: "ok" });
  });

  it("reports non-success API responses", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(null, { status: 503 })),
    );

    await expect(getHealth()).rejects.toThrow(
      "API health check failed with status 503.",
    );
  });

  it("rejects an invalid health payload", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ status: 200 }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    await expect(getHealth()).rejects.toThrow(
      "API health check returned an invalid response.",
    );
  });
});
