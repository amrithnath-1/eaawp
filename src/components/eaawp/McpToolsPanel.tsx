/**
 * McpToolsPanel - review the tools an MCP server exposes and grant them, one tool and one role at a time.
 * Nothing a server exposes is usable until it is granted here. High-risk tools cannot be granted for use at all.
 * Tool names and descriptions come from the server: they are shown as plain text only.
 */
import { useState } from "react";
import { toast } from "sonner";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { apiErrorMessage } from "@/lib/api-client";
import {
  useCapabilityGrants, useCreateCapabilityGrant, useDeleteCapabilityGrant, useDiscoverMcpTools, useIntegrations, useUpdateIntegration,
  type IntegrationOut, type McpToolFE,
} from "@/hooks/use-api";

const ROLES = [
  ["DIGITAL_MARKETING_MANAGER", "Digital Marketing Manager"], ["DATA_INTELLIGENCE_ANALYST", "Data Analyst"],
  ["INSTITUTIONAL_CLERK", "Institutional Clerk"], ["MEDICAL_ASSISTANT", "Medical Assistant"],
] as const;
const RISK_CLASS: Record<string, string> = { low: "border-success/40 text-success", medium: "border-warning/40 text-warning", high: "border-destructive/40 text-destructive" };

function ServerCard({ integ }: { integ: IntegrationOut }) {
  const update = useUpdateIntegration(integ.id);
  const discover = useDiscoverMcpTools();
  const grants = useCapabilityGrants(integ.id);
  const createGrants = useCreateCapabilityGrant(integ.id);
  const delGrant = useDeleteCapabilityGrant();
  const [tools, setTools] = useState<McpToolFE[] | null>(null);
  const [role, setRole] = useState<string>(ROLES[0][0]);
  const granted = new Map((grants.data ?? []).filter((g) => g.is_granted && g.role_key === role).map((g) => [g.capability_key, g.id]));

  const toggle = async (tool: McpToolFE) => {
    const key = `mcp_tool:${tool.entity_name}`;
    try {
      if (granted.has(key)) { await delGrant.mutateAsync({ grantId: granted.get(key)!, integrationId: integ.id }); toast.success(`Revoked ${tool.entity_name}`); return; }
      const need = [{ role_key: role, capability_key: key }];
      if (!granted.has("call_tool")) need.unshift({ role_key: role, capability_key: "call_tool" });
      await createGrants.mutateAsync(need); toast.success(`Granted ${tool.entity_name}`);
    } catch (e) { toast.error(apiErrorMessage(e)); }
  };

  return (
    <li data-testid={`mcp-${integ.id}`} className="space-y-3 border border-border bg-surface p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0"><h4 className="truncate text-[13px] font-medium">{integ.display_name}</h4>
          <p className="text-[11px] text-muted-foreground">{integ.status === "connected" ? "Connected" : `Not connected (${integ.status})`} · {integ.is_enabled ? "enabled" : "disabled"}</p></div>
        <div className="flex gap-2">
          <button type="button" className="border border-border px-3 py-1 text-[12px] hover:bg-accent disabled:opacity-50" disabled={integ.status !== "connected" || update.isPending}
            onClick={() => update.mutate({ is_enabled: !integ.is_enabled }, { onError: (e) => toast.error(apiErrorMessage(e)) })}>{integ.is_enabled ? "Disable" : "Enable"}</button>
          <button type="button" className="inline-flex items-center gap-1 border border-primary px-3 py-1 text-[12px] text-primary hover:bg-primary/10 disabled:opacity-50" disabled={integ.status !== "connected" || discover.isPending}
            onClick={() => discover.mutate(integ.id, { onSuccess: setTools, onError: (e) => toast.error(apiErrorMessage(e)) })}>
            {discover.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : null}Review tools</button>
        </div>
      </div>
      {tools && (
        <div className="space-y-2">
          <label className="flex items-center gap-2 text-[12px]">Grant to
            <select value={role} onChange={(e) => setRole(e.target.value)} aria-label="AI employee role" className="border border-border bg-background px-2 py-1">{ROLES.map(([k, n]) => <option key={k} value={k}>{n}</option>)}</select></label>
          {tools.length === 0 ? <p className="text-[12px] text-muted-foreground">This server exposes no usable tools.</p> : (
            <ul className="divide-y divide-border border border-border">
              {tools.map((t) => {
                const on = granted.has(`mcp_tool:${t.entity_name}`); const high = t.risk_level === "high";
                return (
                  <li key={t.entity_name} className="flex flex-wrap items-start justify-between gap-2 p-3">
                    <div className="min-w-0 flex-1"><div className="flex items-center gap-2"><code className="text-[12px]">{t.entity_name}</code>
                      <span className={cn("border px-1.5 py-0.5 font-mono text-[10px] uppercase", RISK_CLASS[t.risk_level ?? "low"])}>{t.risk_level ?? "low"} risk</span></div>
                      {t.description ? <p className="mt-1 text-[12px] text-muted-foreground">{t.description}</p> : null}</div>
                    {high ? <span className="text-[11px] text-muted-foreground">Cannot run automatically</span> : (
                      <button type="button" onClick={() => void toggle(t)} aria-label={`${on ? "Revoke" : "Grant"} ${t.entity_name}`}
                        className={cn("border px-3 py-1 text-[12px]", on ? "border-border hover:bg-accent" : "border-primary text-primary hover:bg-primary/10")}>{on ? "Revoke" : "Grant"}</button>)}
                  </li>);
              })}
            </ul>)}
        </div>)}
    </li>
  );
}

export function McpToolsPanel() {
  const q = useIntegrations("mcp");
  if (q.isLoading) return <p role="status" className="text-[12px] text-muted-foreground">Loading MCP servers…</p>;
  if (q.isError) return <p role="alert" className="text-[12px] text-destructive">Could not load MCP servers.</p>;
  const list = q.data ?? [];
  if (!list.length) return null;
  return (
    <section aria-label="Connected MCP servers" className="space-y-2">
      <h3 className="font-mono text-[10px] tracking-[0.14em]">CONNECTED SERVERS</h3>
      <ul className="space-y-3">{list.map((i) => <ServerCard key={i.id} integ={i} />)}</ul>
    </section>
  );
}
