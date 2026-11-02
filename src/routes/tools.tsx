import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState, type ReactNode } from "react";
import { toast } from "sonner";
import { ChevronDown, Loader2, RefreshCw, RotateCcw, X } from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { AppShell } from "@/components/eaawp/AppShell";
import { PageHeader } from "@/components/eaawp/Panel";
import { useSession } from "@/state/session";
import { IS_ADMIN_ROLE } from "@/lib/workspace";
import { apiErrorMessage, USE_REAL_API } from "@/lib/api-client";
import { chartColor } from "@/lib/charts";
import { cn } from "@/lib/utils";
import {
  useGrantTool,
  useRefreshMcp,
  useRevokeTool,
  useRollbackTool,
  useSetToolActive,
  useToolAudit,
  useToolBuilder,
  useToolExecutions,
  useToolHealth,
  useToolRegistry,
  type AuditKind,
  type GeneratedTool,
  type GeneratedToolVersion,
  type RegistryTool,
  type ToolExecution,
  type ToolPolicy,
  type RiskClass,
} from "@/hooks/use-toolhub";

export const Route = createFileRoute("/tools")({
  component: ToolCenterPage,
});

const TABS = ["registry", "executions", "builder", "health", "audit"] as const;
type Tab = (typeof TABS)[number];

// ── Small shared pieces ──────────────────────────────────────────────────────

function when(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso.endsWith("Z") || /[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}

function pct(rate: number | null | undefined): string {
  return rate === null || rate === undefined ? "—" : `${Math.round(rate * 1000) / 10}%`;
}

function ms(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return v >= 1000 ? `${(v / 1000).toFixed(v >= 10_000 ? 0 : 1)} s` : `${Math.round(v)} ms`;
}

function words(s: string): string {
  return s.replace(/_/g, " ").toUpperCase();
}

type Tone = "neutral" | "ok" | "warn" | "bad" | "info";
const TONE: Record<Tone, string> = {
  neutral: "border-border text-muted-foreground",
  ok: "border-success/50 text-success",
  warn: "border-warning/60 text-warning",
  bad: "border-destructive/50 text-destructive",
  info: "border-primary/50 text-primary",
};

function Chip({
  tone = "neutral",
  children,
  title,
}: {
  tone?: Tone;
  children: ReactNode;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={cn(
        "inline-flex max-w-full items-center gap-1 break-all border px-1.5 py-0.5 font-mono text-[9px] tracking-[0.08em]",
        TONE[tone],
      )}
    >
      {children}
    </span>
  );
}

function statusTone(s: string): Tone {
  if (["active", "success", "connected", "validated"].includes(s)) return "ok";
  if (["failed", "rejected", "removed", "blocked", "error"].includes(s)) return "bad";
  if (["deactivated", "superseded", "rolled_back", "discovered"].includes(s)) return "warn";
  return "neutral";
}

const RISK_TONE: Record<RiskClass, Tone> = {
  read_only: "ok",
  internal_compute: "ok",
  internal_modify: "warn",
  external_comm: "warn",
  financial: "bad",
  security_sensitive: "bad",
};
const POLICY_TONE: Record<ToolPolicy, Tone> = {
  automatic: "ok",
  governed: "info",
  approval: "warn",
  explicit_approval: "warn",
  blocked: "bad",
};

function StateLine({ children, error }: { children: ReactNode; error?: boolean }) {
  return (
    <div
      role={error ? "alert" : undefined}
      className={cn(
        "border border-border px-3 py-6 text-center text-xs",
        error ? "text-destructive" : "text-muted-foreground",
      )}
    >
      {children}
    </div>
  );
}

function QueryState({
  isLoading,
  error,
  empty,
  emptyText,
  children,
}: {
  isLoading: boolean;
  error: unknown;
  empty: boolean;
  emptyText: string;
  children: ReactNode;
}) {
  if (isLoading)
    return (
      <StateLine>
        <Loader2 className="mx-auto mb-1 size-4 animate-spin" />
        Loading…
      </StateLine>
    );
  if (error) return <StateLine error>Could not load: {apiErrorMessage(error)}</StateLine>;
  if (empty) return <StateLine>{emptyText}</StateLine>;
  return <>{children}</>;
}

const SELECT = "h-8 max-w-full border border-input bg-surface px-2 text-xs";
const BTN =
  "inline-flex items-center gap-1 border border-border px-2 py-1 font-mono text-[10px] tracking-[0.12em] text-muted-foreground hover:text-foreground disabled:opacity-40";

function Section({
  title,
  hint,
  children,
  actions,
}: {
  title: string;
  hint?: ReactNode;
  children: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <section className="mt-4">
      <div className="mb-2 flex flex-wrap items-end justify-between gap-2">
        <div className="min-w-0">
          <h2 className="label-xs">{title}</h2>
          {hint && <p className="mt-0.5 text-[11px] text-muted-foreground">{hint}</p>}
        </div>
        {actions}
      </div>
      {children}
    </section>
  );
}

function Collapsible({ label, children }: { label: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-1.5">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex items-center gap-1 font-mono text-[10px] tracking-[0.1em] text-primary"
      >
        <ChevronDown className={cn("size-3 transition-transform", open && "rotate-180")} />{" "}
        {open ? "HIDE" : "SHOW"} {label}
      </button>
      {open && children}
    </div>
  );
}

function Pre({ children }: { children: string }) {
  return (
    <pre className="mt-1 max-h-72 overflow-auto whitespace-pre border border-border bg-surface-2 p-2 font-mono text-[11px] text-muted-foreground">
      {children}
    </pre>
  );
}

// ── Registry ─────────────────────────────────────────────────────────────────

function RegistryCard({ tool, roles }: { tool: RegistryTool; roles: Record<string, string> }) {
  const grant = useGrantTool();
  const revoke = useRevokeTool();
  const setActive = useSetToolActive();
  const [pick, setPick] = useState("");
  const generated = tool.source === "generated";
  const m = tool.metrics;
  const roleName = (k: string, i: number) => tool.role_names[i] ?? roles[k] ?? k;
  const grantable = Object.entries(roles).filter(([k]) => !tool.roles.includes(k));
  const busy = grant.isPending || revoke.isPending || setActive.isPending;

  function doGrant() {
    if (!pick) return;
    grant.mutate(
      { id: tool.id, role_key: pick },
      {
        onSuccess: () => {
          toast.success(`${tool.name} granted to ${roles[pick] ?? pick}.`);
          setPick("");
        },
        onError: (e) => toast.error(apiErrorMessage(e)),
      },
    );
  }
  function doRevoke(k: string, label: string) {
    if (!window.confirm(`Revoke ${tool.name} from ${label}?`)) return;
    revoke.mutate(
      { id: tool.id, role_key: k },
      {
        onSuccess: () => toast.success(`${tool.name} revoked from ${label}.`),
        onError: (e) => toast.error(apiErrorMessage(e)),
      },
    );
  }
  function doToggle(active: boolean) {
    const q = active
      ? `Activate ${tool.name}? Roles it is granted to can use it again.`
      : `Deactivate ${tool.name}? No AI employee can use it until it is activated again. Nothing is deleted.`;
    if (!window.confirm(q)) return;
    setActive.mutate(
      { id: tool.id, active },
      {
        onSuccess: () => toast.success(`${tool.name} ${active ? "activated" : "deactivated"}.`),
        onError: (e) => toast.error(apiErrorMessage(e)),
      },
    );
  }

  return (
    <li data-testid="registry-tool" className="min-w-0 border border-border bg-surface p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="break-words text-[13px] font-medium">{tool.name}</p>
          <p className="break-all font-mono text-[10px] text-muted-foreground">
            {tool.key} · v{tool.version} ·{" "}
            {generated ? "GENERATED" : `MCP${tool.server ? ` · ${tool.server.toUpperCase()}` : ""}`}
          </p>
        </div>
        <div className="flex flex-wrap gap-1">
          <Chip tone={statusTone(tool.status)}>{words(tool.status)}</Chip>
          {m.degraded && <Chip tone="bad">DEGRADED</Chip>}
        </div>
      </div>
      {tool.description && (
        <p className="mt-1.5 break-words text-[12px] text-muted-foreground">{tool.description}</p>
      )}

      <div className="mt-2 flex flex-wrap gap-1">
        <Chip tone={RISK_TONE[tool.risk_class] ?? "neutral"} title="Risk class">
          RISK · {words(tool.risk_class)}
        </Chip>
        <Chip tone={POLICY_TONE[tool.policy] ?? "neutral"} title="Execution policy">
          POLICY · {words(tool.policy)}
        </Chip>
        <Chip tone={statusTone(tool.validation)} title="Validation">
          VALIDATION · {words(tool.validation)}
        </Chip>
      </div>

      <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 font-mono text-[10px] sm:grid-cols-4">
        <div>
          <dt className="text-muted-foreground">SUCCESS</dt>
          <dd>{pct(m.success_rate)}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">AVG</dt>
          <dd>{ms(m.avg_ms)}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">RUNS</dt>
          <dd>{m.total ?? "—"}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">LAST FAILURE</dt>
          <dd className="break-words">{when(m.last_failure)}</dd>
        </div>
      </dl>

      <div className="mt-2 border-t border-border pt-2">
        <p className="label-xs">Roles</p>
        {tool.roles.length === 0 ? (
          <p className="mt-1 text-[11px] text-muted-foreground">Not granted to any role.</p>
        ) : (
          <ul className="mt-1 flex flex-wrap gap-1">
            {tool.roles.map((k, i) => (
              <li key={k}>
                <Chip tone="info">
                  {roleName(k, i)}
                  {generated && (
                    <button
                      type="button"
                      aria-label={`Revoke from ${roleName(k, i)}`}
                      disabled={busy}
                      onClick={() => doRevoke(k, roleName(k, i))}
                      className="ml-0.5 hover:text-destructive disabled:opacity-40"
                    >
                      <X className="size-2.5" />
                    </button>
                  )}
                </Chip>
              </li>
            ))}
          </ul>
        )}
        {generated ? (
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            {grantable.length > 0 && (
              <>
                <select
                  aria-label={`Role to grant ${tool.name}`}
                  value={pick}
                  onChange={(e) => setPick(e.target.value)}
                  className={SELECT}
                >
                  <option value="">Grant to role…</option>
                  {grantable.map(([k, label]) => (
                    <option key={k} value={k}>
                      {label}
                    </option>
                  ))}
                </select>
                <button type="button" onClick={doGrant} disabled={!pick || busy} className={BTN}>
                  GRANT
                </button>
              </>
            )}
            {tool.status === "active" && (
              <button
                type="button"
                onClick={() => doToggle(false)}
                disabled={busy}
                className={cn(BTN, "hover:text-destructive")}
              >
                DEACTIVATE
              </button>
            )}
            {tool.status === "deactivated" && (
              <button type="button" onClick={() => doToggle(true)} disabled={busy} className={BTN}>
                ACTIVATE
              </button>
            )}
          </div>
        ) : (
          <p className="mt-1.5 text-[11px] text-muted-foreground">
            MCP tools are granted in Integrations → MCP Server → Review tools.
          </p>
        )}
      </div>
    </li>
  );
}

function RegistryTab() {
  const q = useToolRegistry();
  const [search, setSearch] = useState("");
  const [source, setSource] = useState<"all" | "mcp" | "generated">("all");
  const [status, setStatus] = useState("all");
  const tools = useMemo(() => q.data?.tools ?? [], [q.data]);
  const statuses = useMemo(() => [...new Set(tools.map((t) => t.status))].sort(), [tools]);
  const filtered = useMemo(() => {
    const s = search.trim().toLowerCase();
    return tools.filter(
      (t) =>
        (source === "all" || t.source === source) &&
        (status === "all" || t.status === status) &&
        (!s ||
          [t.name, t.key, t.description, t.server ?? ""].some((v) => v.toLowerCase().includes(s))),
    );
  }, [tools, search, source, status]);

  return (
    <Section title={`Registry · ${filtered.length} of ${tools.length}`}>
      <div className="mb-3 flex flex-wrap items-center gap-1.5">
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search tools…"
          aria-label="Search tools"
          className="h-8 w-full border border-input bg-surface px-2 text-xs outline-none focus:border-ring sm:w-56"
        />
        <select
          aria-label="Source"
          value={source}
          onChange={(e) => setSource(e.target.value as typeof source)}
          className={SELECT}
        >
          <option value="all">All sources</option>
          <option value="mcp">MCP</option>
          <option value="generated">Generated</option>
        </select>
        <select
          aria-label="Status"
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          className={SELECT}
        >
          <option value="all">All statuses</option>
          {statuses.map((s) => (
            <option key={s} value={s}>
              {s.replace(/_/g, " ")}
            </option>
          ))}
        </select>
      </div>
      <QueryState
        isLoading={q.isLoading}
        error={q.error}
        empty={filtered.length === 0}
        emptyText={
          tools.length === 0 ? "No tools are registered yet." : "No tools match these filters."
        }
      >
        <ul className="grid grid-cols-1 gap-2 xl:grid-cols-2">
          {filtered.map((t) => (
            <RegistryCard key={t.id} tool={t} roles={q.data?.roles ?? {}} />
          ))}
        </ul>
      </QueryState>
    </Section>
  );
}

// ── Executions ───────────────────────────────────────────────────────────────

function ExecutionRow({ e }: { e: ToolExecution }) {
  const [open, setOpen] = useState(false);
  return (
    <li className="border-b border-border last:border-0">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-left hover:bg-surface"
      >
        <ChevronDown
          className={cn(
            "size-3 shrink-0 text-muted-foreground transition-transform",
            open && "rotate-180",
          )}
        />
        <span className="min-w-0 flex-1 break-words text-[12px]">
          {e.tool_label || e.tool_key}
          <span className="ml-1.5 font-mono text-[9px] text-muted-foreground">
            {e.source.toUpperCase()}
          </span>
        </span>
        <Chip tone={statusTone(e.status)}>{words(e.status)}</Chip>
        <span className="font-mono text-[10px] text-muted-foreground">{ms(e.duration_ms)}</span>
        <span className="w-full font-mono text-[10px] text-muted-foreground sm:w-auto">
          {when(e.started_at)} · {e.role}
        </span>
      </button>
      {open && (
        <div className="space-y-1.5 px-3 pb-3 pl-8 text-[12px]">
          <p className="break-all font-mono text-[10px] text-muted-foreground">
            KEY · {e.tool_key}
            {e.plan_id ? ` · PLAN ${e.plan_id}` : ""}
          </p>
          <div>
            <span className="label-xs">Input</span>
            <p className="mt-0.5 whitespace-pre-wrap break-words">{e.input || "—"}</p>
          </div>
          <div>
            <span className="label-xs">Output</span>
            <p className="mt-0.5 whitespace-pre-wrap break-words">{e.output || "—"}</p>
          </div>
          {(e.error_category || e.error) && (
            <div>
              <span className="label-xs">Error</span>
              <p className="mt-0.5 break-words text-destructive">
                {e.error_category && <Chip tone="bad">{words(e.error_category)}</Chip>} {e.error}
              </p>
            </div>
          )}
          <p className="font-mono text-[10px] text-muted-foreground">
            RETRIES · {e.retries} · DURATION · {ms(e.duration_ms)}
          </p>
          {e.recovery && (
            <div>
              <span className="label-xs">Recovery</span>
              <p className="mt-0.5 break-words">{e.recovery}</p>
            </div>
          )}
        </div>
      )}
    </li>
  );
}

function ExecutionsTab() {
  const [status, setStatus] = useState("");
  const [tool, setTool] = useState("");
  const q = useToolExecutions({ status, tool });
  const registry = useToolRegistry();
  const rows = useMemo(() => q.data?.executions ?? [], [q.data]);
  const toolOptions = useMemo(() => {
    const map = new Map<string, string>();
    for (const t of registry.data?.tools ?? []) map.set(t.key, t.name);
    for (const e of rows) if (!map.has(e.tool_key)) map.set(e.tool_key, e.tool_label || e.tool_key);
    return [...map.entries()].sort((a, b) => a[1].localeCompare(b[1]));
  }, [registry.data, rows]);

  return (
    <Section
      title={`Executions${q.data ? ` · ${rows.length}` : ""}`}
      hint="The latest 100 tool calls, newest first."
    >
      <div className="mb-3 flex flex-wrap items-center gap-1.5">
        <select
          aria-label="Execution status"
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          className={SELECT}
        >
          <option value="">All statuses</option>
          <option value="success">Success</option>
          <option value="failed">Failed</option>
          <option value="blocked">Blocked</option>
        </select>
        <select
          aria-label="Tool"
          value={tool}
          onChange={(e) => setTool(e.target.value)}
          className={cn(SELECT, "w-full sm:w-64")}
        >
          <option value="">All tools</option>
          {toolOptions.map(([k, label]) => (
            <option key={k} value={k}>
              {label}
            </option>
          ))}
        </select>
        {(status || tool) && (
          <button
            type="button"
            onClick={() => {
              setStatus("");
              setTool("");
            }}
            className="font-mono text-[10px] tracking-[0.12em] text-muted-foreground hover:text-foreground"
          >
            CLEAR FILTERS
          </button>
        )}
      </div>
      <QueryState
        isLoading={q.isLoading}
        error={q.error}
        empty={rows.length === 0}
        emptyText={
          status || tool ? "No executions match these filters." : "No tool has been executed yet."
        }
      >
        <ul className="border border-border">
          {rows.map((e) => (
            <ExecutionRow key={e.id} e={e} />
          ))}
        </ul>
      </QueryState>
    </Section>
  );
}

// ── Builder ──────────────────────────────────────────────────────────────────

function VersionBlock({ tool, v }: { tool: GeneratedTool; v: GeneratedToolVersion }) {
  const rollback = useRollbackTool();
  const current = v.version === tool.current_version;
  const validated = v.attempts.some((a) => a.passed);
  const canRollback =
    !current && (v.status === "superseded" || v.status === "rolled_back") && validated;
  function doRollback() {
    if (
      !window.confirm(
        `Roll ${tool.name} back to version ${v.version}? The current version ${tool.current_version} stops being used.`,
      )
    )
      return;
    rollback.mutate(
      { id: tool.id, version: v.version },
      {
        onSuccess: () => toast.success(`${tool.name} rolled back to version ${v.version}.`),
        onError: (e) => toast.error(apiErrorMessage(e)),
      },
    );
  }
  return (
    <li className="border-t border-border py-2 first:border-t-0">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="font-mono text-[11px]">v{v.version}</span>
        <Chip tone={statusTone(v.status)}>{words(v.status)}</Chip>
        {current && <Chip tone="info">CURRENT</Chip>}
        <span className="font-mono text-[10px] text-muted-foreground">
          {when(v.created_at)} · {v.created_by}
        </span>
        {canRollback && (
          <button
            type="button"
            onClick={doRollback}
            disabled={rollback.isPending}
            className={cn(BTN, "ml-auto")}
          >
            <RotateCcw className="size-3" />{" "}
            {rollback.isPending ? "ROLLING BACK…" : "ROLL BACK TO THIS"}
          </button>
        )}
      </div>
      {v.purpose && <p className="mt-1 break-words text-[12px]">{v.purpose}</p>}
      {v.dependencies.length > 0 && (
        <p className="mt-1 break-words font-mono text-[10px] text-muted-foreground">
          DEPENDENCIES · {v.dependencies.join(", ")}
        </p>
      )}
      <Collapsible label="INPUT SCHEMA">
        <Pre>{JSON.stringify(v.input_schema, null, 2)}</Pre>
      </Collapsible>
      <Collapsible label="OUTPUT SCHEMA">
        <Pre>{JSON.stringify(v.output_schema, null, 2)}</Pre>
      </Collapsible>
      <Collapsible label="CODE">
        <Pre>{v.code || "(empty)"}</Pre>
      </Collapsible>
      <div className="mt-2">
        <p className="label-xs">Validation attempts · {v.attempts.length}</p>
        {v.attempts.length === 0 ? (
          <p className="mt-1 text-[11px] text-muted-foreground">No validation was recorded.</p>
        ) : (
          <ol className="mt-1 space-y-1.5">
            {v.attempts.map((a) => (
              <li key={a.attempt} className="border border-border p-2">
                <div className="flex items-center gap-1.5">
                  <span className="font-mono text-[10px]">ATTEMPT {a.attempt}</span>
                  <Chip tone={a.passed ? "ok" : "bad"}>{a.passed ? "PASSED" : "FAILED"}</Chip>
                </div>
                <ul className="mt-1 space-y-0.5">
                  {a.report.map((c, i) => (
                    <li
                      key={`${c.check}-${i}`}
                      className="flex flex-wrap items-baseline gap-x-2 text-[11px]"
                    >
                      <span
                        className={cn(
                          "font-mono text-[10px]",
                          c.passed ? "text-success" : "text-destructive",
                        )}
                      >
                        {c.passed ? "✓" : "✗"} {c.check.toUpperCase()}
                      </span>
                      {c.detail && (
                        <span className="min-w-0 break-words text-muted-foreground">
                          {c.detail}
                        </span>
                      )}
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ol>
        )}
      </div>
    </li>
  );
}

function BuilderTab() {
  const q = useToolBuilder();
  const requests = q.data?.requests ?? [];
  const tools = q.data?.tools ?? [];
  return (
    <>
      <Section
        title={`Missing-capability requests${q.data ? ` · ${requests.length}` : ""}`}
        hint="When an AI employee needed something no tool covered, and whether an existing tool was reused or a new one built."
      >
        <QueryState
          isLoading={q.isLoading}
          error={q.error}
          empty={requests.length === 0}
          emptyText="No missing-capability requests yet."
        >
          <ul className="border border-border">
            {requests.map((r, i) => (
              <li key={`${r.at}-${i}`} className="border-b border-border px-3 py-2 last:border-0">
                <div className="flex flex-wrap items-center gap-1.5">
                  <Chip tone={r.decision === "build" ? "warn" : "info"}>
                    {r.decision.toUpperCase()}
                  </Chip>
                  <span className="font-mono text-[10px] text-muted-foreground">
                    {when(r.at)} · {r.role} · {r.actor}
                  </span>
                </div>
                <p className="mt-1 break-words text-[12px]">{r.need}</p>
                {r.candidates.length > 0 && (
                  <p className="mt-0.5 break-all font-mono text-[10px] text-muted-foreground">
                    CANDIDATES · {r.candidates.join(", ")}
                  </p>
                )}
              </li>
            ))}
          </ul>
        </QueryState>
      </Section>
      <Section title={`Generated tools${q.data ? ` · ${tools.length}` : ""}`}>
        <QueryState
          isLoading={q.isLoading}
          error={q.error}
          empty={tools.length === 0}
          emptyText="No tool has been generated yet."
        >
          <ul className="space-y-2">
            {tools.map((t) => (
              <li key={t.id} className="border border-border bg-surface p-3">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="break-words text-[13px] font-medium">{t.name}</p>
                    <p className="break-all font-mono text-[10px] text-muted-foreground">
                      {t.key} · CURRENT v{t.current_version} · {t.created_by} · {when(t.created_at)}
                    </p>
                  </div>
                  <Chip tone={statusTone(t.status)}>{words(t.status)}</Chip>
                </div>
                {t.description && (
                  <p className="mt-1 break-words text-[12px] text-muted-foreground">
                    {t.description}
                  </p>
                )}
                <ul className="mt-2">
                  {[...t.versions]
                    .sort((a, b) => b.version - a.version)
                    .map((v) => (
                      <VersionBlock key={v.version} tool={t} v={v} />
                    ))}
                </ul>
              </li>
            ))}
          </ul>
        </QueryState>
      </Section>
    </>
  );
}

// ── Health ───────────────────────────────────────────────────────────────────

const SLOW_MS = 10_000;

function HealthTab() {
  const q = useToolHealth();
  const refresh = useRefreshMcp();
  const [refreshing, setRefreshing] = useState<string | null>(null);
  const servers = q.data?.servers ?? [];
  const tools = useMemo(
    () =>
      [...(q.data?.tools ?? [])].sort(
        (a, b) => Number(b.degraded) - Number(a.degraded) || a.success_rate - b.success_rate,
      ),
    [q.data],
  );
  const flagged = tools.filter((t) => t.degraded || t.avg_ms >= SLOW_MS);
  const trend = q.data?.trend ?? [];
  const recoveries = q.data?.recoveries ?? [];

  function doRefresh(id: string, name: string) {
    setRefreshing(id);
    refresh.mutate(id, {
      onSuccess: (r) => toast.success(`${name}: ${r.tool_count} tools discovered.`),
      onError: (e) => toast.error(apiErrorMessage(e)),
      onSettled: () => setRefreshing(null),
    });
  }

  if (q.isLoading || q.error) {
    return (
      <div className="mt-4">
        <QueryState isLoading={q.isLoading} error={q.error} empty={false} emptyText="">
          {null}
        </QueryState>
      </div>
    );
  }

  return (
    <>
      <Section title={`MCP servers · ${servers.length}`}>
        {servers.length === 0 ? (
          <StateLine>No MCP server is connected.</StateLine>
        ) : (
          <ul className="grid grid-cols-1 gap-2 lg:grid-cols-2">
            {servers.map((s) => {
              const d = s.last_discovery;
              return (
                <li key={s.integration_id} className="min-w-0 border border-border bg-surface p-3">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="break-words text-[13px] font-medium">{s.name}</p>
                      <p className="font-mono text-[10px] text-muted-foreground">
                        CHECKED · {when(s.last_checked)}
                      </p>
                    </div>
                    <div className="flex flex-wrap gap-1">
                      <Chip tone={statusTone(s.status)}>{words(s.status)}</Chip>
                      {!s.enabled && <Chip>DISABLED</Chip>}
                    </div>
                  </div>
                  <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 font-mono text-[10px] sm:grid-cols-4">
                    <div>
                      <dt className="text-muted-foreground">LAST DISCOVERY</dt>
                      <dd className="break-words">{when(d?.at)}</dd>
                    </div>
                    <div>
                      <dt className="text-muted-foreground">TOOLS</dt>
                      <dd>{d ? d.tool_count : "—"}</dd>
                    </div>
                    <div>
                      <dt className="text-muted-foreground">DISCOVERIES</dt>
                      <dd>
                        {s.discoveries} ({s.failed_discoveries} failed)
                      </dd>
                    </div>
                    <div>
                      <dt className="text-muted-foreground">DURATION</dt>
                      <dd>{d ? ms(d.duration_ms) : "—"}</dd>
                    </div>
                  </dl>
                  {d && (d.added.length > 0 || d.removed.length > 0 || d.changed.length > 0) && (
                    <div className="mt-2 space-y-0.5 break-all font-mono text-[10px]">
                      {d.added.length > 0 && (
                        <p className="text-success">+ ADDED · {d.added.join(", ")}</p>
                      )}
                      {d.removed.length > 0 && (
                        <p className="text-destructive">− REMOVED · {d.removed.join(", ")}</p>
                      )}
                      {d.changed.length > 0 && (
                        <p className="text-warning">~ CHANGED · {d.changed.join(", ")}</p>
                      )}
                    </div>
                  )}
                  {(s.error || d?.error) && (
                    <p className="mt-2 break-words text-[11px] text-destructive">
                      {s.error ?? d?.error}
                    </p>
                  )}
                  <button
                    type="button"
                    onClick={() => doRefresh(s.integration_id, s.name)}
                    disabled={refreshing !== null}
                    className={cn(BTN, "mt-2")}
                  >
                    <RefreshCw
                      className={cn("size-3", refreshing === s.integration_id && "animate-spin")}
                    />
                    {refreshing === s.integration_id ? "REFRESHING…" : "REFRESH TOOLS"}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </Section>

      <Section title="Success and failure · last 14 days">
        {trend.length === 0 ? (
          <StateLine>No executions in the last 14 days.</StateLine>
        ) : (
          <div className="border border-border p-3">
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={trend} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
                <XAxis
                  dataKey="day"
                  tick={{ fill: "var(--muted-foreground)", fontSize: 10 }}
                  stroke="var(--border)"
                  tickFormatter={(d: string) => d.slice(5)}
                  interval="preserveStartEnd"
                  minTickGap={8}
                />
                <YAxis
                  allowDecimals={false}
                  tick={{ fill: "var(--muted-foreground)", fontSize: 10 }}
                  stroke="var(--border)"
                  width={40}
                  label={{
                    value: "Executions",
                    angle: -90,
                    position: "insideLeft",
                    style: { fill: "var(--muted-foreground)", fontSize: 10, textAnchor: "middle" },
                  }}
                />
                <Tooltip
                  contentStyle={{
                    background: "var(--surface)",
                    border: "1px solid var(--border)",
                    borderRadius: 2,
                    fontSize: 11,
                    color: "var(--foreground)",
                  }}
                  cursor={{ fill: "var(--muted)", fillOpacity: 0.3 }}
                />
                <Legend wrapperStyle={{ fontSize: 11 }} iconSize={9} />
                <Bar
                  dataKey="success"
                  name="Success"
                  stackId="runs"
                  fill={chartColor(2)}
                  isAnimationActive={false}
                />
                <Bar
                  dataKey="failed"
                  name="Failed"
                  stackId="runs"
                  fill={chartColor(3)}
                  isAnimationActive={false}
                />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </Section>

      <Section
        title={`Degraded or slow tools · ${flagged.length}`}
        hint={`Degraded as reported by the server; slow means an average of ${SLOW_MS / 1000} s or more.`}
      >
        {flagged.length === 0 ? (
          <StateLine>No tool is degraded or slow.</StateLine>
        ) : (
          <div className="overflow-x-auto border border-border">
            <table className="w-full min-w-[560px] border-collapse text-[12px]">
              <thead>
                <tr className="bg-surface-2">
                  {["Tool", "Success", "Runs", "Avg", "Timeouts", "Retries", "Last error"].map(
                    (h) => (
                      <th key={h} className="label-xs border-b border-border px-2 py-1.5 text-left">
                        {h}
                      </th>
                    ),
                  )}
                </tr>
              </thead>
              <tbody>
                {flagged.map((t) => (
                  <tr key={t.tool_key} className="border-b border-border align-top last:border-0">
                    <td className="px-2 py-1.5">
                      <div className="break-words">{t.label}</div>
                      <div className="mt-0.5 flex flex-wrap gap-1">
                        {t.degraded && <Chip tone="bad">DEGRADED</Chip>}
                        {t.avg_ms >= SLOW_MS && <Chip tone="warn">SLOW</Chip>}
                      </div>
                    </td>
                    <td className="px-2 py-1.5 font-mono text-[11px]">{pct(t.success_rate)}</td>
                    <td className="px-2 py-1.5 font-mono text-[11px]">
                      {t.success}/{t.total}
                    </td>
                    <td className="px-2 py-1.5 font-mono text-[11px]">{ms(t.avg_ms)}</td>
                    <td className="px-2 py-1.5 font-mono text-[11px]">{t.timeouts}</td>
                    <td className="px-2 py-1.5 font-mono text-[11px]">{t.retries}</td>
                    <td className="max-w-[260px] px-2 py-1.5 text-[11px] text-muted-foreground">
                      <div className="break-words">{t.last_error ?? "—"}</div>
                      {Object.keys(t.errors).length > 0 && (
                        <div className="mt-0.5 font-mono text-[10px]">
                          {Object.entries(t.errors)
                            .map(([k, n]) => `${k} ${n}`)
                            .join(" · ")}
                        </div>
                      )}
                      {t.last_failure && (
                        <div className="mt-0.5 font-mono text-[10px]">{when(t.last_failure)}</div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      <Section title={`Recent recovery attempts · ${recoveries.length}`}>
        {recoveries.length === 0 ? (
          <StateLine>No recovery attempts recorded.</StateLine>
        ) : (
          <ul className="border border-border">
            {recoveries.map((r, i) => (
              <li
                key={`${r.tool_key}-${r.at}-${i}`}
                className="border-b border-border px-3 py-2 last:border-0"
              >
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="break-all text-[12px]">{r.tool_key}</span>
                  <Chip tone={statusTone(r.status)}>{words(r.status)}</Chip>
                  {r.error_category && <Chip tone="warn">{words(r.error_category)}</Chip>}
                  <span className="font-mono text-[10px] text-muted-foreground">
                    {when(r.at)} · {r.retries} {r.retries === 1 ? "retry" : "retries"}
                  </span>
                </div>
                {r.recovery && (
                  <p className="mt-0.5 break-words text-[11px] text-muted-foreground">
                    {r.recovery}
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}
      </Section>
    </>
  );
}

// ── Audit ────────────────────────────────────────────────────────────────────

const AUDIT_KINDS: AuditKind[] = [
  "discovered",
  "schema_changed",
  "removed",
  "generated",
  "validated",
  "rejected",
  "registered",
  "granted",
  "revoked",
  "deactivated",
  "activated",
  "rolled_back",
  "capability_request",
];

function AuditTab() {
  const q = useToolAudit();
  const [kind, setKind] = useState("");
  const events = q.data?.events ?? [];
  const filtered = kind ? events.filter((e) => e.kind === kind) : events;
  return (
    <Section
      title={`Tool audit${q.data ? ` · ${filtered.length}` : ""}`}
      hint="The latest 200 tool lifecycle events."
    >
      <div className="mb-3">
        <select
          aria-label="Event kind"
          value={kind}
          onChange={(e) => setKind(e.target.value)}
          className={SELECT}
        >
          <option value="">All kinds</option>
          {AUDIT_KINDS.map((k) => (
            <option key={k} value={k}>
              {k.replace(/_/g, " ")}
            </option>
          ))}
        </select>
      </div>
      <QueryState
        isLoading={q.isLoading}
        error={q.error}
        empty={filtered.length === 0}
        emptyText={kind ? "No events of this kind." : "No tool events recorded yet."}
      >
        <ul className="border border-border">
          {filtered.map((e) => (
            <li key={e.id} className="border-b border-border px-3 py-2 last:border-0">
              <div className="flex flex-wrap items-center gap-1.5">
                <Chip tone={statusTone(e.kind)}>{words(e.kind)}</Chip>
                <span className="font-mono text-[10px] text-muted-foreground">
                  {when(e.at)} · {e.actor}
                </span>
              </div>
              <p className="mt-0.5 break-words text-[12px]">{e.detail}</p>
            </li>
          ))}
        </ul>
      </QueryState>
    </Section>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────────

function ToolCenterPage() {
  const { user } = useSession();
  const isAdmin = IS_ADMIN_ROLE(user?.role);
  const [tab, setTab] = useState<Tab>("registry");

  return (
    <AppShell>
      <div className="min-w-0 p-4">
        <PageHeader
          title="Tool Center"
          subtitle="Every tool the AI employees can use: registry, executions, generated tools, health and audit."
        />
        {!isAdmin ? (
          <p
            data-testid="tools-admin-only"
            className="mt-4 border border-border px-3 py-6 text-center text-xs text-muted-foreground"
          >
            Only administrators can open the Tool Center.
          </p>
        ) : !USE_REAL_API ? (
          <p className="mt-4 border border-border px-3 py-6 text-center text-xs text-muted-foreground">
            The Tool Center shows live data only. Connect the app to the backend to use it.
          </p>
        ) : (
          <>
            <div
              role="tablist"
              aria-label="Tool Center sections"
              className="mt-3 flex flex-wrap gap-1.5"
            >
              {TABS.map((t) => (
                <button
                  key={t}
                  type="button"
                  role="tab"
                  aria-selected={tab === t}
                  onClick={() => setTab(t)}
                  className={cn(
                    "border px-3 py-1.5 font-mono text-[10px] tracking-[0.14em]",
                    tab === t
                      ? "border-foreground text-foreground"
                      : "border-border text-muted-foreground hover:text-foreground",
                  )}
                >
                  {t.toUpperCase()}
                </button>
              ))}
            </div>
            <div role="tabpanel">
              {tab === "registry" && <RegistryTab />}
              {tab === "executions" && <ExecutionsTab />}
              {tab === "builder" && <BuilderTab />}
              {tab === "health" && <HealthTab />}
              {tab === "audit" && <AuditTab />}
            </div>
          </>
        )}
      </div>
    </AppShell>
  );
}
