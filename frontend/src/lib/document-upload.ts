import { apiBaseUrl } from "@/lib/api";
import { normalizeApiError } from "@/lib/errors";
import { getAccessToken, refreshSession } from "@/lib/session";
import type { DocumentRecord } from "@/lib/documents";

export const MAX_PDF_SIZE_BYTES = 20 * 1024 * 1024;
export const MAX_PDF_PAGES = 500;

export type FileValidationError = {
  file: File;
  message: string;
};

export function fileIdentity(file: File): string {
  return `${file.name.toLocaleLowerCase()}|${file.size}|${file.lastModified}`;
}

export function validatePdfFiles(
  files: File[],
  existingIdentities: Set<string> = new Set(),
): { accepted: File[]; rejected: FileValidationError[] } {
  const accepted: File[] = [];
  const rejected: FileValidationError[] = [];
  const identities = new Set(existingIdentities);

  for (const file of files) {
    const identity = fileIdentity(file);
    if (identities.has(identity)) {
      rejected.push({ file, message: "This file is already selected." });
      continue;
    }
    identities.add(identity);
    if (file.type !== "application/pdf" || !file.name.toLowerCase().endsWith(".pdf")) {
      rejected.push({ file, message: "Choose a PDF file." });
      continue;
    }
    if (file.size > MAX_PDF_SIZE_BYTES) {
      rejected.push({
        file,
        message: `This PDF exceeds the ${MAX_PDF_SIZE_BYTES / 1024 / 1024} MB size limit.`,
      });
      continue;
    }
    accepted.push(file);
  }
  return { accepted, rejected };
}

export async function estimatePdfPageCount(file: File): Promise<number | null> {
  const bytes = await file.arrayBuffer();
  const content = new TextDecoder("latin1").decode(bytes);
  const pageObjects = content.match(/\/Type\s*\/Page\b/g);
  return pageObjects?.length ?? null;
}

export type UploadRequestOptions = {
  signal: AbortSignal;
  onProgress: (progress: number) => void;
  xhrFactory?: () => XMLHttpRequest;
};

function sendUpload(
  file: File,
  token: string | null,
  options: UploadRequestOptions,
): Promise<{ status: number; body: unknown }> {
  return new Promise((resolve, reject) => {
    const xhr = options.xhrFactory?.() ?? new XMLHttpRequest();
    const formData = new FormData();
    formData.append("file", file, file.name);
    xhr.open("POST", `${apiBaseUrl}/documents/upload`);
    xhr.setRequestHeader("Accept", "application/json");
    if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) {
        options.onProgress(Math.min(100, Math.round((event.loaded / event.total) * 100)));
      }
    };
    xhr.onerror = () => reject(new Error("The upload connection failed."));
    xhr.onabort = () => reject(new DOMException("Upload canceled.", "AbortError"));
    xhr.onload = () => {
      let body: unknown;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        body = xhr.responseText;
      }
      resolve({ status: xhr.status, body });
    };
    const abort = () => xhr.abort();
    options.signal.addEventListener("abort", abort, { once: true });
    xhr.onloadend = () => options.signal.removeEventListener("abort", abort);
    if (options.signal.aborted) {
      xhr.abort();
      return;
    }
    xhr.send(formData);
  });
}

function isDocumentRecord(value: unknown): value is DocumentRecord {
  return (
    typeof value === "object" &&
    value !== null &&
    "id" in value &&
    typeof value.id === "number" &&
    "title" in value &&
    typeof value.title === "string" &&
    "status" in value &&
    typeof value.status === "string" &&
    "progress" in value &&
    typeof value.progress === "number" &&
    "error_message" in value &&
    (typeof value.error_message === "string" || value.error_message === null) &&
    "page_count" in value &&
    (typeof value.page_count === "number" || value.page_count === null) &&
    "language" in value &&
    (typeof value.language === "string" || value.language === null) &&
    "created_at" in value &&
    typeof value.created_at === "string"
  );
}

export async function uploadPdf(
  file: File,
  options: UploadRequestOptions,
): Promise<DocumentRecord> {
  const attempt = async (token: string | null) =>
    sendUpload(file, token, options);
  let response = await attempt(getAccessToken());
  if (response.status === 401) {
    const refreshed = await refreshSession();
    if (!refreshed) {
      throw normalizeApiError(401, response.body);
    }
    response = await attempt(getAccessToken());
  }
  if (response.status < 200 || response.status >= 300) {
    throw normalizeApiError(response.status, response.body);
  }
  if (!isDocumentRecord(response.body)) {
    throw new Error("The upload response did not contain a valid document.");
  }
  return response.body;
}
