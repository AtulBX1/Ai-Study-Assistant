import { describe, expect, it, vi } from "vitest";
import {
  MAX_PDF_SIZE_BYTES,
  fileIdentity,
  uploadPdf,
  validatePdfFiles,
} from "@/lib/document-upload";

class FakeXMLHttpRequest {
  upload = { onprogress: null } as unknown as XMLHttpRequestUpload;
  status = 202;
  responseText = JSON.stringify({
    id: 1,
    title: "sample.pdf",
    status: "queued",
    progress: 0,
    error_message: null,
    page_count: 1,
    language: null,
    created_at: "2026-01-01T00:00:00Z",
  });
  headers = new Map<string, string>();
  sent = false;
  aborted = false;
  onload: (() => void) | null = null;
  onloadend: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;

  open(): void {}

  setRequestHeader(name: string, value: string): void {
    this.headers.set(name, value);
  }

  send(): void {
    this.sent = true;
    const upload = this.upload as unknown as {
      onprogress: ((event: ProgressEvent) => void) | null;
    };
    upload.onprogress?.({
      lengthComputable: true,
      loaded: 25,
      total: 100,
    } as ProgressEvent);
  }

  abort(): void {
    this.aborted = true;
    this.onabort?.();
    this.onloadend?.();
  }

  finish(): void {
    this.onload?.();
    this.onloadend?.();
  }
}

function pdfFile(
  name = "sample.pdf",
  options: { size?: number; type?: string; lastModified?: number } = {},
): File {
  return new File(
    [new Uint8Array(options.size ?? 32)],
    name,
    {
      type: options.type ?? "application/pdf",
      lastModified: options.lastModified ?? 1,
    },
  );
}

describe("PDF upload validation and transport", () => {
  it("rejects non-PDF, oversized, and duplicate files", () => {
    const pdf = pdfFile();
    const invalid = pdfFile("notes.txt", { type: "text/plain" });
    const tooLarge = pdfFile("large.pdf", { size: MAX_PDF_SIZE_BYTES + 1 });
    const result = validatePdfFiles([invalid, tooLarge, pdf, pdf]);

    expect(result.accepted).toEqual([pdf]);
    expect(result.rejected.map(({ message }) => message)).toEqual([
      "Choose a PDF file.",
      `This PDF exceeds the ${MAX_PDF_SIZE_BYTES / 1024 / 1024} MB size limit.`,
      "This file is already selected.",
    ]);
    expect(fileIdentity(pdf)).toBe(fileIdentity(pdfFile()));
  });

  it("reports upload progress and returns the queued document", async () => {
    const xhr = new FakeXMLHttpRequest();
    const onProgress = vi.fn();
    const request = uploadPdf(pdfFile(), {
      signal: new AbortController().signal,
      onProgress,
      xhrFactory: () => xhr as unknown as XMLHttpRequest,
    });

    expect(xhr.sent).toBe(true);
    expect(xhr.headers.get("Accept")).toBe("application/json");
    expect(onProgress).toHaveBeenCalledWith(25);
    xhr.finish();
    await expect(request).resolves.toMatchObject({ id: 1, status: "queued" });
  });

  it("cancels an active upload", async () => {
    const xhr = new FakeXMLHttpRequest();
    const controller = new AbortController();
    const request = uploadPdf(pdfFile(), {
      signal: controller.signal,
      onProgress: vi.fn(),
      xhrFactory: () => xhr as unknown as XMLHttpRequest,
    });
    controller.abort();

    await expect(request).rejects.toMatchObject({ name: "AbortError" });
    expect(xhr.aborted).toBe(true);
  });
});
