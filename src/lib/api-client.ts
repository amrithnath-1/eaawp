/**
 * EAAWP API Client
 *
 * Typed HTTP client that points at the FastAPI backend.
 * All service functions should go through this — never call fetch() directly
 * in components or the mock service layer.
 *
 * When VITE_USE_REAL_API is "false" (default), the service layer falls back
 * to mock data so the UI keeps working without a backend running.
 */

export const API_BASE_URL = import.meta.env["VITE_API_BASE_URL"] ?? "http://localhost:8000";
export const USE_REAL_API = import.meta.env["VITE_USE_REAL_API"] === "true";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly body: unknown,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function handleSessionExpired(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem("eaawp.access_token");
    window.localStorage.removeItem("eaawp.refresh_token");
    window.localStorage.removeItem("eaawp.session");
  } catch { /* ignore */ }
  if (window.location.pathname !== "/") window.location.assign("/");
}

async function request<T>(
  method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE",
  path: string,
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const url = `${API_BASE_URL}${path}`;

  // Inject the JWT access token. The tenant is derived server-side from the
  // verified token; no tenant header is sent (the backend ignores it).
  const accessToken = typeof window !== "undefined"
    ? window.localStorage.getItem("eaawp.access_token")
    : null;

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Accept: "application/json",
  };
  if (accessToken) headers["Authorization"] = `Bearer ${accessToken}`;

  const res = await fetch(url, {
    method,
    headers,
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    ...(signal !== undefined ? { signal } : {}),
  });

  if (res.status === 401 && accessToken) {
    // Token missing/expired/invalid on the server: drop the stale session so
    // the route guard sends the user back to the login page.
    handleSessionExpired();
  }

  if (!res.ok) {
    let errorBody: unknown;
    try {
      errorBody = await res.json();
    } catch {
      errorBody = await res.text();
    }
    throw new ApiError(
      res.status,
      errorBody,
      `API ${method} ${path} failed with status ${res.status}`,
    );
  }

  // 204 No Content
  if (res.status === 204) return undefined as T;

  return res.json() as Promise<T>;
}

export const apiClient = {
  get: <T>(path: string, signal?: AbortSignal) =>
    request<T>("GET", path, undefined, signal),

  post: <T>(path: string, body: unknown, signal?: AbortSignal) =>
    request<T>("POST", path, body, signal),

  put: <T>(path: string, body: unknown, signal?: AbortSignal) =>
    request<T>("PUT", path, body, signal),

  patch: <T>(path: string, body: unknown, signal?: AbortSignal) =>
    request<T>("PATCH", path, body, signal),

  delete: <T>(path: string, signal?: AbortSignal) =>
    request<T>("DELETE", path, undefined, signal),
};
