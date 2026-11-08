import type { ChatOptions } from "@/lib/chat";

export type GroundingLevel = {
  label: "Well supported" | "Partly supported" | "Weakly supported";
  className: string;
};

export function groundingLevel(score: number): GroundingLevel {
  if (score >= 0.75) {
    return {
      label: "Well supported",
      className: "border-emerald-600/40 bg-emerald-600/10 text-emerald-800 dark:text-emerald-200",
    };
  }
  if (score >= 0.5) {
    return {
      label: "Partly supported",
      className: "border-amber-600/40 bg-amber-600/10 text-amber-800 dark:text-amber-200",
    };
  }
  return {
    label: "Weakly supported",
    className: "border-red-600/40 bg-red-600/10 text-red-800 dark:text-red-200",
  };
}

export function normalizeSentence(value: string): string {
  return value.toLocaleLowerCase().replace(/\s+/g, " ").trim();
}

export function isUnsupportedSentence(
  sentence: string,
  unsupportedSentences: string[],
): boolean {
  const normalized = normalizeSentence(sentence);
  return unsupportedSentences.some((item) => normalizeSentence(item) === normalized);
}

export function isNotFoundRefusal(content: string): boolean {
  return normalizeSentence(content.replace(/[.!]+$/, "")) === "not found in the document";
}

export function stripMarkdownAndCitations(content: string): string {
  return content
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\[([^\]]+),\s*p\.?\s*\d+\]/gi, " ")
    .replace(/!\[([^\]]*)\]\([^)]+\)/g, "$1")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/^\s{0,3}#{1,6}\s+/gm, "")
    .replace(/^\s*[-*+]\s+/gm, "")
    .replace(/^\s*\d+\.\s+/gm, "")
    .replace(/(\*\*|__|\*|_|~~)/g, "")
    .replace(/[>#]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

export function speechLanguage(language: ChatOptions["language"]): string {
  switch (language) {
    case "Hindi":
      return "hi-IN";
    case "Punjabi":
      return "pa-IN";
    default:
      return "en-US";
  }
}

export function findCitationPassage(
  page: number,
  documentTitle: string | undefined,
  chunks: Array<{ page?: number; document_title?: string; text?: string }>,
  answerSentences: string[] = [],
): string {
  const evidence = chunks.find(
    (chunk) =>
      chunk.page === page &&
      (!documentTitle ||
        !chunk.document_title ||
        chunk.document_title.toLocaleLowerCase() === documentTitle.toLocaleLowerCase()) &&
      Boolean(chunk.text?.trim()),
  );
  if (evidence?.text) return evidence.text;
  const citedSentence = answerSentences.find((sentence) => {
    const citation = /\[([^\],]+),\s*p\.?\s*(\d+)\]/i.exec(sentence);
    return (
      Number(citation?.[2]) === page &&
      (!documentTitle ||
        citation?.[1].trim().toLocaleLowerCase() === documentTitle.toLocaleLowerCase())
    );
  });
  return citedSentence?.replace(/\[[^\]]+,\s*p\.?\s*\d+\]/gi, "").trim() ?? "";
}
