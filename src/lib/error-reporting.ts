/**
 * EAAWP Error Reporting
 *
 * Structured error capture for both development and production.
 * All errors are captured with route, timestamp, and context.
 *
 * To add Sentry (recommended for production):
 *   1. npm install @sentry/react
 *   2. Add VITE_SENTRY_DSN to your .env
 *   3. Initialise in src/main.tsx: Sentry.init({ dsn: import.meta.env.VITE_SENTRY_DSN })
 *   4. Uncomment the Sentry lines below.
 */

export interface ErrorContext {
  [key: string]: unknown;
}

export function reportError(error: unknown, context: ErrorContext = {}): void {
  if (typeof window === "undefined") return;

  const message =
    error instanceof Response
      ? `HTTP ${error.status}${error.url ? ` at ${error.url}` : ""}`
      : error instanceof Error
        ? error.message
        : String(error);

  const entry = {
    message,
    route: window.location.pathname,
    timestamp: new Date().toISOString(),
    ...context,
  };

  // Always log to console so errors are visible in browser DevTools
  if (import.meta.env.DEV) {
    console.error("[EAAWP error]", entry, error);
  } else {
    // In production: still log a minimal entry so DevTools still work
    console.error("[EAAWP error]", entry.message, entry.timestamp);
  }

  // Keep a rolling buffer of the last 20 errors in localStorage so they
  // survive page reloads and can be retrieved from the browser console:
  //   JSON.parse(localStorage.getItem("eaawp.errors") ?? "[]")
  try {
    const key = "eaawp.errors";
    const existing: typeof entry[] = JSON.parse(localStorage.getItem(key) ?? "[]");
    existing.unshift(entry);
    localStorage.setItem(key, JSON.stringify(existing.slice(0, 20)));
  } catch {
    // localStorage may be full or unavailable — ignore silently
  }

  // ── Sentry integration (uncomment after adding @sentry/react) ─────────────
  // import * as Sentry from "@sentry/react";
  // Sentry.captureException(error instanceof Error ? error : new Error(message), {
  //   extra: entry,
  // });
}

/**
 * Retrieve the last N errors from localStorage.
 * Useful for debugging: call eaawp.getErrors() from the browser console.
 */
export function getRecentErrors(limit = 20): ErrorContext[] {
  try {
    const raw = localStorage.getItem("eaawp.errors") ?? "[]";
    return (JSON.parse(raw) as ErrorContext[]).slice(0, limit);
  } catch {
    return [];
  }
}

// Expose on window in dev for easy console debugging
if (typeof window !== "undefined" && import.meta.env.DEV) {
  // @ts-expect-error — intentional global for debugging
  window.eaawp = { ...(window.eaawp ?? {}), getErrors: getRecentErrors };
}
