import { describe, expect, it } from "vitest";
import {
  findCitationPassage,
  groundingLevel,
  isNotFoundRefusal,
  isUnsupportedSentence,
  speechLanguage,
  stripMarkdownAndCitations,
} from "@/lib/study-utils";

describe("grounded answer helpers", () => {
  it("labels each grounding threshold accessibly", () => {
    expect(groundingLevel(0.75).label).toBe("Well supported");
    expect(groundingLevel(0.5).label).toBe("Partly supported");
    expect(groundingLevel(0.49).label).toBe("Weakly supported");
  });

  it("recognizes unsupported sentences and the dedicated refusal state", () => {
    expect(isUnsupportedSentence("This claim is unsupported.", ["this claim is unsupported."])).toBe(true);
    expect(isNotFoundRefusal("not found in the document")).toBe(true);
    expect(isNotFoundRefusal("The document discusses this.")).toBe(false);
  });

  it("uses document evidence for citations and strips markup and citations for speech", () => {
    expect(
      findCitationPassage(2, "Unit I", [
        { page: 2, document_title: "Unit I", text: "Relevant source passage." },
      ]),
    ).toBe("Relevant source passage.");
    expect(stripMarkdownAndCitations("**Attention** [Unit I, p.2] uses *context*.")).toBe(
      "Attention uses context.",
    );
    expect(speechLanguage("Punjabi")).toBe("pa-IN");
  });
});
