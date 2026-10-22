/**
 * Role-specific dashboards for the /workspace page. Each one reads the role's real data through the existing hooks
 * (the server applies the usual per-person access rules: an employee sees their own requests/appointments, staff and
 * administrators see the company queue).
 */
import type { ReactNode } from "react";
import { Link } from "@tanstack/react-router";
import { AlertTriangle, ArrowRight, ShieldCheck } from "lucide-react";
import { KeyValue, Panel } from "@/components/eaawp/Panel";
import {
  useAnalysisReports, useCampaigns, useClerkRequests, useClinicAppointments, useDataConnections, useDatasets,
  type WorkspaceAiFE, type WorkspaceRoleKey,
} from "@/hooks/use-api";
import { apiErrorMessage } from "@/lib/api-client";
import { ROLE_META } from "@/lib/workspace";
import type { FileRoutesByTo } from "@/routeTree.gen";

function Stat({ label, value, tone }: { label: string; value: ReactNode; tone?: "warn" | undefined }) {
  return (
    <div className="border border-border bg-surface px-3 py-2">
      <div className="label-xs">{label}</div>
      <div className={`mt-1 font-mono text-xl ${tone === "warn" ? "text-warning" : "text-foreground"}`}>{value}</div>
    </div>
  );
}

function Action({ to, children, primary }: { to: keyof FileRoutesByTo; children: ReactNode; primary?: boolean }) {
  return (
    <Link
      to={to}
      className={primary
        ? "inline-flex items-center gap-1.5 border border-primary bg-primary px-3 py-1.5 font-mono text-[10px] tracking-[0.14em] text-primary-foreground"
        : "inline-flex items-center gap-1.5 border border-border px-3 py-1.5 font-mono text-[10px] tracking-[0.14em] text-muted-foreground hover:text-foreground"}
    >
      {children} <ArrowRight className="size-3" />
    </Link>
  );
}

function LoadState({ error, loading }: { error: unknown; loading: boolean }) {
  if (loading) return <p className="label-xs px-3 py-3">Loading…</p>;
  if (error) return <p className="px-3 py-3 text-[12px] text-destructive">{apiErrorMessage(error)}</p>;
  return null;
}

/** Shared header: what this AI employee is, what it may use, and the rules it works under. */
export function RoleHeader({ role, ai, actions }: { role: WorkspaceRoleKey; ai: WorkspaceAiFE; actions: ReactNode }) {
  const meta = ROLE_META[role];
  return (
    <div className="border-b border-border px-4 py-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start">
        <span className="hidden size-10 shrink-0 place-items-center border border-border-strong sm:grid"><meta.icon className="size-5" strokeWidth={1.5} /></span>
        <div className="min-w-0 flex-1">
          <h1 data-testid="dashboard-title" className="text-lg font-semibold tracking-tight">{meta.dashboardTitle}</h1>
          <p className="text-[13px] text-muted-foreground">{meta.dashboardSubtitle}</p>
        </div>
        <div className="flex flex-wrap gap-2">{actions}</div>
      </div>
      <div className="mt-3 grid grid-cols-1 gap-3 text-[12px] lg:grid-cols-3">
        <div>
          <div className="label-xs">AI employee</div>
          <p className="mt-1">
            {ai.agent_name} · {ai.allowed_tools.length} tools enabled · {ai.guarded_tools.length}{" "}
            {ai.guarded_tools.length === 1 ? "needs" : "need"} human approval
          </p>
        </div>
        <div>
          <div className="label-xs">Knowledge scope</div>
          <p className="mt-1 text-muted-foreground">{ai.knowledge_domain}</p>
        </div>
        <details data-testid="safety-rules">
          <summary className="label-xs flex cursor-pointer items-center gap-1"><ShieldCheck className="size-3" /> Safety rules ({ai.safety_rules.length})</summary>
          <ul className="mt-1 list-disc pl-4 text-muted-foreground">{ai.safety_rules.map((r) => <li key={r}>{r}</li>)}</ul>
        </details>
      </div>
    </div>
  );
}

// ── Institutional Clerk ───────────────────────────────────────────────────────

const OPEN_REQUEST = new Set(["submitted", "in_review", "needs_info"]);

export function ClerkDashboard() {
  const q = useClerkRequests();
  const items = q.data ?? [];
  return (
    <div data-testid="dashboard-clerk" className="grid grid-cols-1 gap-0 xl:grid-cols-[minmax(0,1fr)_320px]">
      <div className="p-4">
        <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
          <Stat label="Open requests" value={items.filter((r) => OPEN_REQUEST.has(r.status)).length} />
          <Stat label="Needs information" value={items.filter((r) => r.status === "needs_info").length} tone="warn" />
          <Stat label="Approved" value={items.filter((r) => r.status === "approved").length} />
          <Stat label="Fulfilled" value={items.filter((r) => r.status === "fulfilled").length} />
        </div>
        <Panel title="Latest service requests" dense className="mt-4 border border-border">
          <LoadState loading={q.isLoading} error={q.error} />
          {!q.isLoading && !q.error && items.length === 0 && <p className="px-3 py-3 text-[12px] text-muted-foreground">No service requests yet.</p>}
          <ul>
            {items.slice(0, 6).map((r) => (
              <li key={r.id} className="flex items-center justify-between gap-3 border-b border-border px-3 py-2 text-[12px] last:border-0">
                <span className="min-w-0 truncate">{r.title} <span className="text-muted-foreground">· {r.requester_name}</span></span>
                <span className="shrink-0 font-mono text-[10px] uppercase text-muted-foreground">{r.status.replace(/_/g, " ")}</span>
              </li>
            ))}
          </ul>
        </Panel>
      </div>
      <Panel title="Clerk workflow" dense className="border-l border-border">
        <div className="space-y-2 px-3 py-3 text-[12px] text-muted-foreground">
          <p>1. A request is filed (by the requester, or from an uploaded document using extraction).</p>
          <p>2. Staff review it; status changes the AI proposes wait for human approval.</p>
          <p>3. Documents are drafted from approved templates and issued only by a person.</p>
        </div>
      </Panel>
    </div>
  );
}

// ── Medical Assistant ─────────────────────────────────────────────────────────

export function ClinicDashboard() {
  const q = useClinicAppointments();
  const items = q.data ?? [];
  const flagged = items.filter((a) => a.red_flag && (a.status === "requested" || a.status === "confirmed"));
  return (
    <div data-testid="dashboard-clinic" className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_320px]">
      <div className="p-4">
        <div className="mb-3 flex items-start gap-2 border border-warning/50 bg-warning/5 px-3 py-2 text-[12px]">
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-warning" />
          Administrative support only. The assistant does not diagnose, interpret symptoms or recommend treatment. In an emergency call your local emergency number.
        </div>
        <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
          <Stat label="Requested" value={items.filter((a) => a.status === "requested").length} />
          <Stat label="Confirmed" value={items.filter((a) => a.status === "confirmed").length} />
          <Stat label="Urgent wording" value={flagged.length} tone={flagged.length ? "warn" : undefined} />
          <Stat label="Completed" value={items.filter((a) => a.status === "completed").length} />
        </div>
        <Panel title="Upcoming and recent appointments" dense className="mt-4 border border-border">
          <LoadState loading={q.isLoading} error={q.error} />
          {!q.isLoading && !q.error && items.length === 0 && <p className="px-3 py-3 text-[12px] text-muted-foreground">No appointment requests yet.</p>}
          <ul>
            {items.slice(0, 6).map((a) => (
              <li key={a.id} className="flex items-center justify-between gap-3 border-b border-border px-3 py-2 text-[12px] last:border-0">
                <span className="min-w-0 truncate">{a.patient_name} <span className="text-muted-foreground">· {a.preferred_time || "no preferred time"}</span></span>
                <span className="shrink-0 font-mono text-[10px] uppercase text-muted-foreground">{a.red_flag ? "⚠ " : ""}{a.status}</span>
              </li>
            ))}
          </ul>
        </Panel>
      </div>
      <Panel title="Access and privacy" dense className="border-l border-border">
        <div className="space-y-2 px-3 py-3 text-[12px] text-muted-foreground">
          <p>Patients see only their own requests. Clinic staff see the company queue.</p>
          <p>Every confirmation, reschedule or cancellation by the AI waits for a staff member's approval.</p>
          <p>Clinic conversations are never written to shared AI memory.</p>
        </div>
      </Panel>
    </div>
  );
}

// ── Data Analyst ──────────────────────────────────────────────────────────────

/** Admin-only API: rendered only for administrators so employees never trigger a refused request. */
function ConnectionCount() {
  const conns = useDataConnections();
  return <Stat label="DB connections" value={conns.isLoading ? "…" : conns.error ? "–" : (conns.data?.length ?? 0)} />;
}

export function AnalystDashboard({ isAdmin }: { isAdmin: boolean }) {
  const ds = useDatasets();
  const reports = useAnalysisReports();
  const datasets = ds.data ?? [];
  const rs = reports.data ?? [];
  return (
    <div data-testid="dashboard-analyst" className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_320px]">
      <div className="p-4">
        <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
          <Stat label="Datasets" value={datasets.length} />
          <Stat label="Rows available" value={datasets.reduce((n, d) => n + d.row_count, 0).toLocaleString()} />
          <Stat label="Saved reports" value={rs.length} />
          {isAdmin ? <ConnectionCount /> : <Stat label="DB connections" value="admin only" />}
        </div>
        <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
          <Panel title="Datasets" dense className="border border-border">
            <LoadState loading={ds.isLoading} error={ds.error} />
            {!ds.isLoading && !ds.error && datasets.length === 0 && <p className="px-3 py-3 text-[12px] text-muted-foreground">Upload a CSV to start exploring.</p>}
            <div className="px-3 py-1">
              {datasets.slice(0, 6).map((d) => <KeyValue key={d.id} k={d.name} v={`${d.row_count.toLocaleString()} rows${d.is_restricted ? " · restricted" : ""}`} />)}
            </div>
          </Panel>
          <Panel title="Latest reports" dense className="border border-border">
            <LoadState loading={reports.isLoading} error={reports.error} />
            {!reports.isLoading && !reports.error && rs.length === 0 && <p className="px-3 py-3 text-[12px] text-muted-foreground">No saved reports yet.</p>}
            <div className="px-3 py-1">
              {rs.slice(0, 6).map((r) => <KeyValue key={r.id} k={r.title} v={r.dataset_name} />)}
            </div>
          </Panel>
        </div>
      </div>
      <Panel title="Query safety" dense className="border-l border-border">
        <div className="space-y-2 px-3 py-3 text-[12px] text-muted-foreground">
          <p>Figures come from the deterministic analysis engine, never from the language model.</p>
          <p>Database access is read only, through admin-defined mappings and entity permissions; sensitive columns are blocked and every query is audited.</p>
        </div>
      </Panel>
    </div>
  );
}

// ── Digital Marketing Manager (summary strip above the existing overview) ─────

export function MarketingStrip() {
  const q = useCampaigns();
  const items = q.data ?? [];
  return (
    <div data-testid="dashboard-marketing" className="grid grid-cols-2 gap-2 border-b border-border p-4 md:grid-cols-4">
      <Stat label="Campaigns" value={q.isLoading ? "…" : items.length} />
      <Stat label="Active" value={items.filter((c) => c.status === "active").length} />
      <Stat label="Draft" value={items.filter((c) => c.status === "draft").length} />
      <Stat label="Completed" value={items.filter((c) => c.status === "completed").length} />
    </div>
  );
}

export const ROLE_ACTIONS: Record<WorkspaceRoleKey, (isAdmin: boolean) => ReactNode> = {
  DIGITAL_MARKETING_MANAGER: () => (<>
    <Action to="/cabin" primary>ASK THE AI</Action>
    <Action to="/customize">CAMPAIGNS & CONTENT</Action>
    <Action to="/integrations">ANALYTICS & SEO</Action>
  </>),
  INSTITUTIONAL_CLERK: () => (<>
    <Action to="/cabin" primary>ASK THE AI</Action>
    <Action to="/clerk">SERVICE REQUESTS</Action>
  </>),
  MEDICAL_ASSISTANT: () => (<>
    <Action to="/cabin" primary>ASK THE AI</Action>
    <Action to="/clinic">CLINIC DESK</Action>
  </>),
  DATA_INTELLIGENCE_ANALYST: (isAdmin) => (<>
    <Action to="/cabin" primary>ASK THE AI</Action>
    <Action to="/data">DATASETS & ANALYSIS</Action>
    {isAdmin && <Action to="/connections">DATABASE CONNECTIONS</Action>}
  </>),
};
