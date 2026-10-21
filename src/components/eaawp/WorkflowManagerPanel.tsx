/**
 * WorkflowManagerPanel — Workflow CRUD and Execution
 *
 * Shows all workflows for the tenant. Lets administrators:
 * - Create new workflows (name, trigger, schedule, steps)
 * - Enable / disable
 * - Manually trigger
 * - View last execution status
 *
 * Scheduled workflows (trigger="scheduled") run automatically via
 * the backend scheduler at the configured cron time.
 *
 * HIGH-risk steps (send_email, publish) still require approval — the
 * workflow scheduler enforces this through the existing planner pipeline.
 */
import { useState } from "react";
import { toast } from "sonner";
import {
  Plus, Loader2, Play, Pause, Trash2, Clock,
  CheckCircle, XCircle, AlertTriangle, ChevronDown, ChevronRight,
  Calendar, Zap, RefreshCw,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  useWorkflows,
  useCreateWorkflow,
  useUpdateWorkflow,
  useDeleteWorkflow,
  useTriggerWorkflow,
  useWorkflowRuns,
  useCancelWorkflowRun,
  type WorkflowOut,
  type WorkflowCreate,
  type WorkflowStep,
} from "@/hooks/use-api";

// ── Status badge ──────────────────────────────────────────────────────────────
function StatusBadge({ status }: { status: string }) {
  const cfgMap: Record<string, { cls: string; label: string }> = {
    idle:      { cls: "text-muted-foreground border-muted-foreground/40", label: "IDLE" },
    running:   { cls: "text-warning border-warning/40",                   label: "RUNNING" },
    awaiting_approval: { cls: "text-warning border-warning/40",           label: "NEEDS APPROVAL" },
    completed: { cls: "text-success border-success/40",                   label: "COMPLETED" },
    failed:    { cls: "text-destructive border-destructive/40",           label: "FAILED" },
    rejected:  { cls: "text-destructive border-destructive/40",           label: "REJECTED" },
    queued:    { cls: "text-muted-foreground border-muted-foreground/40", label: "QUEUED" },
    waiting_setup: { cls: "text-warning border-warning/40",               label: "NEEDS SETUP" },
    skipped:   { cls: "text-muted-foreground border-muted-foreground/40", label: "SKIPPED" },
    cancelled: { cls: "text-muted-foreground border-muted-foreground/40", label: "CANCELLED" },
  };
  const cfg = cfgMap[status] ?? cfgMap["idle"]!;
  const { cls, label } = cfg;
  return (
    <span className={cn("border px-1.5 py-0.5 font-mono text-[9px] tracking-[0.06em]", cls)}>
      {label}
    </span>
  );
}

// ── Run history (real outcomes of each attempt) ────────────────────────────
function RunHistory({ workflowId }: { workflowId: string }) {
  const { data, isLoading, error } = useWorkflowRuns(workflowId, true);
  const cancel = useCancelWorkflowRun(workflowId);
  if (isLoading) return <p className="text-[10px] text-muted-foreground">Loading history…</p>;
  if (error) return <p className="text-[10px] text-destructive">Could not load run history (it is visible to company administrators only).</p>;
  if (!data || data.length === 0) {
    return <p className="text-[10px] text-muted-foreground">No runs yet.</p>;
  }
  return (
    <div className="border-t border-border/40 pt-2 space-y-1">
      <p className="font-mono text-[9px] tracking-[0.1em] text-muted-foreground">RUN HISTORY</p>
      {data.slice(0, 10).map((r) => (
        <div key={r.id} className="flex items-start gap-2 text-[11px]">
          <span className="font-mono text-[9px] text-muted-foreground shrink-0 w-28">
            {new Date(r.created_at).toLocaleString()}
          </span>
          <StatusBadge status={r.status} />
          <span className="font-mono text-[9px] text-muted-foreground shrink-0">
            {r.trigger}{r.attempt > 1 ? ` · attempt ${r.attempt}` : ""}
          </span>
          <span className="min-w-0 flex-1 truncate text-muted-foreground" title={r.detail}>{r.detail}</span>
          {["queued", "waiting_setup", "awaiting_approval"].includes(r.status) && (
            <button
              disabled={cancel.isPending}
              onClick={() => cancel.mutate(r.id, {
                onError: (e) => toast.error(e instanceof Error ? e.message : "Could not cancel the run."),
              })}
              className="shrink-0 border border-border px-1.5 font-mono text-[9px] text-muted-foreground hover:text-foreground disabled:opacity-50"
            >
              CANCEL
            </button>
          )}
        </div>
      ))}
    </div>
  );
}

// ── Workflow card ─────────────────────────────────────────────────────────────
function WorkflowCard({
  wf,
  onToggle,
  onTrigger,
  onDelete,
  triggering,
}: {
  wf: WorkflowOut;
  onToggle: (id: string, enabled: boolean) => void;
  onTrigger: (id: string) => void;
  onDelete: (id: string) => void;
  triggering: boolean;
}) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="border border-border bg-surface p-3 space-y-2">
      <div className="flex items-start gap-2.5">
        {wf.trigger === "scheduled" ? (
          <Calendar className="size-3.5 text-muted-foreground shrink-0 mt-0.5" />
        ) : (
          <Zap className="size-3.5 text-muted-foreground shrink-0 mt-0.5" />
        )}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-mono text-[11px] tracking-[0.06em]">{wf.name}</span>
            <StatusBadge status={wf.status} />
            {!wf.is_enabled && (
              <span className="border border-muted-foreground/30 px-1 py-0.5 font-mono text-[9px] text-muted-foreground/60">
                DISABLED
              </span>
            )}
          </div>
          {wf.description && (
            <p className="text-[11px] text-muted-foreground mt-0.5">{wf.description}</p>
          )}
          <div className="flex gap-3 mt-0.5 text-[10px] text-muted-foreground font-mono">
            <span>{wf.trigger.toUpperCase()}</span>
            {wf.schedule_cron && <span>{wf.schedule_cron}</span>}
            <span>{wf.steps.length} steps</span>
            {wf.trigger === "scheduled" && <span>{wf.timezone ?? "UTC"}</span>}
            {(wf.max_retries ?? 0) > 0 && <span>retries: {wf.max_retries}</span>}
          </div>
        </div>
        <button
          onClick={() => setExpanded((e) => !e)}
          className="shrink-0 text-muted-foreground hover:text-foreground"
        >
          {expanded ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
        </button>
      </div>

      {/* Last run info */}
      {wf.last_run_at && (
        <div className="text-[10px] text-muted-foreground font-mono flex gap-2">
          <span>Last run: {new Date(wf.last_run_at).toLocaleString()}</span>
          {wf.last_run_status && <span>· {wf.last_run_status}</span>}
        </div>
      )}

      {/* Step list */}
      {expanded && wf.steps.length > 0 && (
        <div className="border-t border-border/40 pt-2 space-y-1">
          <p className="font-mono text-[9px] tracking-[0.1em] text-muted-foreground">STEPS</p>
          {wf.steps.map((s, i) => (
            <div key={i} className="flex items-start gap-2 text-[11px]">
              <span className="font-mono text-muted-foreground/60 shrink-0 w-4">{i + 1}.</span>
              <div>
                <span className="font-mono text-[9px] border border-border/50 px-1 mr-1.5">
                  {s.step_type.toUpperCase()}
                </span>
                {s.description}
                {s.requires_approval && (
                  <span className="ml-1.5 text-warning text-[9px] font-mono">APPROVAL REQUIRED</span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {expanded && <RunHistory workflowId={wf.id} />}

      {/* Actions */}
      <div className="flex gap-1.5 flex-wrap pt-1">
        {wf.is_enabled && (
          <button
            onClick={() => onTrigger(wf.id)}
            disabled={triggering || wf.status === "running"}
            className="inline-flex items-center gap-1 border border-foreground/20 px-2 py-0.5 font-mono text-[10px] tracking-[0.08em] hover:bg-foreground/5 disabled:opacity-50"
          >
            {triggering ? <Loader2 className="size-2.5 animate-spin" /> : <Play className="size-2.5" />}
            RUN NOW
          </button>
        )}
        <button
          onClick={() => onToggle(wf.id, !wf.is_enabled)}
          className="inline-flex items-center gap-1 border border-border px-2 py-0.5 font-mono text-[10px] tracking-[0.08em] text-muted-foreground hover:text-foreground"
        >
          {wf.is_enabled ? <Pause className="size-2.5" /> : <Play className="size-2.5" />}
          {wf.is_enabled ? "DISABLE" : "ENABLE"}
        </button>
        <button
          onClick={() => onDelete(wf.id)}
          className="inline-flex items-center gap-1 border border-destructive/30 px-2 py-0.5 font-mono text-[10px] tracking-[0.08em] text-destructive hover:bg-destructive/10"
        >
          <Trash2 className="size-2.5" /> DELETE
        </button>
      </div>
    </div>
  );
}

// ── Create form ───────────────────────────────────────────────────────────────
function CreateWorkflowForm({ onDone }: { onDone: () => void }) {
  const createMutation = useCreateWorkflow();
  const [form, setForm] = useState<WorkflowCreate>({
    name: "",
    description: "",
    trigger: "manual",
    schedule_cron: null,
    steps: [],
  });

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.name.trim()) { toast.error("Name is required."); return; }
    createMutation.mutate(form, {
      onSuccess: () => { toast.success("Workflow created."); onDone(); },
      onError: (e) => toast.error(e.message),
    });
  }

  const field = "h-8 w-full border border-input bg-background px-2 text-[12px] outline-none focus:border-ring";

  return (
    <form onSubmit={(e) => { e.preventDefault(); void handleSubmit(e); }} className="border border-border bg-surface p-3 space-y-3">
      <p className="font-mono text-[10px] tracking-[0.14em] text-muted-foreground">NEW WORKFLOW</p>
      <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
        <div>
          <label className="label-xs">Name</label>
          <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })}
            placeholder="e.g. Weekly Performance Report" className={cn(field, "mt-1")} />
        </div>
        <div>
          <label className="label-xs">Trigger</label>
          <select value={form.trigger} onChange={(e) => setForm({ ...form, trigger: e.target.value as "manual" | "scheduled" })}
            className={cn(field, "mt-1 appearance-none")}>
            <option value="manual">Manual</option>
            <option value="scheduled">Scheduled (cron)</option>
          </select>
        </div>
        {form.trigger === "scheduled" && (
          <div className="md:col-span-2">
            <label className="label-xs">Cron Schedule</label>
            <input value={form.schedule_cron ?? ""} onChange={(e) => setForm({ ...form, schedule_cron: e.target.value || null })}
              placeholder="0 9 * * 1  (every Monday at 9am)" className={cn(field, "mt-1 font-mono")} />
            <p className="mt-0.5 text-[10px] text-muted-foreground">Format: minute hour day month weekday</p>
          </div>
        )}
        <div className="md:col-span-2">
          <label className="label-xs">Description (optional)</label>
          <input value={form.description ?? ""} onChange={(e) => setForm({ ...form, description: e.target.value })}
            placeholder="What this workflow does" className={cn(field, "mt-1")} />
        </div>
      </div>
      <div className="flex gap-2">
        <button type="submit" disabled={createMutation.isPending}
          className="inline-flex items-center gap-1.5 border border-foreground/20 bg-foreground/5 px-3 py-1 font-mono text-[11px] tracking-[0.08em] hover:bg-foreground/10 disabled:opacity-50">
          {createMutation.isPending ? <Loader2 className="size-3 animate-spin" /> : <Plus className="size-3" />}
          CREATE
        </button>
        <button type="button" onClick={onDone} className="border border-border px-3 py-1 font-mono text-[11px] text-muted-foreground hover:text-foreground">
          CANCEL
        </button>
      </div>
    </form>
  );
}

// ── Main panel ────────────────────────────────────────────────────────────────
export function WorkflowManagerPanel() {
  const [showCreate, setShowCreate] = useState(false);
  const [triggeringId, setTriggeringId] = useState<string | null>(null);
  const [togglingId, setTogglingId] = useState<string | null>(null);

  const { data: workflows = [], isLoading, refetch } = useWorkflows();
  const updateMutation = useUpdateWorkflow(togglingId ?? "");
  const deleteMutation = useDeleteWorkflow();
  const triggerMutation = useTriggerWorkflow();

  function handleToggle(id: string, enabled: boolean) {
    setTogglingId(id);
    updateMutation.mutate({ is_enabled: enabled }, {
      onSuccess: () => {
        toast.success(enabled ? "Workflow enabled." : "Workflow disabled.");
        void refetch();
        setTogglingId(null);
      },
      onError: (e) => { toast.error(e.message); setTogglingId(null); },
    });
  }

  function handleTrigger(id: string) {
    setTriggeringId(id);
    triggerMutation.mutate(id, {
      onSuccess: (r) => {
        toast.success(r.message.slice(0, 120));
        setTriggeringId(null);
        void refetch();
      },
      onError: (e) => { toast.error(e.message); setTriggeringId(null); },
    });
  }

  function handleDelete(id: string) {
    deleteMutation.mutate(id, {
      onSuccess: () => toast.success("Workflow deleted."),
      onError: (e) => toast.error(e.message),
    });
  }

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="font-mono text-[11px] tracking-[0.14em] text-muted-foreground">WORKFLOW MANAGER</h3>
          <p className="mt-1 text-[13px] text-foreground">
            Create and manage recurring or event-driven workflows for your AI employees.
          </p>
          <p className="text-[12px] text-muted-foreground mt-0.5">
            HIGH-risk steps (send email, publish) always require human approval.
          </p>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="shrink-0 inline-flex items-center gap-1.5 border border-foreground/20 bg-foreground/5 px-2.5 py-1 font-mono text-[10px] tracking-[0.08em] hover:bg-foreground/10"
        >
          <Plus className="size-3" /> NEW
        </button>
      </div>

      {showCreate && <CreateWorkflowForm onDone={() => setShowCreate(false)} />}

      {isLoading ? (
        <div className="flex items-center gap-2 text-[12px] text-muted-foreground">
          <Loader2 className="size-3.5 animate-spin" /> Loading workflows...
        </div>
      ) : workflows.length === 0 ? (
        <div className="border border-border/40 p-4 text-center text-[12px] text-muted-foreground">
          No workflows yet. Click NEW to create one.
        </div>
      ) : (
        <div className="space-y-2">
          {workflows.map((wf) => (
            <WorkflowCard
              key={wf.id}
              wf={wf}
              onToggle={handleToggle}
              onTrigger={handleTrigger}
              onDelete={handleDelete}
              triggering={triggeringId === wf.id}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export default WorkflowManagerPanel;
