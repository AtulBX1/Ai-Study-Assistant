import { describe, expect, it } from "vitest";
import { findPassageInTextLayer } from "@/lib/citation-matching";

function textLayer(parts: string[]): HTMLElement {
  const layer = document.createElement("div");
  layer.className = "textLayer";
  parts.forEach((part) => {
    const span = document.createElement("span");
    span.textContent = part;
    layer.append(span);
  });
  document.body.append(layer);
  return layer;
}

describe("citation text matching", () => {
  it("matches case-insensitively across line breaks, whitespace, and hyphenation", () => {
    const layer = textLayer(["The trans-", "former model uses multi\nhead attention."]);
    const match = findPassageInTextLayer(
      layer,
      "The TRANSFORMER model uses multi head attention.",
    );

    expect(match?.fuzzy).toBe(false);
    expect(match?.text).toBe("The trans-former model uses multi\nhead attention.");
    layer.remove();
  });

  it("falls back to the longest common run of at least eight words", () => {
    const layer = textLayer([
      "Evidence shows the model can learn contextual patterns from a limited training corpus.",
    ]);
    const match = findPassageInTextLayer(
      layer,
      "The paper says evidence shows the model can learn contextual patterns from a limited dataset.",
    );

    expect(match?.fuzzy).toBe(true);
    expect(match?.text?.toLocaleLowerCase()).toContain(
      "evidence shows the model can learn contextual patterns",
    );
    layer.remove();
  });

  it("returns no match when neither exact nor eight consecutive words match", () => {
    const layer = textLayer(["A short unrelated text sample."]);
    expect(findPassageInTextLayer(layer, "There is no relevant evidence in this document.")).toBeNull();
    layer.remove();
  });
});
