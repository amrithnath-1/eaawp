/**
 * GoogleSearchConsolePanel
 *
 * Integration Manager panel for Google Search Console (Phase 4).
 *
 * Supports the full integration lifecycle:
 *   DISCONNECTED → Connect (OAuth2) → CONNECTED → Test → ENABLED → Grant capabilities → DMM use
 *   CONNECTED → Disconnect
 *
 * Security notes:
 * - OAuth credentials are NEVER stored in React state.
 * - The authorization_url is received from the backend and used immediately
 *   for a browser redirect; it is not stored or displayed.
 * - Connection status is always authoritative from the backend.
 * - Capability grants are managed server-side; the UI only reads/displays them.
 * - The frontend never touches OAuth tokens, refresh tokens, or client secrets.
 */

import { useEffect, useState } from "react";
import { toast } from "sonner";
import { AdminProviderConfigPanel } from "./AdminProviderConfigPanel";
import {
  CheckCircle,
  XCircle,
  Clock,
  RefreshCw,
  ExternalLink,
  ShieldCheck,
  ShieldOff,
  Unplug,
  Search,
  BarChart2,
  Globe,
  Loader2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  useIntegrations,
  useTestIntegration,
  useDeleteIntegration,
  useUpdateIntegration,
  useCapabilityGrants,
  useCreateCapabilityGrant,
  useDeleteCapabilityGrant,
  useGscAuthorize,
  type IntegrationOut,
  type IntegrationStatus,
  type CapabilityGrantOut,
} from "@/hooks/use-api";

// ── Constants ─────────────────────────────────────────────────────────────────

const PROVIDER_TYPE = "google_search_console";

// GSC capabilities as declared by GoogleSearchConsoleProvider.
// Display order and labels come from the backend; these are kept in sync
// with the provider's get_capabilities() output.
const GSC_CAPABILITIES = [
  {
    key: "list_sites",
    label: "List Search Console Sites",
    description:
      "Retrieve all Search Console properties accessible to the connected Google account.",
    icon: Globe,
  },
  {
    key: "get_search_analytics",
    label: "Search Analytics",
    description: "Query search performance metrics — clicks, impressions, CTR, and position.",
    icon: BarChart2,
  },
  {
    key: "get_site_metadata",
    label: "Site Metadata",
    description: "Retrieve property verification status and permission levels.",
    icon: Search,
  },
] as const;

// Role keys that can be granted GSC capabilities.
// The grant system is the authority; this list drives the grant UI.
const GRANTABLE_ROLES = [
  { key: "DIGITAL_MARKETING_MANAGER", label: "Digital Marketing Manager" },
  { key: "CONTENT_STRATEGIST", label: "Content Strategist" },
  { key: "SEO_ANALYST", label: "SEO Analyst" },
] as const;

// ── Status badge ──────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: IntegrationStatus }) {
  const cfg: Record<IntegrationStatus, { icon: React.ElementType; cls: string; label: string }> = {
    not_configured: {
      icon: Clock,
      cls: "text-muted-foreground border-muted-foreground/40",
      label: "NOT CONNECTED",
    },
    not_tested: {
      icon: Clock,
      cls: "text-muted-foreground border-muted-foreground/40",
      label: "NOT TESTED",
    },
    connected: { icon: CheckCircle, cls: "text-success border-success/40", label: "CONNECTED" },
    failed: { icon: XCircle, cls: "text-destructive border-destructive/40", label: "FAILED" },
    disabled: {
      icon: ShieldOff,
      cls: "text-muted-foreground border-muted-foreground/40",
      label: "DISABLED",
    },
  };
  const { icon: Icon, cls, label } = cfg[status] ?? cfg.not_configured;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 border px-1.5 py-0.5 font-mono text-[10px] tracking-[0.08em]",
        cls,
      )}
    >
      <Icon className="size-2.5" />
      {label}
    </span>
  );
}

// ── Capability grants sub-panel ───────────────────────────────────────────────

function CapabilityGrantsPanel({ integrationId }: { integrationId: string }) {
  const { data: grants = [], isLoading } = useCapabilityGrants(integrationId);
  const createGrants = useCreateCapabilityGrant(integrationId);
  const deleteGrant = useDeleteCapabilityGrant();
  const [pendingRole, setPendingRole] = useState<string>(GRANTABLE_ROLES[0].key);

  function isGranted(roleKey: string, capKey: string): CapabilityGrantOut | undefined {
    return grants.find(
      (g) => g.role_key === roleKey && g.capability_key === capKey && g.is_granted,
    );
  }

  async function handleGrant(roleKey: string, capKey: string) {
    createGrants.mutate([{ role_key: roleKey, capability_key: capKey, is_granted: true }], {
      onSuccess: () => toast.success(`Granted ${capKey} to ${roleKey}`),
      onError: (e) => toast.error(e.message),
    });
  }

  async function handleRevoke(grant: CapabilityGrantOut) {
    deleteGrant.mutate(
      { grantId: grant.id, integrationId },
      {
        onSuccess: () => toast.success(`Revoked ${grant.capability_key} from ${grant.role_key}`),
        onError: (e) => toast.error(e.message),
      },
    );
  }

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 py-3 text-[12px] text-muted-foreground">
        <Loader2 className="size-3.5 animate-spin" /> Loading grants…
      </div>
    );
  }

  return (
    <div className="space-y-3 border border-border bg-surface p-3">
      <p className="font-mono text-[10px] tracking-[0.14em] text-muted-foreground">
        CAPABILITY GRANTS
      </p>
      <p className="text-[12px] text-muted-foreground">
        Grant specific capabilities to AI employees. The grant is the authority — a connected
        integration does not automatically give access to any role.
      </p>

      <div className="flex items-center gap-2">
        <label className="label-xs whitespace-nowrap">Grant to role:</label>
        <select
          value={pendingRole}
          onChange={(e) => setPendingRole(e.target.value)}
          className="h-7 border border-input bg-background px-2 text-[12px] outline-none focus:border-ring"
        >
          {GRANTABLE_ROLES.map((r) => (
            <option key={r.key} value={r.key}>
              {r.label}
            </option>
          ))}
        </select>
      </div>

      <div className="space-y-1.5">
        {GSC_CAPABILITIES.map(({ key, label, description, icon: Icon }) => {
          const grant = isGranted(pendingRole, key);
          return (
            <div
              key={key}
              className="flex items-start justify-between gap-3 border border-border p-2.5"
            >
              <div className="flex items-start gap-2.5 flex-1 min-w-0">
                <Icon className="size-3.5 mt-0.5 shrink-0 text-muted-foreground" />
                <div className="min-w-0">
                  <p className="font-mono text-[11px] tracking-[0.06em]">{label}</p>
                  <p className="mt-0.5 text-[11px] text-muted-foreground">{description}</p>
                </div>
              </div>
              <div className="shrink-0">
                {grant ? (
                  <button
                    onClick={() => void handleRevoke(grant)}
                    disabled={deleteGrant.isPending}
                    className="inline-flex items-center gap-1 border border-destructive/40 px-2 py-0.5 font-mono text-[10px] tracking-[0.08em] text-destructive hover:bg-destructive/10 disabled:opacity-50"
                  >
                    <ShieldOff className="size-2.5" /> REVOKE
                  </button>
                ) : (
                  <button
                    onClick={() => void handleGrant(pendingRole, key)}
                    disabled={createGrants.isPending}
                    className="inline-flex items-center gap-1 border border-success/40 px-2 py-0.5 font-mono text-[10px] tracking-[0.08em] text-success hover:bg-success/10 disabled:opacity-50"
                  >
                    <ShieldCheck className="size-2.5" /> GRANT
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {grants.length > 0 && (
        <div className="space-y-1 pt-1">
          <p className="font-mono text-[10px] tracking-[0.14em] text-muted-foreground">
            ACTIVE GRANTS
          </p>
          {grants
            .filter((g) => g.is_granted)
            .map((g) => (
              <div
                key={g.id}
                className="flex items-center justify-between text-[11px] text-muted-foreground border-l-2 border-success/40 pl-2 py-0.5"
              >
                <span>
                  <span className="text-foreground">{g.role_key}</span> → {g.capability_key}
                </span>
                <span className="font-mono text-[10px]">
                  {new Date(g.granted_at).toLocaleDateString()}
                </span>
              </div>
            ))}
        </div>
      )}
    </div>
  );
}

// ── Main panel ────────────────────────────────────────────────────────────────

export function GoogleSearchConsolePanel() {
  const { data: integrations = [], isLoading, refetch } = useIntegrations(PROVIDER_TYPE);
  const testMutation = useTestIntegration();
  const deleteMutation = useDeleteIntegration();
  const [currentIntegrationId, setCurrentIntegrationId] = useState<string>("");
  const updateMutation = useUpdateIntegration(currentIntegrationId);
  const gscAuthorize = useGscAuthorize();

  // Handle the OAuth2 callback redirect — the backend redirects back with
  // ?success=true&integration_id=...  or  ?error=...&error_description=...
  // We read the URL params once on mount and display a toast.
  const [callbackHandled, setCallbackHandled] = useState(false);
  useEffect(() => {
    if (callbackHandled) return;
    const params = new URLSearchParams(window.location.search);
    const success = params.get("success");
    const integrationId = params.get("integration_id");
    const error = params.get("error");
    const errorDescription = params.get("error_description");

    if (success === "true" && integrationId) {
      toast.success("Google Search Console connected. Run Test to verify.");
      void refetch();
      // Remove OAuth params from the URL without page reload
      const clean = new URL(window.location.href);
      clean.searchParams.delete("success");
      clean.searchParams.delete("integration_id");
      clean.searchParams.delete("provider_type");
      window.history.replaceState({}, "", clean.toString());
      setCallbackHandled(true);
    } else if (error) {
      const msg = errorDescription ?? error;
      toast.error(`Google authorization failed: ${msg}`);
      const clean = new URL(window.location.href);
      clean.searchParams.delete("error");
      clean.searchParams.delete("error_description");
      window.history.replaceState({}, "", clean.toString());
      setCallbackHandled(true);
    }
  }, [callbackHandled, refetch]);

  // The current integration (there should be at most one GSC integration per tenant).
  const integration: IntegrationOut | undefined = integrations[0];

  function handleConnect() {
    gscAuthorize.mutate(undefined, {
      onSuccess: (data) => {
        // Redirect browser to Google's authorization endpoint.
        // The state token is embedded in the URL by the backend.
        window.location.href = data.authorization_url;
      },
      onError: (err) => toast.error(err.message),
    });
  }

  function handleTest(id: string) {
    testMutation.mutate(id, {
      onSuccess: (result) => {
        if (result.success) {
          toast.success("Connection verified.");
        } else {
          toast.error(result.error_message ?? "Connection test failed.");
        }
        void refetch();
      },
      onError: (e) => toast.error(e.message),
    });
  }

  function handleDisconnect(id: string) {
    deleteMutation.mutate(id, {
      onSuccess: () => {
        toast.success("Google Search Console disconnected.");
        void refetch();
      },
      onError: (e) => toast.error(e.message),
    });
  }

  function handleToggleEnabled(intg: IntegrationOut) {
    setCurrentIntegrationId(intg.id);
    updateMutation.mutate(
      { is_enabled: !intg.is_enabled },
      {
        onSuccess: () => {
          toast.success(intg.is_enabled ? "Integration disabled." : "Integration enabled.");
          void refetch();
        },
        onError: (e) => toast.error(e.message),
      },
    );
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="font-mono text-[11px] tracking-[0.14em] text-muted-foreground">
            GOOGLE SEARCH CONSOLE
          </h3>
          <p className="mt-1 text-[13px] text-foreground">
            Read-only access to Search Console properties, search analytics, and site metadata.
          </p>
          <p className="mt-0.5 text-[12px] text-muted-foreground">
            All capabilities are read-only. No website modifications, publishing, or destructive
            operations.
          </p>
        </div>
        <a
          href="https://search.google.com/search-console"
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 border border-border px-2 py-1 font-mono text-[10px] tracking-[0.06em] text-muted-foreground hover:text-foreground"
        >
          <ExternalLink className="size-3" /> OPEN CONSOLE
        </a>
      </div>

      {/* Loading */}
      {isLoading && (
        <div className="flex items-center gap-2 py-4 text-[12px] text-muted-foreground">
          <Loader2 className="size-3.5 animate-spin" /> Loading integration status…
        </div>
      )}

      {/* Not connected (never connected, or disconnected): the Google OAuth app settings first, then Connect */}
      {!isLoading && !integration && (
        <AdminProviderConfigPanel
          providerType={PROVIDER_TYPE}
          providerDisplayName="Google Search Console"
          allowReplace
        />
      )}
      {!isLoading && !integration && (
        <div className="border border-border bg-surface p-4 space-y-3">
          <div className="flex items-center gap-2">
            <StatusBadge status="not_configured" />
          </div>
          <p className="text-[12px] text-muted-foreground">
            Connect your Google account to give AI employees read-only access to Search Console
            data. You will be redirected to Google to authorize access.
          </p>
          <div className="rounded border border-border/50 bg-muted/30 p-2.5 space-y-1">
            <p className="font-mono text-[10px] tracking-[0.1em] text-muted-foreground">
              PERMISSIONS REQUESTED
            </p>
            <p className="text-[12px] text-muted-foreground">
              <span className="font-mono text-[10px] text-foreground/70">
                https://www.googleapis.com/auth/webmasters.readonly
              </span>{" "}
              — read-only access to Search Console properties and analytics only.
            </p>
          </div>
          <button
            onClick={handleConnect}
            disabled={gscAuthorize.isPending}
            className="inline-flex items-center gap-2 border border-foreground/20 bg-foreground/5 px-3 py-1.5 font-mono text-[11px] tracking-[0.08em] hover:bg-foreground/10 disabled:opacity-50"
          >
            {gscAuthorize.isPending ? (
              <Loader2 className="size-3.5 animate-spin" />
            ) : (
              <ExternalLink className="size-3.5" />
            )}
            CONNECT WITH GOOGLE
          </button>
        </div>
      )}

      {/* Connected */}
      {!isLoading && integration && (
        <div className="space-y-3">
          {/* Status row */}
          <div className="border border-border bg-surface p-3 space-y-2">
            <div className="flex items-center justify-between gap-4 flex-wrap">
              <div className="flex items-center gap-2.5">
                <StatusBadge status={integration.status} />
                {integration.is_enabled && integration.status === "connected" && (
                  <span className="inline-flex items-center gap-1 border border-success/40 px-1.5 py-0.5 font-mono text-[10px] tracking-[0.08em] text-success">
                    <CheckCircle className="size-2.5" /> ENABLED
                  </span>
                )}
              </div>
              <div className="flex items-center gap-1.5 flex-wrap">
                <button
                  onClick={() => handleTest(integration.id)}
                  disabled={testMutation.isPending}
                  className="inline-flex items-center gap-1 border border-border px-2 py-0.5 font-mono text-[10px] tracking-[0.08em] hover:bg-muted/40 disabled:opacity-50"
                >
                  {testMutation.isPending ? (
                    <Loader2 className="size-2.5 animate-spin" />
                  ) : (
                    <RefreshCw className="size-2.5" />
                  )}
                  TEST
                </button>
                <button
                  onClick={() => handleDisconnect(integration.id)}
                  disabled={deleteMutation.isPending}
                  className="inline-flex items-center gap-1 border border-destructive/40 px-2 py-0.5 font-mono text-[10px] tracking-[0.08em] text-destructive hover:bg-destructive/10 disabled:opacity-50"
                >
                  {deleteMutation.isPending ? (
                    <Loader2 className="size-2.5 animate-spin" />
                  ) : (
                    <Unplug className="size-2.5" />
                  )}
                  DISCONNECT
                </button>
              </div>
            </div>

            {/* Account info */}
            {integration.account_info && Object.keys(integration.account_info).length > 0 && (
              <div className="border-t border-border/50 pt-2 text-[12px] text-muted-foreground space-y-0.5">
                {Object.entries(integration.account_info).map(([k, v]) => (
                  <div key={k} className="flex gap-2">
                    <span className="font-mono text-[10px] text-muted-foreground/70 w-32 shrink-0">
                      {k}
                    </span>
                    <span>{String(v)}</span>
                  </div>
                ))}
              </div>
            )}

            {/* Error message */}
            {integration.error_message && (
              <div className="border border-destructive/30 bg-destructive/5 p-2 text-[12px] text-destructive">
                {integration.error_message}
              </div>
            )}

            {/* Last tested */}
            {integration.last_tested_at && (
              <p className="text-[11px] text-muted-foreground">
                Last tested: {new Date(integration.last_tested_at).toLocaleString()}
              </p>
            )}
          </div>

          {/* Capabilities overview */}
          <div className="border border-border bg-surface p-3 space-y-2">
            <p className="font-mono text-[10px] tracking-[0.14em] text-muted-foreground">
              AVAILABLE CAPABILITIES
            </p>
            <div className="space-y-1">
              {GSC_CAPABILITIES.map(({ key, label, description, icon: Icon }) => (
                <div key={key} className="flex items-start gap-2.5 py-1">
                  <Icon className="size-3.5 mt-0.5 shrink-0 text-muted-foreground" />
                  <div>
                    <p className="font-mono text-[11px] tracking-[0.06em]">{label}</p>
                    <p className="text-[11px] text-muted-foreground">{description}</p>
                  </div>
                  <span className="ml-auto shrink-0 inline-flex items-center border border-success/40 px-1.5 py-0.5 font-mono text-[9px] tracking-[0.08em] text-success">
                    READ ONLY
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* Capability grants */}
          {integration.status === "connected" && (
            <CapabilityGrantsPanel integrationId={integration.id} />
          )}

          {/* Not connected yet — reconnect */}
          {integration.status !== "connected" && (
            <div className="border border-border bg-surface p-3 space-y-2">
              <p className="text-[12px] text-muted-foreground">
                Authorization is required before capabilities can be granted.
              </p>
              <button
                onClick={handleConnect}
                disabled={gscAuthorize.isPending}
                className="inline-flex items-center gap-2 border border-foreground/20 bg-foreground/5 px-3 py-1.5 font-mono text-[11px] tracking-[0.08em] hover:bg-foreground/10 disabled:opacity-50"
              >
                {gscAuthorize.isPending ? (
                  <Loader2 className="size-3.5 animate-spin" />
                ) : (
                  <ExternalLink className="size-3.5" />
                )}
                RECONNECT WITH GOOGLE
              </button>
            </div>
          )}
        </div>
      )}

      {/* Security notice */}
      <div className="border border-border/40 p-2.5 space-y-0.5">
        <p className="font-mono text-[10px] tracking-[0.1em] text-muted-foreground">SECURITY</p>
        <ul className="space-y-0.5 text-[11px] text-muted-foreground list-none">
          <li>• OAuth credentials are encrypted at rest and never returned to the browser.</li>
          <li>• Only the minimum required scope (webmasters.readonly) is requested.</li>
          <li>• All capability executions are recorded in the audit log.</li>
          <li>
            • Capability grants are required before any AI employee can access Search Console data.
          </li>
        </ul>
      </div>
    </div>
  );
}

export default GoogleSearchConsolePanel;
