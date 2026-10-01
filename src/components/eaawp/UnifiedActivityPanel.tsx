/**
 * UnifiedActivityPanel — Unified Activity and Audit View
 *
 * Shows a unified stream of:
 * - Agent/employee activity events
 * - Tool executions (dynamic integration tools)
 * - Approvals (pending and resolved)
 * - Monitoring events
 * - Workflow executions
 * - Errors and failures
 *
 * LIVE vs SIMULATED: Events from real API calls are shown as LIVE.
 * Any mock-mode data is explicitly labelled SIMULATED.
 * Never claims simulated actions actually occurred externally.
 */
import { useState } from "react";
import { toast } from "sonner";
import {
  Activity, AlertTriangle, CheckCircle, Clock, XCircle,
  Loader2, RefreshCw, ShieldCheck, Zap, Eye,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { USE_REAL_API } from "@/lib/api-client";
import {
  useApprovalRequests,
  type ApprovalRequestOut,
} from "@/hooks/use-api";
import { useAuditLog, useExecutionTraces } from "@/hooks/use-api";

type EventKind = "approval" | "audit" | "trace" | "all";

interface ActivityItem {
  id: string;
  kind: EventKind;
  title: string;
  detail: string;
  status: string;
  actor: string;
  timestamp: string;
  isSimulated: boolean;
}

function kindIcon(kind: EventKind) {
  switch (kind) {
    case "approval": return ShieldCheck;
    case "trace":    return Zap;
    case "audit":    return Eye;
    default:         return Activity;
  }
}

function statusColor(status: string) {
  if (/approved|success|ok|completed/i.test(status)) return "text-success";
  if (/rejected|failed|error/i.test(status)) return "text-destructive";
  if (/pending|running|warning/i.test(status)) return "text-warning";
  return "text-muted-foreground";
}

function SimulatedBadge() {
  return (
    <span className="border border-warning/40 px-1.5 py-0.5 font-mono text-[9px] tracking-[0.06em] text-warning">
      SIMULATED
    </span>
  );
}

function LiveBadge() {
  return (
    <span className="border border-success/40 px-1.5 py-0.5 font-mono text-[9px] tracking-[0.06em] text-success">
      LIVE
    </span>
  );
}

function ActivityRow({ item }: { item: ActivityItem }) {
  const Icon = kindIcon(item.kind);
  return (
    <div className="flex items-start gap-2.5 border-b border-border/30 py-2 last:border-0">
      <Icon className="size-3.5 mt-0.5 shrink-0 text-muted-foreground" />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-mono text-[11px] tracking-[0.04em]">{item.title}</span>
          <span className={cn("font-mono text-[10px]", statusColor(item.status))}>
            {item.status.toUpperCase()}
          </span>
          {item.isSimulated ? <SimulatedBadge /> : <LiveBadge />}
        </div>
        {item.detail && (
          <p className="text-[11px] text-muted-foreground mt-0.5 truncate">{item.detail.slice(0, 150)}</p>
        )}
        <p className="text-[10px] text-muted-foreground/60 font-mono mt-0.5">
          {item.actor} · {new Date(item.timestamp).toLocaleString()}
        </p>
      </div>
    </div>
  );
}

export function UnifiedActivityPanel() {
  const [activeKind, setActiveKind] = useState<EventKind>("all");

  // Real data sources
  const { data: approvals = [], isLoading: loadingApprovals, refetch: refetchApprovals } =
    useApprovalRequests();
  const { data: auditLogs = [], isLoading: loadingAudit, refetch: refetchAudit } =
    useAuditLog();
  const { data: traces = [], isLoading: loadingTraces, refetch: refetchTraces } =
    useExecutionTraces();

  const isLoading = loadingApprovals || loadingAudit || loadingTraces;

  function handleRefresh() {
    void refetchApprovals();
    void refetchAudit();
    void refetchTraces();
    toast.success("Activity refreshed.");
  }

  // Build unified activity items from real data
  const items: ActivityItem[] = [];
  const isSimulated = !USE_REAL_API;

  // Approvals
  for (const a of approvals) {
    items.push({
      id: `approval-${a.id}`,
      kind: "approval",
      title: a.action,
      detail: a.detail.slice(0, 200),
      status: a.status,
      actor: a.requested_by,
      timestamp: a.created_at,
      isSimulated,
    });
  }

  // Audit logs
  for (const log of auditLogs) {
    items.push({
      id: `audit-${log.id}`,
      kind: "audit",
      title: String(log.event ?? "").slice(0, 80),
      detail: "",
      status: String(log.status ?? "ok"),
      actor: String(log.actor ?? "system"),
      timestamp: String(log.time ?? ""),
      isSimulated,
    });
  }

  // Execution traces
  for (const t of traces) {
    items.push({
      id: `trace-${t.id}`,
      kind: "trace",
      title: String(t.title ?? "").slice(0, 80),
      detail: t.steps.length > 0 ? `${t.steps.length} steps` : "",
      status: t.steps.length > 0 ? String(t.steps[t.steps.length - 1]?.kind ?? "unknown") : "unknown",
      actor: String(t.department ?? "agent"),
      timestamp: String(t.triggeredAt ?? ""),
      isSimulated,
    });
  }

  // Sort newest first
  items.sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime());

  const filtered = activeKind === "all" ? items : items.filter((i) => i.kind === activeKind);

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="font-mono text-[11px] tracking-[0.14em] text-muted-foreground">UNIFIED ACTIVITY</h3>
          <p className="mt-1 text-[13px] text-foreground">
            All agent activity, approvals, and audit events in one stream.
          </p>
          {isSimulated && (
            <div className="mt-1 inline-flex items-center gap-1.5 border border-warning/40 px-2 py-0.5">
              <AlertTriangle className="size-3 text-warning" />
              <span className="font-mono text-[10px] tracking-[0.08em] text-warning">
                DEMO MODE — events are simulated
              </span>
            </div>
          )}
        </div>
        <button
          onClick={handleRefresh}
          disabled={isLoading}
          className="shrink-0 inline-flex items-center gap-1.5 border border-border px-2.5 py-1 font-mono text-[10px] tracking-[0.08em] text-muted-foreground hover:text-foreground disabled:opacity-50"
        >
          {isLoading ? (
            <Loader2 className="size-3 animate-spin" />
          ) : (
            <RefreshCw className="size-3" />
          )}
          REFRESH
        </button>
      </div>

      {/* Kind filter */}
      <div className="flex gap-1 border-b border-border pb-2">
        {(["all", "approval", "audit", "trace"] as EventKind[]).map((k) => {
          const count = k === "all" ? items.length : items.filter((i) => i.kind === k).length;
          return (
            <button
              key={k}
              onClick={() => setActiveKind(k)}
              className={cn(
                "border px-2.5 py-0.5 font-mono text-[10px] tracking-[0.08em] capitalize",
                activeKind === k
                  ? "border-foreground/30 bg-foreground/5 text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              )}
            >
              {k === "trace" ? "EXECUTIONS" : k.toUpperCase()} {count > 0 && `(${count})`}
            </button>
          );
        })}
      </div>

      {/* Activity stream */}
      {isLoading ? (
        <div className="flex items-center gap-2 text-[12px] text-muted-foreground py-4">
          <Loader2 className="size-3.5 animate-spin" /> Loading activity...
        </div>
      ) : filtered.length === 0 ? (
        <div className="border border-border/40 p-4 text-center text-[12px] text-muted-foreground">
          {isSimulated
            ? "No activity recorded yet. Run the agent to generate activity."
            : "No activity found. Activity appears here as AI employees work."}
        </div>
      ) : (
        <div className="border border-border bg-surface divide-y divide-border/30">
          {filtered.slice(0, 100).map((item) => (
            <div key={item.id} className="px-3">
              <ActivityRow item={item} />
            </div>
          ))}
          {filtered.length > 100 && (
            <div className="px-3 py-2 text-center text-[11px] text-muted-foreground font-mono">
              Showing 100 of {filtered.length} events
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default UnifiedActivityPanel;
