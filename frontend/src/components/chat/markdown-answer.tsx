"use client";

import type { ReactNode } from "react";
import React from "react";
import ReactMarkdown from "react-markdown";
import rehypeKatex from "rehype-katex";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import remarkMath from "remark-math";
import { isUnsupportedSentence } from "@/lib/study-utils";

export type Citation = { title: string; page: number };

type Props = {
  content: string;
  unsupportedSentences?: string[];
  onCitationClick: (page: number, title: string) => void;
};

const safeMarkdownSchema = {
  ...defaultSchema,
  attributes: {
    ...defaultSchema.attributes,
    code: [...(defaultSchema.attributes?.code ?? []), ["className", "math-inline", "math-display"]],
    div: [...(defaultSchema.attributes?.div ?? []), ["className", "math-display"]],
  },
};

function transformText(markdown: string): string {
  const protectedCode = /(```[\s\S]*?```|~~~[\s\S]*?~~~|`[^`\n]*`)/g;
  return markdown.split(protectedCode).map((part, index) => {
    if (index % 2 === 1) return part;
    return part
      .replace(/\\\(/g, "$\u200b")
      .replace(/\\\)/g, "\u200b$")
      .replace(/\\\[/g, () => "\n$$\n")
      .replace(/\\\]/g, () => "\n$$\n")
      .replace(
        /\[([^\],]+),\s*p\.?\s*(\d+)\]/gi,
        (_match, title: string, page: string) =>
          `[${title}, p.${page}](https://citation.study-assistant.invalid/${page}/${encodeURIComponent(title.trim())})`,
      )
      .replace(/\$\$\u200b/g, "$$")
      .replace(/\u200b\$\$/g, "$$")
      .replace(/\$\u200b/g, "$")
      .replace(/\u200b\$/g, "$")
      .replace(/\$\$([^\n]+?)\$\$/g, (_match, formula: string) =>
        `\n$$\n${formula}\n$$\n`,
      );
  }).join("");
}

function markUnsupported(
  children: ReactNode,
  unsupportedSentences: string[],
): ReactNode {
  return React.Children.map(children, (child) => {
    if (typeof child !== "string") return child;
    const sentences = child.split(/(?<=[.!?])\s+/);
    return sentences.map((sentence, index) =>
      isUnsupportedSentence(sentence.trim(), unsupportedSentences) ? (
        <span
          key={`unsupported-${index}`}
          className="underline decoration-wavy decoration-danger underline-offset-2"
          title="Not found in your document"
          aria-label={`${sentence} Not found in your document`}
        >
          {sentence}
        </span>
      ) : (
        <React.Fragment key={`sentence-${index}`}>{sentence}</React.Fragment>
      ),
    );
  });
}

export function MarkdownAnswer({
  content,
  unsupportedSentences = [],
  onCitationClick,
}: Props) {
  return (
    <div className="markdown-answer space-y-2 break-words">
      <ReactMarkdown
        remarkPlugins={[remarkMath]}
        rehypePlugins={[[rehypeSanitize, safeMarkdownSchema], rehypeKatex]}
        components={{
          p: ({ children }) => (
            <p className="whitespace-pre-wrap">
              {markUnsupported(children, unsupportedSentences)}
            </p>
          ),
          h1: ({ children }) => <h3 className="font-semibold">{children}</h3>,
          h2: ({ children }) => <h4 className="font-semibold">{children}</h4>,
          h3: ({ children }) => <h5 className="font-semibold">{children}</h5>,
          ul: ({ children }) => <ul className="list-disc space-y-1 pl-5">{children}</ul>,
          ol: ({ children }) => <ol className="list-decimal space-y-1 pl-5">{children}</ol>,
          code: ({ children, className }) => (
            <code className={`${className ?? ""} rounded bg-muted px-1 py-0.5`}>{children}</code>
          ),
          pre: ({ children }) => (
            <pre className="overflow-x-auto rounded-md bg-muted p-3 text-xs">{children}</pre>
          ),
          a: ({ href, children }) => {
            const citation = /^\/(\d+)\/(.+)$/.exec(
              href?.startsWith("https://citation.study-assistant.invalid")
                ? new URL(href).pathname
                : "",
            );
            if (citation) {
              const title = decodeURIComponent(citation[2]);
              const page = Number(citation[1]);
              return (
                <button
                  type="button"
                  className="mx-1 inline-flex rounded-full border border-primary/30 bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary hover:bg-primary/20"
                  aria-label={`Go to ${title}, page ${page}`}
                  onClick={() => onCitationClick(page, title)}
                >
                  {title}, p.{page}
                </button>
              );
            }
            if (!href) return <>{children}</>;
            return (
              <a href={href} rel="noreferrer" target="_blank" className="text-primary underline underline-offset-2">
                {children}
              </a>
            );
          },
        }}
      >
        {transformText(content)}
      </ReactMarkdown>
    </div>
  );
}
