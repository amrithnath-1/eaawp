/**
 * Lightweight error reporting utility.
 * Replace this with your own error tracking service (e.g. Sentry, Datadog) as needed.
 */

type ErrorOptions = {
  boundary?: string;
  severity?: "error" | "warning" | "info";
};

export function reportError(error: unknown, context: Record<string, unknown> = {}): void {
  if (typeof window === "undefined") return;

  const message =
    error instanceof Response
      ? `Response ${error.status}${error.url ? ` at ${error.url}` : ""}`
      : error instanceof Error
        ? error.message
        : String(error);

  const details = {
    message,
    route: window.location.pathname,
    timestamp: new Date().toISOString(),
    ...context,
  };

  // Log to console in development
  if (import.meta.env.DEV) {
    console.error("[reportError]", details, error);
  }

  // TODO: integrate your error tracking service here
  // e.g. Sentry.captureException(error, { extra: details });
}
