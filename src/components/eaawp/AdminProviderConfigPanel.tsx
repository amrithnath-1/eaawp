/**
 * AdminProviderConfigPanel
 *
 * Secure configuration panel for server-level integration provider settings.
 * Used when the Agent detects missing OAuth credentials (e.g. Google Client ID/Secret).
 *
 * Security invariants:
 * - Secret fields (client_secret, api_key, etc.) use type="password" inputs.
 * - After successful submit, all secret input state is cleared immediately.
 * - Values are NEVER stored in component state beyond the controlled input element.
 * - Configured fields show "******* (Configured ✓)" — no value is ever displayed.
 * - On 403, renders an inline permission-denied message (not just a toast).
 * - console.log is never called with secret field values.
 */

import { useState, useEffect, useCallback } from "react";
import { toast } from "sonner";
import {
  CheckCircle,
  AlertCircle,
  Lock,
  Copy,
  Loader2,
  ShieldCheck,
} from "lucide-react";
import { cn } from "@/lib/utils";

// ── Types ─────────────────────────────────────────────────────────────────────

interface ConfigurationStatusResponse {
  provider_type: string;
  state: "NOT_CONFIGURED" | "PARTIALLY_CONFIGURED" | "CONFIGURED" | "VALID" | "INVALID";
  configured_fields: string[];
  missing_fields: string[];
  oauth_ready: boolean;
  redirect_uri: string;
  message: string;
}

interface AdminProviderConfigPanelProps {
  providerType: string;
  providerDisplayName: string;
  onConfigured?: () => void;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * Determine whether a field key should use a password input.
 * Keys that end with or match these patterns are treated as secrets.
 */
const SECRET_KEY_SUFFIXES = ["secret", "key", "token", "password", "api_key", "app_secret"];

function isSecretField(fieldKey: string): boolean {
  const lower = fieldKey.toLowerCase();
  return SECRET_KEY_SUFFIXES.some(
    (suffix) => lower === suffix || lower.endsWith(`_${suffix}`)
  );
}

function getFieldDisplayName(fieldKey: string): string {
  return fieldKey
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

// ── Component ─────────────────────────────────────────────────────────────────

export function AdminProviderConfigPanel({
  providerType,
  providerDisplayName,
  onConfigured,
}: AdminProviderConfigPanelProps) {
  const [status, setStatus] = useState<ConfigurationStatusResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [permissionDenied, setPermissionDenied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Controlled input state — only holds values during the form session.
  // Secret inputs are cleared immediately after successful submit.
  const [fieldValues, setFieldValues] = useState<Record<string, string>>({});
  const [copied, setCopied] = useState(false);

  const fetchStatus = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await fetch(`/api/v1/admin/provider-config/${providerType}/status`, {
        headers: { "Content-Type": "application/json" },
        credentials: "include",
      });
      if (resp.status === 401) {
        setError("You must be logged in to view configuration status.");
        return;
      }
      if (!resp.ok) {
        setError(`Failed to load configuration status (${resp.status}).`);
        return;
      }
      const data = (await resp.json()) as ConfigurationStatusResponse;
      setStatus(data);
      // Initialise input values for missing fields (empty strings).
      const initial: Record<string, string> = {};
      for (const key of data.missing_fields) {
        initial[key] = "";
      }
      setFieldValues(initial);
    } catch {
      setError("Network error loading configuration status.");
    } finally {
      setLoading(false);
    }
  }, [providerType]);

  useEffect(() => {
    void fetchStatus();
  }, [fetchStatus]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!status) return;

    // Build payload — only include fields that have a non-empty value.
    const fields: Record<string, string> = {};
    for (const key of status.missing_fields) {
      const val = fieldValues[key];
      if (val && val.trim()) {
        fields[key] = val.trim();
      }
    }

    if (Object.keys(fields).length === 0) {
      toast.error("Please fill in at least one field before submitting.");
      return;
    }

    setSubmitting(true);
    setError(null);
    try {
      const resp = await fetch(`/api/v1/admin/provider-config/${providerType}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ fields }),
      });

      if (resp.status === 403) {
        setPermissionDenied(true);
        return;
      }

      if (resp.status === 422) {
        const body = (await resp.json()) as { detail?: string };
        const detail = body.detail ?? "Validation error. Check field values.";
        toast.error(detail);
        return;
      }

      if (!resp.ok) {
        toast.error(`Failed to save configuration (${resp.status}).`);
        return;
      }

      // SUCCESS — clear all secret input values from state immediately.
      const cleared: Record<string, string> = {};
      for (const key of Object.keys(fields)) {
        cleared[key] = ""; // explicit clear for secret hygiene
      }
      setFieldValues(cleared);

      toast.success("Configuration saved successfully.");
      onConfigured?.();
      // Re-fetch status to reflect the new state.
      await fetchStatus();
    } catch {
      toast.error("Network error saving configuration.");
    } finally {
      setSubmitting(false);
    }
  };

  const handleCopyRedirectUri = async () => {
    if (!status?.redirect_uri) return;
    try {
      await navigator.clipboard.writeText(status.redirect_uri);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error("Could not copy to clipboard.");
    }
  };

  // ── Render ────────────────────────────────────────────────────────────────

  if (permissionDenied) {
    return (
      <div className="border border-destructive/40 bg-destructive/5 p-3 text-[12px] text-destructive">
        <div className="flex items-center gap-2 font-mono font-semibold tracking-wide">
          <AlertCircle className="size-3.5" />
          PERMISSION DENIED
        </div>
        <p className="mt-1.5 text-muted-foreground">
          You do not have permission to configure this integration. Please ask your Company Admin.
        </p>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="flex items-center gap-2 p-3 text-[12px] text-muted-foreground">
        <Loader2 className="size-3.5 animate-spin" />
        Loading configuration status…
      </div>
    );
  }

  if (error) {
    return (
      <div className="border border-destructive/40 p-3 text-[12px] text-destructive">
        <AlertCircle className="mb-1 size-3.5" />
        {error}
        <button
          onClick={() => void fetchStatus()}
          className="ml-2 underline hover:no-underline"
        >
          Retry
        </button>
      </div>
    );
  }

  if (!status) return null;

  const allConfigured =
    status.state === "CONFIGURED" ||
    status.state === "VALID";

  return (
    <div className="border border-border bg-surface">
      {/* Header */}
      <div className="border-b border-border p-3">
        <div className="flex items-center gap-2">
          <ShieldCheck className="size-3.5 text-muted-foreground" />
          <p className="font-mono text-[10px] tracking-[0.14em] text-muted-foreground uppercase">
            {providerDisplayName} — Server Configuration
          </p>
        </div>
        <p className="mt-1 text-[11px] text-muted-foreground">
          {allConfigured
            ? "All required fields are configured."
            : `State: ${status.state.replace(/_/g, " ")} — ${status.missing_fields.length} field(s) missing.`}
        </p>
      </div>

      <div className="p-3 space-y-4">
        {/* Already-configured fields */}
        {status.configured_fields.length > 0 && (
          <div className="space-y-2">
            {status.configured_fields.map((key) => (
              <div key={key} className="flex items-center gap-2">
                <CheckCircle className="size-3.5 shrink-0 text-success" />
                <span className="text-[12px] text-foreground">
                  {getFieldDisplayName(key)}:
                </span>
                <span className="font-mono text-[11px] text-muted-foreground">
                  ******* (Configured ✓)
                </span>
              </div>
            ))}
          </div>
        )}

        {/* Configuration form — only shown if there are missing fields */}
        {!allConfigured && status.missing_fields.length > 0 && (
          <form onSubmit={(e) => void handleSubmit(e)} className="space-y-3">
            <p className="text-[11px] font-mono text-amber-600 dark:text-amber-400">
              MISSING FIELDS — please provide the following:
            </p>

            {status.missing_fields.map((key) => {
              const isSecret = isSecretField(key);
              const displayName = getFieldDisplayName(key);
              return (
                <div key={key} className="space-y-1">
                  <label className="flex items-center gap-1.5 font-mono text-[10px] tracking-[0.08em] text-muted-foreground uppercase">
                    {isSecret && <Lock className="size-3" />}
                    {displayName}
                    {isSecret && (
                      <span className="text-[9px] normal-case tracking-normal text-muted-foreground/70">
                        (encrypted at rest)
                      </span>
                    )}
                  </label>
                  <input
                    type={isSecret ? "password" : "text"}
                    value={fieldValues[key] ?? ""}
                    onChange={(e) =>
                      setFieldValues((prev) => ({
                        ...prev,
                        [key]: e.target.value,
                      }))
                    }
                    autoComplete={isSecret ? "new-password" : "off"}
                    spellCheck={false}
                    className="w-full h-8 border border-input bg-background px-2 font-mono text-[12px] outline-none focus:border-ring"
                    disabled={submitting}
                  />
                </div>
              );
            })}

            <button
              type="submit"
              disabled={submitting}
              className={cn(
                "inline-flex items-center gap-1.5 border border-foreground/20 bg-foreground/5",
                "px-3 py-1.5 font-mono text-[11px] tracking-[0.08em]",
                "hover:bg-foreground/10 disabled:opacity-40"
              )}
            >
              {submitting ? (
                <>
                  <Loader2 className="size-3 animate-spin" />
                  SAVING…
                </>
              ) : (
                "SAVE CONFIGURATION"
              )}
            </button>
          </form>
        )}

        {/* Redirect URI — shown for providers that need it */}
        {status.redirect_uri && (
          <div className="border border-border/50 bg-muted/20 p-2.5 space-y-1.5">
            <p className="font-mono text-[10px] tracking-[0.1em] text-muted-foreground uppercase">
              Authorized Redirect URI
            </p>
            <p className="text-[11px] text-muted-foreground">
              Register this exact URI in the provider&apos;s developer console:
            </p>
            <div className="flex items-center gap-2">
              <code className="flex-1 font-mono text-[11px] text-foreground break-all">
                {status.redirect_uri}
              </code>
              <button
                type="button"
                onClick={() => void handleCopyRedirectUri()}
                className={cn(
                  "shrink-0 border border-border/50 p-1 hover:bg-foreground/5",
                  copied && "border-success/40 text-success"
                )}
                title="Copy to clipboard"
              >
                {copied ? (
                  <CheckCircle className="size-3.5" />
                ) : (
                  <Copy className="size-3.5" />
                )}
              </button>
            </div>
          </div>
        )}

        {/* All configured — success state */}
        {allConfigured && (
          <div className="flex items-center gap-2 text-[12px] text-success">
            <CheckCircle className="size-3.5" />
            All configuration fields are set. OAuth flow is ready.
          </div>
        )}
      </div>
    </div>
  );
}

export default AdminProviderConfigPanel;
