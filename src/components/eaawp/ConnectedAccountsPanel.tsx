/**
 * The company's existing connections for one provider, with their real state, safe account details, and which AI
 * employees may use which capability.
 *
 * State comes from the integration record (status, enabled, last test, error) and the capability grants; account
 * details are only the non-secret fields the provider returned from its last successful test. Tokens are never shown.
 * Every button calls the existing admin-only API; the server enforces the rules, this screen only reflects them.
 */
import { useMemo, useState } from "react";
import { Loader2, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import {
  useCapabilityGrants,
  useCreateCapabilityGrant,
  useDeleteCapabilityGrant,
  useDeleteIntegration,
  useIntegrationProviders,
  useIntegrations,
  useTestIntegration,
  useUpdateIntegration,
  type CapabilityGrantOut,
  type IntegrationOut,
  type ProviderCapabilityOut,
} from "@/hooks/use-api";
import { apiErrorMessage } from "@/lib/api-client";
import { cn } from "@/lib/utils";

const ROLES: { key: string; name: string }[] = [
  { key: "DIGITAL_MARKETING_MANAGER", name: "Digital Marketing Manager" },
  { key: "DATA_INTELLIGENCE_ANALYST", name: "Data Analyst" },
  { key: "INSTITUTIONAL_CLERK", name: "Institutional Clerk" },
  { key: "MEDICAL_ASSISTANT", name: "Medical Assistant" },
];

// Non-secret account fields providers return from a connection test, with display labels.
const SAFE_ACCOUNT_FIELDS: Record<string, string> = {
  login: "Account",
  name: "Name",
  public_repos: "Public repositories",
  email: "Account email",
  site_url: "Site",
  default_property: "Selected property",
  property_name: "Property",
  server_name: "Server",
  server_version: "Server version",
  tool_count: "Tools discovered",
  database: "Database",
  host: "Host",
};

export type ConnectionState =
  | "connected"
  | "connected_no_access"
  | "not_verified"
  | "expired_or_revoked"
  | "error"
  | "switched_off"
  | "not_configured";

export function connectionState(
  i: IntegrationOut,
  grantCount: number,
): { state: ConnectionState; label: string; tone: string } {
  const err = (i.error_message ?? "").toLowerCase();
  if (!i.is_enabled && i.status === "connected")
    return {
      state: "switched_off",
      label: "Disconnected (switched off)",
      tone: "text-muted-foreground border-border",
    };
  if (i.status === "disabled")
    return {
      state: "switched_off",
      label: "Disconnected (switched off)",
      tone: "text-muted-foreground border-border",
    };
  if (i.status === "failed") {
    if (/401|403|revoked|expired|invalid_grant|bad credentials|unauthori/.test(err)) {
      return {
        state: "expired_or_revoked",
        label: "Expired or revoked — reconnect",
        tone: "text-destructive border-destructive/50",
      };
    }
    return { state: "error", label: "Error", tone: "text-destructive border-destructive/50" };
  }
  if (i.status === "not_tested")
    return {
      state: "not_verified",
      label: "Saved, not verified yet",
      tone: "text-warning border-warning/50",
    };
  if (i.status === "not_configured" || !i.has_credentials)
    return {
      state: "not_configured",
      label: "Not configured",
      tone: "text-muted-foreground border-border",
    };
  if (grantCount === 0)
    return {
      state: "connected_no_access",
      label: "Connected — no AI employee has access yet",
      tone: "text-warning border-warning/50",
    };
  return {
    state: "connected",
    label: "Connected and authorized",
    tone: "text-success border-success/50",
  };
}

function when(iso: string | null): string {
  if (!iso) return "never";
  const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : `${iso}Z`);
  return d.toLocaleString([], {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function GrantMatrix({
  integration,
  capabilities,
}: {
  integration: IntegrationOut;
  capabilities: ProviderCapabilityOut[];
}) {
  const { data: grants = [], isLoading } = useCapabilityGrants(integration.id);
  const create = useCreateCapabilityGrant(integration.id);
  const remove = useDeleteCapabilityGrant();
  const byKey = useMemo(() => {
    const m = new Map<string, CapabilityGrantOut>();
    for (const g of grants) if (g.is_granted) m.set(`${g.role_key}|${g.capability_key}`, g);
    return m;
  }, [grants]);
  const busy = create.isPending || remove.isPending;

  function toggle(role: string, cap: ProviderCapabilityOut) {
    const g = byKey.get(`${role}|${cap.key}`);
    if (g) {
      remove.mutate(
        { grantId: g.id, integrationId: integration.id },
        {
          onSuccess: () => toast.success(`Access removed: ${cap.display_name}.`),
          onError: (e) => toast.error(apiErrorMessage(e)),
        },
      );
    } else {
      create.mutate([{ role_key: role, capability_key: cap.key, is_granted: true }], {
        onSuccess: () => toast.success(`Access granted: ${cap.display_name}.`),
        onError: (e) => toast.error(apiErrorMessage(e)),
      });
    }
  }

  if (isLoading)
    return (
      <p className="text-[11px] text-muted-foreground">
        <Loader2 className="inline size-3 animate-spin" /> Loading access…
      </p>
    );

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[560px] border-collapse text-[11px]">
        <caption className="mb-1 text-left font-mono text-[9px] tracking-[0.1em] text-muted-foreground">
          WHICH AI EMPLOYEE MAY USE WHAT (READ = LOOK UP DATA · WRITE/HIGH RISK = NEVER RUN BY AN AI
          EMPLOYEE WITHOUT GOVERNANCE)
        </caption>
        <thead>
          <tr>
            <th className="border border-border px-2 py-1 text-left font-normal text-muted-foreground">
              Capability
            </th>
            {ROLES.map((r) => (
              <th
                key={r.key}
                className="border border-border px-2 py-1 font-normal text-muted-foreground"
              >
                {r.name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {capabilities.map((cap) => {
            const high = cap.risk_level === "high";
            return (
              <tr key={cap.key}>
                <td className="border border-border px-2 py-1">
                  <span className="text-foreground">{cap.display_name}</span>{" "}
                  <span
                    className={cn(
                      "font-mono text-[9px]",
                      high ? "text-destructive" : "text-muted-foreground",
                    )}
                  >
                    {cap.category.toUpperCase()} · {cap.risk_level.toUpperCase()}
                  </span>
                </td>
                {ROLES.map((r) => {
                  const on = byKey.has(`${r.key}|${cap.key}`);
                  return (
                    <td key={r.key} className="border border-border px-2 py-1 text-center">
                      <input
                        type="checkbox"
                        checked={on}
                        disabled={busy}
                        aria-label={`${cap.display_name} for ${r.name}`}
                        onChange={() => toggle(r.key, cap)}
                      />
                      {on && high && (
                        <span className="ml-1 font-mono text-[8px] text-destructive">
                          BLOCKED FOR AI
                        </span>
                      )}
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function ConnectionCard({
  integration,
  capabilities,
}: {
  integration: IntegrationOut;
  capabilities: ProviderCapabilityOut[];
}) {
  const { data: grants = [] } = useCapabilityGrants(integration.id);
  const test = useTestIntegration();
  const update = useUpdateIntegration(integration.id);
  const del = useDeleteIntegration();
  const [confirm, setConfirm] = useState(false);
  const [showAccess, setShowAccess] = useState(false);
  const granted = grants.filter((g) => g.is_granted);
  const st = connectionState(integration, granted.length);
  const account = Object.entries(integration.account_info ?? {}).filter(
    ([k, v]) => k in SAFE_ACCOUNT_FIELDS && v !== null && v !== "" && typeof v !== "object",
  );
  const busy = test.isPending || update.isPending || del.isPending;
  const btn =
    "border border-border px-2 py-1 font-mono text-[10px] tracking-[0.08em] hover:bg-foreground/5 disabled:opacity-40";

  return (
    <li
      className="space-y-2 border border-border bg-surface p-3"
      data-testid={`connection-${integration.provider_type}`}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-[13px] font-medium">{integration.display_name}</p>
          <p className="text-[11px] text-muted-foreground">
            Last checked: {when(integration.last_tested_at)}
          </p>
        </div>
        <span
          className={cn("border px-1.5 py-0.5 font-mono text-[10px] tracking-[0.06em]", st.tone)}
          data-testid="connection-state"
        >
          {st.label}
        </span>
      </div>

      {account.length > 0 && (
        <dl className="grid grid-cols-1 gap-x-4 gap-y-0.5 text-[12px] sm:grid-cols-2">
          {account.map(([k, v]) => (
            <div key={k} className="flex gap-2">
              <dt className="text-muted-foreground">{SAFE_ACCOUNT_FIELDS[k]}:</dt>
              <dd className="text-foreground">{String(v)}</dd>
            </div>
          ))}
        </dl>
      )}
      {integration.error_message && (st.state === "error" || st.state === "expired_or_revoked") && (
        <p className="border border-destructive/40 bg-destructive/5 p-2 text-[11px] text-destructive">
          {integration.error_message}
        </p>
      )}
      <p className="text-[11px] text-muted-foreground">
        {granted.length === 0
          ? "No AI employee may use this connection yet."
          : `Granted capabilities: ${granted.length} (${[...new Set(granted.map((g) => ROLES.find((r) => r.key === g.role_key)?.name ?? g.role_key))].join(", ")}).`}
      </p>

      <div className="flex flex-wrap gap-1.5">
        <button
          className={btn}
          disabled={busy}
          onClick={() =>
            test.mutate(integration.id, {
              onSuccess: (r) =>
                r.success
                  ? toast.success("Connection verified.")
                  : toast.error(`Connection test failed: ${r.error_message ?? "unknown error"}`),
              onError: (e) => toast.error(apiErrorMessage(e)),
            })
          }
        >
          {test.isPending ? (
            <Loader2 className="inline size-3 animate-spin" />
          ) : (
            <RefreshCw className="inline size-3" />
          )}{" "}
          TEST NOW
        </button>
        <button className={btn} onClick={() => setShowAccess((v) => !v)} aria-expanded={showAccess}>
          {showAccess ? "HIDE AI ACCESS" : "MANAGE AI ACCESS"}
        </button>
        <button
          className={btn}
          disabled={busy}
          onClick={() =>
            update.mutate(
              { is_enabled: !integration.is_enabled },
              {
                onSuccess: () =>
                  toast.success(
                    integration.is_enabled
                      ? "Connection switched off. AI employees can no longer use it."
                      : "Connection switched on.",
                  ),
                onError: (e) => toast.error(apiErrorMessage(e)),
              },
            )
          }
        >
          {integration.is_enabled ? "SWITCH OFF" : "SWITCH ON"}
        </button>
        {confirm ? (
          <button
            className={cn(btn, "border-destructive/60 text-destructive")}
            disabled={busy}
            onClick={() =>
              del.mutate(integration.id, {
                onSuccess: () =>
                  toast.success(
                    "Disconnected. Stored credentials and all access grants were deleted.",
                  ),
                onError: (e) => toast.error(apiErrorMessage(e)),
              })
            }
          >
            CONFIRM DISCONNECT
          </button>
        ) : (
          <button className={cn(btn, "text-destructive")} onClick={() => setConfirm(true)}>
            DISCONNECT…
          </button>
        )}
      </div>
      {showAccess && <GrantMatrix integration={integration} capabilities={capabilities} />}
    </li>
  );
}

export function ConnectedAccountsPanel({
  providerType,
  title,
}: {
  providerType: string;
  title?: string;
}) {
  const { data: integrations, isLoading, isError, error, refetch } = useIntegrations(providerType);
  const { data: providers } = useIntegrationProviders();
  const capabilities = providers?.find((p) => p.provider_type === providerType)?.capabilities ?? [];

  return (
    <section aria-label={title ?? "Existing connections"} className="space-y-2">
      <p className="font-mono text-[10px] tracking-[0.14em] text-muted-foreground">
        {(title ?? "Existing connections").toUpperCase()}
      </p>
      {isLoading ? (
        <p className="text-[12px] text-muted-foreground">
          <Loader2 className="inline size-3 animate-spin" /> Loading connections…
        </p>
      ) : isError ? (
        <p className="text-[12px] text-destructive">
          Could not load connections: {apiErrorMessage(error)}{" "}
          <button className="underline" onClick={() => void refetch()}>
            Try again
          </button>
        </p>
      ) : !integrations?.length ? (
        <p className="border border-dashed border-border p-3 text-[12px] text-muted-foreground">
          Not connected yet.
        </p>
      ) : (
        <ul className="space-y-2">
          {integrations.map((i) => (
            <ConnectionCard key={i.id} integration={i} capabilities={capabilities} />
          ))}
        </ul>
      )}
    </section>
  );
}
