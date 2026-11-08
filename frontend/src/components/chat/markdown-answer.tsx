"use client";

import type { ReactNode } from "react";
import { isUnsupportedSentence } from "@/lib/study-utils";

export type Citation = { title: string; page: number };

type Props = {
  content: string;
  unsupportedSentences?: string[];
  onCitationClick: (page: number, title: string) => void;
};

function safeHref(value: string): string | null {
  try {
    const url = new URL(value, "https://study-assistant.invalid");
    return ["https:", "http:", "mailto:"].includes(url.protocol) ? value : null;
  } catch {
    return null;
  }
}

function inlineContent(
  text: string,
  onCitationClick: (page: number, title: string) => void,
): ReactNode[] {
  const pattern =
    /(\[[^\],]+,\s*p\.?\s*\d+\]|`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*|\[[^\]]+\]\([^)]+\))/gi;
  const output: ReactNode[] = [];
  let lastIndex = 0;
  for (const match of text.matchAll(pattern)) {
    const index = match.index ?? 0;
    if (index > lastIndex) output.push(text.slice(lastIndex, index));
    const token = match[0];
    const citation = /^\[([^\],]+),\s*p\.?\s*(\d+)\]$/i.exec(token);
    if (citation) {
      const title = citation[1].trim();
      const page = Number(citation[2]);
      output.push(
        <button
          key={`citation-${index}`}
          type="button"
          className="mx-1 inline-flex rounded-full border border-primary/30 bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary hover:bg-primary/20"
          aria-label={`Go to ${title}, page ${page}`}
          onClick={() => onCitationClick(page, title)}
        >
          {title}, p.{page}
        </button>,
      );
    } else if (token.startsWith("`")) {
      output.push(
        <code key={`code-${index}`} className="rounded bg-muted px-1 py-0.5">
          {token.slice(1, -1)}
        </code>,
      );
    } else if (token.startsWith("**")) {
      output.push(<strong key={`strong-${index}`}>{token.slice(2, -2)}</strong>);
    } else if (token.startsWith("*")) {
      output.push(<em key={`em-${index}`}>{token.slice(1, -1)}</em>);
    } else {
      const link = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(token);
      const href = link ? safeHref(link[2].trim()) : null;
      output.push(
        href ? (
          <a
            key={`link-${index}`}
            href={href}
            rel="noreferrer"
            target="_blank"
            className="text-primary underline underline-offset-2"
          >
            {link?.[1]}
          </a>
        ) : (
          link?.[1] ?? token
        ),
      );
    }
    lastIndex = index + token.length;
  }
  if (lastIndex < text.length) output.push(text.slice(lastIndex));
  return output;
}

export function MarkdownAnswer({
  content,
  unsupportedSentences = [],
  onCitationClick,
}: Props) {
  const blocks: ReactNode[] = [];
  const lines = content.split(/\r?\n/);
  let paragraph: string[] = [];
  let list: string[] = [];
  let code: string[] = [];
  let inCode = false;

  const flushParagraph = () => {
    if (!paragraph.length) return;
    blocks.push(
      <p key={`p-${blocks.length}`} className="whitespace-pre-wrap">
        {paragraph.map((line, index) => (
          <span key={index}>
            {index ? <br /> : null}
            {line.split(/(?<=[.!?])\s+/).map((sentence, sentenceIndex) =>
              isUnsupportedSentence(sentence.trim(), unsupportedSentences) ? (
                <span
                  key={`unsupported-${sentenceIndex}`}
                  className="underline decoration-wavy decoration-danger underline-offset-2"
                  title="Not found in your document"
                  aria-label={`${sentence} Not found in your document`}
                >
                  {inlineContent(sentence, onCitationClick)}
                </span>
              ) : (
                <span key={`sentence-${sentenceIndex}`}>
                  {inlineContent(sentence, onCitationClick)}
                </span>
              ),
            )}
          </span>
        ))}
      </p>,
    );
    paragraph = [];
  };
  const flushList = () => {
    if (!list.length) return;
    blocks.push(
      <ul key={`ul-${blocks.length}`} className="list-disc space-y-1 pl-5">
        {list.map((line, index) => (
          <li key={index}>{inlineContent(line, onCitationClick)}</li>
        ))}
      </ul>,
    );
    list = [];
  };
  const flushCode = () => {
    blocks.push(
      <pre
        key={`pre-${blocks.length}`}
        className="overflow-x-auto rounded-md bg-muted p-3 text-xs"
      >
        <code>{code.join("\n")}</code>
      </pre>,
    );
    code = [];
  };

  lines.forEach((line) => {
    if (line.trim().startsWith("```")) {
      if (inCode) flushCode();
      else {
        flushParagraph();
        flushList();
      }
      inCode = !inCode;
      return;
    }
    if (inCode) {
      code.push(line);
      return;
    }
    const heading = /^(#{1,3})\s+(.+)$/.exec(line);
    if (heading) {
      flushParagraph();
      flushList();
      const level = heading[1].length;
      const Tag = level === 1 ? "h3" : level === 2 ? "h4" : "h5";
      blocks.push(
        <Tag key={`heading-${blocks.length}`} className="font-semibold">
          {inlineContent(heading[2], onCitationClick)}
        </Tag>,
      );
      return;
    }
    const item = /^\s*[-*]\s+(.+)$/.exec(line);
    if (item) {
      flushParagraph();
      list.push(item[1]);
      return;
    }
    if (!line.trim()) {
      flushParagraph();
      flushList();
      return;
    }
    flushList();
    paragraph.push(line);
  });
  if (inCode) flushCode();
  flushParagraph();
  flushList();

  return <div className="space-y-2 break-words">{blocks}</div>;
}
