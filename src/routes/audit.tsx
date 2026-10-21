import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { ChevronDown, Zap, Wrench, Database, Clock, CheckCircle2, XCircle } from "lucide-react";
import { AppShell } from "@/components/eaawp/AppShell";
import { PageHeader } from "@/components/eaawp/Panel";
import { auditService, departmentName } from "@/services";
import { downloadAuditCsv, useAuditHistory, useAuditLog, type AuditFilters } from "@/hooks/use-api";
import { useSession } from "@/state/session";
import { USE_REAL_API } from "@/lib/api-client";
import type { ExecutionStepKind, ExecutionTraceStep } from "@/services/types";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/audit")({
  component: AuditPage,
});

const MOCK_ACTORS = ["All", "AI", "Manager", "Company Admin", "System", "Employee"];
const VIEWS = ["Log", "Traces"] as const;

// ── Execution trace helpers ──────────────────────────────────────────────────

const STEP_ICON: Record<ExecutionStepKind, React.ReactNode> = {
  trigger:        <Zap        className="size-3.5" strokeWidth={1.8} />,
  tool_call:      <Wrench     className="size-3.5" strokeWidth={1.8} />,
  vector_search:  <Database   className="size-3.5" strokeWidth={1.8} />,
  approval_queued:<Clock      className="size-3.5" strokeWidth={1.8} />,
  result:         <CheckCircle2 className="size-3.5" strokeWidth={1.8} />,
  error:          <XCircle    className="size-3.5" strokeWidth={1.8} />,
};

const STEP_COLOUR: Record<ExecutionStepKind, string> = {
  trigger:        "border-primary/50 bg-primary/10 text-primary",
  tool_call:      "border-accent/50 bg-accent/10 text-accent",
  vector_search:  "border-info/50 bg-info/10 text-info",
  approval_queued:"border-warning/50 bg-warning/10 text-warning",
  result:         "border-success/50 bg-success/10 text-success",
  error:          "border-destructive/50 bg-destructive/10 text-destructive",
};

function TraceStep({ step }: { step: ExecutionTraceStep }) {
  const [open, setOpen] = useState(false);
  const hasMeta = step.meta.tokenCost !== undefined || step.meta.durationMs !== undefined || step.meta.payload;

  return (
    <li className="relative flex gap-3">
      {/* Timeline spine */}
      <div className="flex flex-col items-center">
        <span className={cn("mt-0.5 grid size-6 shrink-0 place-items-center border", STEP_COLOUR[step.kind])}>
          {STEP_ICON[step.kind]}
        </span>
        <div className="w-px flex-1 bg-border" />
      </div>

      <div className="mb-3 min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-2">
          <span className="font-mono text-[10px] text-muted-foreground">{step.time}</span>
          <span className="text-[13px] font-medium">{step.label}</span>
        </div>
        <p className="mt-0.5 font-mono text-[11px] text-muted-foreground">{step.detail}</p>

        {/* Inline meta chips */}
        <div className="mt-1 flex flex-wrap gap-2">
          {step.meta.durationMs !== undefined && (
            <span className="font-mono text-[10px] text-muted-foreground">{step.meta.durationMs}ms</span>
          )}
          {step.meta.tokenCost !== undefined && (
            <span className="font-mono text-[10px] text-muted-foreground">{step.meta.tokenCost} tokens</span>
          )}
        </div>

        {/* Expandable JSON payload */}
        {hasMeta && (
          <button
            onClick={() => setOpen((o) => !o)}
            className="mt-1 flex items-center gap-1 font-mono text-[10px] tracking-[0.1em] text-primary"
          >
            <ChevronDown className={cn("size-3 transition-transform", open && "rotate-180")} strokeWidth={2} />
            {open ? "HIDE" : "SHOW"} DETAILS
          </button>
        )}
        {open && (
          <pre className="mt-1 max-h-36 overflow-y-auto border border-border bg-surface-2 p-2 font-mono text-[11px] text-muted-foreground">
            {JSON.stringify(step.meta, null, 2)}
          </pre>
        )}
      </div>
    </li>
  );
}

function AuditPage() {
  const { user } = useSession();
  const isAdmin = !USE_REAL_API || user?.role === "Company Admin" || user?.role === "AI Administrator";
  // Mock mode keeps the old client-side behaviour; live mode uses the server: persistent history with filters, paging and export.
  const mockAudit = useAuditLog(isAdmin && !USE_REAL_API);
  const [view, setView] = useState<(typeof VIEWS)[number]>("Log");
  const [actor, setActor] = useState<string>("All");
  const [q, setQ] = useState("");
  const [qDebounced, setQDebounced] = useState("");
  const [department, setDepartment] = useState("All");
  const [status, setStatus] = useState("All");
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  useEffect(() => { const t = setTimeout(() => setQDebounced(q.trim()), 300); return () => clearTimeout(t); }, [q]);
  const filters: AuditFilters = useMemo(
    () => ({ q: qDebounced, actor, department, status, since, until }),
    [qDebounced, actor, department, status, since, until],
  );
  const history = useAuditHistory(filters, isAdmin);
  const rows = USE_REAL_API ? (history.data?.pages.flat() ?? []) : (mockAudit.data ?? []);
  // Live mode has no execution-trace feed yet: show an honest empty state, never sample traces.
  const traces = USE_REAL_API ? [] : auditService.traces();
  // Remember every actor / department / status seen so the filter options do not vanish once a filter is applied.
  const [seen, setSeen] = useState<{ actors: Record<string, string>; departments: string[]; statuses: string[] }>({ actors: {}, departments: [], statuses: [] });
  useEffect(() => {
    if (!USE_REAL_API || rows.length === 0) return;
    setSeen((prev) => {
      const actors = { ...prev.actors }; const deps = new Set(prev.departments); const sts = new Set(prev.statuses);
      for (const r of rows) { actors[r.actorKey ?? r.actor] = r.actor; if (r.department) deps.add(String(r.department)); if (r.status) sts.add(r.status); }
      const same = Object.keys(actors).length === Object.keys(prev.actors).length && deps.size === prev.departments.length && sts.size === prev.statuses.length;
      return same ? prev : { actors, departments: [...deps].sort(), statuses: [...sts].sort() };
    });
  }, [rows]);
  const ACTORS: { key: string; label: string }[] = useMemo(
    () => USE_REAL_API
      ? [{ key: "All", label: "All" }, ...Object.entries(seen.actors).map(([key, label]) => ({ key, label })).sort((x, y) => x.label.localeCompare(y.label))]
      : MOCK_ACTORS.map((a) => ({ key: a, label: a })),
    [seen.actors],
  );
  const [selectedTrace, setSelectedTrace] = useState(traces[0]?.id ?? "");
  const [exporting, setExporting] = useState(false);

  const filtered = useMemo(
    () => USE_REAL_API ? rows : rows.filter((r) => (actor === "All" || r.actor === actor) && r.event.toLowerCase().includes(q.toLowerCase())),
    [rows, actor, q],
  );
  const hasFilter = actor !== "All" || department !== "All" || status !== "All" || since !== "" || until !== "" || qDebounced !== "";
  async function exportCsv() {
    setExporting(true);
    try { await downloadAuditCsv(filters); toast.success("Audit log exported."); }
    catch (e) { toast.error(e instanceof Error ? e.message : "The export failed."); }
    finally { setExporting(false); }
  }

  const activeTrace = traces.find((t) => t.id === selectedTrace);

  return (
    <AppShell>
      <div className="p-4">
        <PageHeader title="Audit / activity" subtitle="Immutable record of what the AI and people did inside this environment." />

        {/* View toggle */}
        <div className="mt-3 flex gap-1.5">
          {VIEWS.map((v) => (
            <button
              key={v}
              onClick={() => setView(v)}
              className={cn(
                "border px-3 py-1.5 font-mono text-[10px] tracking-[0.14em]",
                view === v ? "border-foreground text-foreground" : "border-border text-muted-foreground hover:text-foreground",
              )}
            >
              {v === "Log" ? "ACTIVITY LOG" : "EXECUTION TRACES"}
            </button>
          ))}
        </div>

        {/* ── Activity Log view ── */}
        {view === "Log" && (
          <>
            {(!USE_REAL_API || isAdmin) && <div className="mt-3 flex flex-wrap items-center gap-1.5">
              <input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Search events…"
                aria-label="Search events"
                className="h-8 w-56 border border-input bg-surface px-2 text-xs outline-none focus:border-ring"
              />
              {ACTORS.map((a) => (
                <button
                  key={a.key}
                  onClick={() => setActor(a.key)}
                  className={cn(
                    "border px-2 py-1 font-mono text-[10px] tracking-[0.1em]",
                    actor === a.key ? "border-primary text-primary" : "border-border text-muted-foreground hover:text-foreground",
                  )}
                >
                  {a.label.toUpperCase()}
                </button>
              ))}
            </div>}
            {USE_REAL_API && isAdmin && (
              <div className="mt-2 flex flex-wrap items-center gap-2" data-testid="audit-filters">
                <select aria-label="Department" value={department} onChange={(e) => setDepartment(e.target.value)} className="h-8 border border-input bg-surface px-2 text-xs">
                  <option value="All">All departments</option>
                  {seen.departments.map((d) => <option key={d} value={d}>{departmentName(d)}</option>)}
                </select>
                <select aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value)} className="h-8 border border-input bg-surface px-2 text-xs">
                  <option value="All">All statuses</option>
                  {seen.statuses.map((x) => <option key={x} value={x}>{x}</option>)}
                </select>
                <label className="flex items-center gap-1 text-[11px] text-muted-foreground">From
                  <input type="date" aria-label="From date" value={since} max={until || undefined} onChange={(e) => setSince(e.target.value)} className="h-8 border border-input bg-surface px-2 text-xs" /></label>
                <label className="flex items-center gap-1 text-[11px] text-muted-foreground">To
                  <input type="date" aria-label="To date" value={until} min={since || undefined} onChange={(e) => setUntil(e.target.value)} className="h-8 border border-input bg-surface px-2 text-xs" /></label>
                {hasFilter && (
                  <button onClick={() => { setQ(""); setActor("All"); setDepartment("All"); setStatus("All"); setSince(""); setUntil(""); }}
                          className="font-mono text-[10px] tracking-[0.12em] text-muted-foreground hover:text-foreground">CLEAR FILTERS</button>
                )}
                <button onClick={() => void exportCsv()} disabled={exporting || rows.length === 0}
                        className="ml-auto border border-border px-3 py-1.5 font-mono text-[10px] tracking-[0.12em] text-muted-foreground hover:text-foreground disabled:opacity-40">
                  {exporting ? "EXPORTING…" : "EXPORT CSV"}
                </button>
              </div>
            )}
            <div className="mt-4 overflow-x-auto border border-border">
              <div className="min-w-[640px]">
              <div className={cn("grid gap-3 border-b border-border bg-surface-2 px-3 py-2", USE_REAL_API ? "grid-cols-[120px_2fr_1fr_1fr_90px]" : "grid-cols-[70px_2fr_1fr_1fr_90px]")}>
                {["Time", "Event", "Actor", "Department", "Status"].map((h) => (
                  <span key={h} className="label-xs">{h}</span>
                ))}
              </div>
              {filtered.map((r) => (
                <div key={r.id} data-testid="audit-row" className={cn("grid gap-3 border-b border-border px-3 py-2 last:border-0 hover:bg-surface", USE_REAL_API ? "grid-cols-[120px_2fr_1fr_1fr_90px]" : "grid-cols-[70px_2fr_1fr_1fr_90px]")}>
                  <span className="font-mono text-[11px] text-muted-foreground">{r.time}</span>
                  <span className="break-words text-[13px]">{r.event}</span>
                  <span className={cn("break-words font-mono text-[11px]", r.actor === "AI" ? "text-primary" : "text-foreground")}>{r.actor}</span>
                  <span className="font-mono text-[11px] text-muted-foreground">{r.department ? departmentName(r.department) : "—"}</span>
                  <span className={cn("font-mono text-[10px] tracking-[0.12em]", r.status === "ok" ? "text-success" : r.status === "pending" || r.status === "warning" ? "text-warning" : "text-destructive")}>
                    {r.status.toUpperCase()}
                  </span>
                </div>
              ))}
              {USE_REAL_API && history.isLoading && <div className="px-3 py-6 text-center text-xs text-muted-foreground">Loading…</div>}
              {USE_REAL_API && history.isError && <div role="alert" className="px-3 py-6 text-center text-xs text-destructive">The audit history could not be loaded.</div>}
              {filtered.length === 0 && !(USE_REAL_API && (history.isLoading || history.isError)) && (
                <div className="px-3 py-6 text-center text-xs text-muted-foreground">
                  {USE_REAL_API && !isAdmin ? "Only administrators can view the audit log." : hasFilter ? "No events match these filters." : "No live audit records are available."}
                </div>
              )}
              </div>
            </div>
            {USE_REAL_API && history.hasNextPage && (
              <div className="mt-3 text-center">
                <button onClick={() => void history.fetchNextPage()} disabled={history.isFetchingNextPage}
                        className="border border-border px-4 py-1.5 font-mono text-[10px] tracking-[0.12em] text-muted-foreground hover:text-foreground disabled:opacity-40">
                  {history.isFetchingNextPage ? "LOADING…" : "LOAD MORE"}
                </button>
              </div>
            )}
          </>
        )}

        {/* ── Feature 3: Execution Trace Timeline ── */}
        {view === "Traces" && (
          <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-[260px_minmax(0,1fr)]">
            {/* Trace list */}
            <div className="border border-border">
              <div className="border-b border-border bg-surface-2 px-3 py-2">
                <span className="label-xs">Execution traces</span>
              </div>
              {traces.map((t) => (
                <button
                  key={t.id}
                  onClick={() => setSelectedTrace(t.id)}
                  className={cn(
                    "block w-full border-b border-border px-3 py-2.5 text-left last:border-0 hover:bg-surface",
                    selectedTrace === t.id && "bg-surface-2",
                  )}
                >
                  <p className="text-[13px] font-medium leading-snug">{t.title}</p>
                  <div className="mt-0.5 flex items-center gap-2">
                    <span className="font-mono text-[10px] text-muted-foreground">{t.triggeredAt}</span>
                    {t.department && (
                      <span className="font-mono text-[10px] text-accent">{departmentName(t.department).toUpperCase()}</span>
                    )}
                  </div>
                </button>
              ))}
            </div>

            {/* Trace detail */}
            {activeTrace ? (
              <div className="border border-border">
                <div className="flex items-baseline justify-between border-b border-border bg-surface-2 px-3 py-2">
                  <span className="text-[13px] font-medium">{activeTrace.title}</span>
                  <span className="font-mono text-[10px] text-muted-foreground">
                    {activeTrace.steps.length} steps · triggered {activeTrace.triggeredAt}
                  </span>
                </div>
                <ul className="px-4 pt-4">
                  {activeTrace.steps.map((step) => (
                    <TraceStep key={step.id} step={step} />
                  ))}
                  {/* End cap */}
                  <li className="flex gap-3 pb-2">
                    <span className="grid size-6 shrink-0 place-items-center border border-border text-muted-foreground">
                      <span className="size-1.5 bg-muted-foreground" />
                    </span>
                    <span className="pt-0.5 font-mono text-[11px] text-muted-foreground">Trace end</span>
                  </li>
                </ul>
              </div>
            ) : (
              <div className="flex items-center justify-center border border-border py-16 font-mono text-[11px] text-muted-foreground">
                {traces.length === 0 ? "No live execution traces are available." : "Select a trace to view."}
              </div>
            )}
          </div>
        )}
      </div>
    </AppShell>
  );
}
