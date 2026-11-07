export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, detail?: unknown) {
    super(getFriendlyMessage(status, detail));
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

function getFriendlyMessage(status: number, detail: unknown): string {
  if (typeof detail === "string" && detail.trim()) return detail;

  if (typeof detail === "object" && detail !== null && "detail" in detail) {
    const value = detail.detail;
    if (typeof value === "string" && value.trim()) return value;
    if (Array.isArray(value)) {
      const firstMessage = value.find(
        (item: unknown) =>
          typeof item === "object" &&
          item !== null &&
          "msg" in item &&
          typeof item.msg === "string",
      );
      if (firstMessage && "msg" in firstMessage) return firstMessage.msg;
    }
  }

  if (status === 401) return "Your session has expired. Please sign in again.";
  if (status === 403) return "You do not have permission to do that.";
  if (status === 404) return "The requested information could not be found.";
  if (status >= 500) return "The service is temporarily unavailable.";
  return "We could not complete your request. Check your details and try again.";
}

export function normalizeApiError(status: number, detail?: unknown): ApiError {
  return new ApiError(status, detail);
}
