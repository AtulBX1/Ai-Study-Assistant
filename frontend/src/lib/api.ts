export interface ApiHealth {
  status: string;
}

const apiBaseUrl =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export async function getHealth(): Promise<ApiHealth> {
  const response = await fetch(`${apiBaseUrl}/health`);
  if (!response.ok) {
    throw new Error(`API health check failed with status ${response.status}.`);
  }
  const payload: unknown = await response.json();
  if (
    typeof payload !== "object" ||
    payload === null ||
    !("status" in payload) ||
    typeof payload.status !== "string"
  ) {
    throw new Error("API health check returned an invalid response.");
  }
  return { status: payload.status };
}
