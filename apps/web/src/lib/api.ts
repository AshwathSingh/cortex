export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly details?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function apiRequest<T>(
  path: `/api/${string}`,
  init?: RequestInit,
): Promise<T> {
  const headers = new Headers(init?.headers);
  if (!headers.has("Accept")) {
    headers.set("Accept", "application/json");
  }

  if (typeof init?.body === "string" && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(path, {
    ...init,
    credentials: "same-origin",
    headers,
  });

  const contentType = response.headers.get("content-type");
  const responseBody =
    response.status === 204
      ? undefined
      : contentType?.includes("application/json")
        ? await response.json()
        : await response.text();

  if (!response.ok) {
    const message =
      typeof responseBody === "object" &&
      responseBody !== null &&
      "detail" in responseBody &&
      typeof responseBody.detail === "string"
        ? responseBody.detail
        : "API request failed";

    throw new ApiError(message, response.status, responseBody);
  }

  return responseBody as T;
}
