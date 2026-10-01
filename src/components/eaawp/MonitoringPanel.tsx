/**
 * MonitoringPanel — Autonomous Monitoring and Trigger Engine UI
 *
 * Shows the monitoring rules for the Digital Marketing Manager.
 * Administrators can view, enable/disable, create, edit and delete rules.
 * The evaluation history and linked execution plans are also shown.
 *
 * MOCK MODE (VITE_USE_REAL_API=false):
 *   Displays clearly-labelled SIMULATED data.
 *   Mutations (create/delete/enable/disable) show an informational
 *   message explaining real monitoring requires the backend.
 *
 * REAL MODE (VITE_USE_REAL_API=true):
 *   All operations go to the FastAPI backend.
 *   The scheduler runs in the backend process and evaluates rules
 *   on their configured frequency via the controlled data access layer.
 */

import { useState } from "react";
import {
  Activity,
  AlertTriangle,
  Check,
  ChevronDown,
  ChevronRight,
  Clock,
  Info,
  Loader2,
  Pause,
  Play,
  Plus,
  RefreshCw,
  Trash2,
  X,
  Zap,
} from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { USE_REAL_API } from "@/lib/api-client";
import {
  useMonitoringRules,
  useMonitoringStatus,
  useCreateMonitoringRule,
  useUpdateMonitoringRule,
  useDeleteMonitoringRule,
  useEnableMonitoringRule,
  useDisableMonitoringRule,
  useMonitoringAudit,
  useManuallyEvaluateRule,
  type MonitoringRuleFE,
  type MonitoringRuleCreate,
  type MonitoringCondition,
  type MonitoringFrequency,
  type MonitoringOperator,
  type MonitoringAggregateFn,
} from "@/hooks/use-api";

// ── Constants ─────────────────────────────────────────────────────────────────

const OPERATORS: { value: MonitoringOperator; label: string }[] = [
  { value: "decreases_by_more_than_pct", label: "Decreases by more than %" },
  { value: "increases_by_more_than_pct", label: "Increases by more than %" },
  { value: "falls_below", label: "Falls below" },
  { value: "exceeds", label: "Exceeds" },
  { value: "equals", label: "Equals" },
  { value: "is_unavailable", label: "Data becomes unavailable" },
  { value: "count_falls_below", label: "Row count falls below" },
  { value: "count_exceeds", label: "Row count exceeds" },
];

const FREQUENCIES: { value: MonitoringFrequency; label: string }[] = [
  { value: "hourly", label: "Every hour" },
  { value: "every_6h", label: "Every 6 hours" },
  { value: "daily", label: "Daily" },
];

const AGG_FNS: { value: MonitoringAggregateFn; label: string }[] = [
  { value: "avg", label: "Average" },
  { value: "sum", label: "Sum" },
  { value: "count", label: "Count" },
  { value: "max", label: "Maximum" },
  { value: "min", label: "Minimum" },
  { value: "latest", label: "Latest value" },
];

// ── Status badge ──────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: MonitoringRuleFE["status"] }) {
  const map: Record<string, { label: string; cls: string }> = {
    idle: { label: "IDLE", cls: "border-border text-muted-foreground" },
    evaluating: { label: "EVALUATING", cls: "border-primary/60 text-primary animate-pulse" },
    triggered: { label: "TRIGGERED", cls: "border-warning/60 text-warning" },
    error: { label: "ERROR", cls: "border-destructive/60 text-destructive" },
    disabled: { label: "DISABLED", cls: "border-border text-muted-foreground opacity-50" },
  };
  const entry = map[status] ?? { label: status.toUpperCase(), cls: "border-border text-muted-foreground" };
  return (
    <span className={cn("border px-1.5 py-0.5 font-mono text-[9px] tracking-[0.12em]", entry.cls)}>
      {entry.label}
    </span>
  );
}

// ── Result code badge ─────────────────────────────────────────────────────────

function ResultBadge({ result }: { result: string | null }) {
  if (!result) return <span className="text-muted-foreground">—</span>;
  const map: Record<string, string> = {
    condition_false: "text-success",
    condition_true: "text-warning",
    condition_true_cooldown: "text-muted-foreground",
    error: "text-destructive",
    permission_denied: "text-destructive",
    no_data: "text-muted-foreground",
  };
  return (
    <span className={cn("font-mono text-[10px]", map[result] ?? "text-muted-foreground")}>
      {result.replace(/_/g, " ").toUpperCase()}
    </span>
  );
}

// ── Frequency label ───────────────────────────────────────────────────────────

function freqLabel(freq: MonitoringFrequency): string {
  return FREQUENCIES.find((f) => f.value === freq)?.label ?? freq;
}

// ── Relative timestamp ────────────────────────────────────────────────────────

function relTime(iso: string | null): string {
  if (!iso) return "—";
  const diff = Date.now() - new Date(iso).getTime();
  const s = Math.floor(diff / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

// ── Audit log drawer ──────────────────────────────────────────────────────────

function RuleAuditLog({ ruleId }: { ruleId: string }) {
  const { data: audits, isLoading } = useMonitoringAudit(ruleId);

  if (!USE_REAL_API) {
    return (
      <p className="text-[11px] text-muted-foreground italic">
        Evaluation history requires VITE_USE_REAL_API=true.
      </p>
    );
  }

  if (isLoading) return <Loader2 className="size-4 animate-spin text-muted-foreground" />;
  if (!audits?.length)
    return <p className="text-[11px] text-muted-foreground">No evaluations recorded yet.</p>;

  return (
    <div className="max-h-48 overflow-y-auto border border-border">
      <table className="w-full text-[11px]">
        <thead>
          <tr className="border-b border-border bg-surface-2">
            <th className="px-2 py-1 text-left font-mono text-muted-foreground">Time</th>
            <th className="px-2 py-1 text-left font-mono text-muted-foreground">Result</th>
            <th className="px-2 py-1 text-left font-mono text-muted-foreground">Triggered</th>
            <th className="px-2 py-1 text-left font-mono text-muted-foreground">Value</th>
            <th className="px-2 py-1 text-left font-mono text-muted-foreground">Plan</th>
          </tr>
        </thead>
        <tbody>
          {audits.map((a) => (
            <tr key={a.id} className="border-b border-border last:border-0">
              <td className="px-2 py-1 text-muted-foreground">{relTime(a.evaluated_at)}</td>
              <td className="px-2 py-1">
                <ResultBadge result={a.result} />
              </td>
              <td className="px-2 py-1">
                {a.triggered ? (
                  <Zap className="size-3 text-warning" />
                ) : (
                  <span className="text-muted-foreground">—</span>
                )}
              </td>
              <td className="px-2 py-1 text-muted-foreground">
                {a.current_value !== null ? a.current_value.toFixed(2) : "—"}
              </td>
              <td className="px-2 py-1 font-mono text-[9px] text-muted-foreground">
                {a.triggered_plan_id ? a.triggered_plan_id.slice(0, 8) + "…" : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Rule row ──────────────────────────────────────────────────────────────────

function RuleRow({
  rule,
  roleKey,
  onEdit,
}: {
  rule: MonitoringRuleFE;
  roleKey: string;
  onEdit: (rule: MonitoringRuleFE) => void;
}) {
  const [expanded, setExpanded] = useState(false);

  const enable = useEnableMonitoringRule(roleKey);
  const disable = useDisableMonitoringRule(roleKey);
  const del = useDeleteMonitoringRule(roleKey);
  const evaluate = useManuallyEvaluateRule(roleKey);

  const isSimulated = rule.id.startsWith("mock-");

  function handleToggle() {
    if (!USE_REAL_API) {
      toast.info("Toggle requires VITE_USE_REAL_API=true. This is simulated data.");
      return;
    }
    if (rule.enabled) {
      disable.mutate(rule.id, { onSuccess: () => toast.success(`"${rule.name}" disabled`) });
    } else {
      enable.mutate(rule.id, { onSuccess: () => toast.success(`"${rule.name}" enabled`) });
    }
  }

  function handleDelete() {
    if (!USE_REAL_API) {
      toast.info("Delete requires VITE_USE_REAL_API=true.");
      return;
    }
    if (!confirm(`Delete monitoring rule "${rule.name}"? This cannot be undone.`)) return;
    del.mutate(rule.id, { onSuccess: () => toast.success("Rule deleted") });
  }

  function handleEvaluate() {
    if (!USE_REAL_API) {
      toast.info("Manual evaluation requires VITE_USE_REAL_API=true.");
      return;
    }
    evaluate.mutate(rule.id, {
      onSuccess: (result) => {
        const r = result as Record<string, unknown>;
        if (r["triggered"]) {
          toast.success(`Rule triggered — plan created: ${String(r["plan_id"] ?? "").slice(0, 8)}`);
        } else {
          toast.info(`Evaluated: ${String(r["result"] ?? "condition_false")}`);
        }
      },
      onError: (e) => toast.error(e.message),
    });
  }

  const cond = rule.condition;
  const needsField = cond.operator !== "is_unavailable";
  const isPct = cond.operator === "decreases_by_more_than_pct" || cond.operator === "increases_by_more_than_pct";

  const condSummary = cond.operator === "is_unavailable"
    ? `Data for "${rule.semantic_concept}" becomes unavailable`
    : `${rule.semantic_concept}.${cond.metric_field} ${OPERATORS.find((o) => o.value === cond.operator)?.label.toLowerCase() ?? cond.operator} ${cond.threshold}${isPct ? "%" : ""}`;

  return (
    <div className={cn("border-b border-border last:border-0", !rule.enabled && "opacity-60")}>
      {/* Main row */}
      <div className="flex items-center gap-3 px-3 py-2.5">
        <button
          onClick={() => setExpanded((e) => !e)}
          className="text-muted-foreground hover:text-foreground"
          aria-label="Expand rule"
        >
          {expanded ? (
            <ChevronDown className="size-3.5" strokeWidth={2} />
          ) : (
            <ChevronRight className="size-3.5" strokeWidth={2} />
          )}
        </button>

        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-[13px] font-medium truncate">{rule.name}</span>
            {isSimulated && (
              <span className="shrink-0 border border-border px-1 font-mono text-[8px] text-muted-foreground tracking-widest">
                SIMULATED
              </span>
            )}
            <StatusBadge status={rule.status} />
          </div>
          <p className="mt-0.5 text-[11px] text-muted-foreground truncate">{condSummary}</p>
          <div className="mt-0.5 flex items-center gap-3 text-[10px] text-muted-foreground">
            <span className="flex items-center gap-1">
              <Clock className="size-3" strokeWidth={1.5} />
              {freqLabel(rule.evaluation_frequency)}
            </span>
            <span>Last eval: {relTime(rule.last_evaluated_at)}</span>
            {rule.last_triggered_at && (
              <span className="flex items-center gap-1 text-warning">
                <Zap className="size-3" strokeWidth={1.5} />
                Triggered: {relTime(rule.last_triggered_at)}
              </span>
            )}
            {rule.last_triggered_plan_id && (
              <span className="font-mono text-[9px] text-muted-foreground">
                plan:{rule.last_triggered_plan_id.slice(0, 8)}
              </span>
            )}
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-1">
          {/* Last result */}
          {rule.last_evaluation_result && (
            <ResultBadge result={rule.last_evaluation_result} />
          )}

          {/* Manual evaluate */}
          <button
            onClick={handleEvaluate}
            disabled={evaluate.isPending}
            title="Manually trigger evaluation"
            className="border border-border px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground hover:text-primary hover:border-primary disabled:opacity-40"
          >
            {evaluate.isPending ? (
              <Loader2 className="size-3 animate-spin" />
            ) : (
              <Activity className="size-3" strokeWidth={1.5} />
            )}
          </button>

          {/* Edit */}
          <button
            onClick={() => onEdit(rule)}
            title="Edit rule"
            className="border border-border px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground hover:text-foreground hover:border-foreground"
          >
            EDIT
          </button>

          {/* Enable/Disable toggle */}
          <button
            onClick={handleToggle}
            disabled={enable.isPending || disable.isPending}
            title={rule.enabled ? "Disable rule" : "Enable rule"}
            className={cn(
              "border px-1.5 py-0.5 font-mono text-[10px] disabled:opacity-40",
              rule.enabled
                ? "border-primary text-primary hover:bg-primary/10"
                : "border-border text-muted-foreground hover:text-foreground",
            )}
          >
            {rule.enabled ? <Pause className="size-3" strokeWidth={2} /> : <Play className="size-3" strokeWidth={2} />}
          </button>

          {/* Delete */}
          <button
            onClick={handleDelete}
            disabled={del.isPending}
            title="Delete rule"
            className="border border-border px-1.5 py-0.5 text-muted-foreground hover:border-destructive hover:text-destructive disabled:opacity-40"
          >
            <Trash2 className="size-3" strokeWidth={1.5} />
          </button>
        </div>
      </div>

      {/* Expanded detail */}
      {expanded && (
        <div className="border-t border-border bg-surface-2 px-4 py-3">
          <div className="grid grid-cols-1 gap-3 text-[12px] md:grid-cols-2">
            <div>
              <p className="label-xs mb-1">Condition</p>
              <p className="text-muted-foreground">{condSummary}</p>
              {needsField && (
                <p className="mt-0.5 text-muted-foreground">
                  Aggregation: {AGG_FNS.find((a) => a.value === cond.aggregate_fn)?.label ?? cond.aggregate_fn}
                  {isPct && ` · Window: ${cond.comparison_window_hours ?? 24}h`}
                </p>
              )}
            </div>
            <div>
              <p className="label-xs mb-1">Action on trigger</p>
              <p className="text-muted-foreground">{rule.action_objective}</p>
              {rule.require_approval_on_trigger && (
                <p className="mt-0.5 text-warning text-[11px]">⚠ Requires approval before execution</p>
              )}
            </div>
            <div>
              <p className="label-xs mb-1">Deduplication cooldown</p>
              <p className="text-muted-foreground">{rule.cooldown_hours}h between triggers</p>
            </div>
            <div>
              <p className="label-xs mb-1">Next evaluation</p>
              <p className="text-muted-foreground">{rule.next_evaluation_at ? relTime(rule.next_evaluation_at) : "Not scheduled"}</p>
            </div>
            {rule.last_error_message && (
              <div className="md:col-span-2">
                <p className="label-xs mb-1 text-destructive">Last error</p>
                <p className="text-[11px] text-destructive">{rule.last_error_message}</p>
              </div>
            )}
            {rule.description && (
              <div className="md:col-span-2">
                <p className="label-xs mb-1">Description</p>
                <p className="text-muted-foreground">{rule.description}</p>
              </div>
            )}
          </div>
          {/* Evaluation audit log */}
          <div className="mt-3">
            <p className="label-xs mb-1">Evaluation history</p>
            <RuleAuditLog ruleId={rule.id} />
          </div>
        </div>
      )}
    </div>
  );
}

// ── Rule form (create / edit) ─────────────────────────────────────────────────

const EMPTY_CONDITION: MonitoringCondition = {
  metric_field: "",
  operator: "falls_below",
  threshold: 0,
  comparison_window_hours: 24,
  aggregate_fn: "avg",
};

const EMPTY_FORM: MonitoringRuleCreate = {
  name: "",
  description: "",
  enabled: true,
  semantic_concept: "",
  condition: EMPTY_CONDITION,
  evaluation_frequency: "daily",
  action_objective: "",
  require_approval_on_trigger: false,
  cooldown_hours: 24,
};

function RuleForm({
  initial,
  roleKey,
  onClose,
}: {
  initial?: MonitoringRuleFE;
  roleKey: string;
  onClose: () => void;
}) {
  const [form, setForm] = useState<MonitoringRuleCreate>(
    initial
      ? {
          name: initial.name,
          description: initial.description,
          enabled: initial.enabled,
          semantic_concept: initial.semantic_concept,
          condition: initial.condition,
          evaluation_frequency: initial.evaluation_frequency,
          action_objective: initial.action_objective,
          require_approval_on_trigger: initial.require_approval_on_trigger,
          cooldown_hours: initial.cooldown_hours,
        }
      : EMPTY_FORM,
  );

  const create = useCreateMonitoringRule(roleKey);
  const update = useUpdateMonitoringRule(roleKey);
  const isEditing = !!initial;
  const isPending = create.isPending || update.isPending;

  const needsField = form.condition.operator !== "is_unavailable";
  const isPct =
    form.condition.operator === "decreases_by_more_than_pct" ||
    form.condition.operator === "increases_by_more_than_pct";

  function setCondField<K extends keyof MonitoringCondition>(key: K, val: MonitoringCondition[K]) {
    setForm((f) => ({ ...f, condition: { ...f.condition, [key]: val } }));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();

    if (!USE_REAL_API) {
      toast.info(
        "Creating real monitoring rules requires VITE_USE_REAL_API=true and the backend running. " +
          "This is simulated mode.",
        { duration: 6000 },
      );
      onClose();
      return;
    }

    try {
      if (isEditing && initial) {
        await update.mutateAsync({ ruleId: initial.id, update: form });
        toast.success("Rule updated");
      } else {
        await create.mutateAsync(form);
        toast.success("Monitoring rule created");
      }
      onClose();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save rule");
    }
  }

  return (
    <form
      onSubmit={(e) => void handleSubmit(e)}
      className="border border-border bg-surface p-4 space-y-3"
    >
      <div className="flex items-center justify-between border-b border-border pb-2">
        <h3 className="font-mono text-[11px] tracking-widest">
          {isEditing ? "EDIT MONITORING RULE" : "CREATE MONITORING RULE"}
        </h3>
        <button type="button" onClick={onClose} className="text-muted-foreground hover:text-foreground">
          <X className="size-4" strokeWidth={1.5} />
        </button>
      </div>

      {!USE_REAL_API && (
        <div className="flex gap-2 border border-border bg-surface-2 p-2 text-[11px] text-muted-foreground">
          <Info className="size-3.5 shrink-0 mt-0.5 text-primary" strokeWidth={1.5} />
          <span>
            <strong>Simulated mode</strong> — submitting this form will not create a real monitoring
            rule. Set VITE_USE_REAL_API=true and start the backend to create real rules.
          </span>
        </div>
      )}

      {/* Name */}
      <div>
        <label className="label-xs">Rule name *</label>
        <input
          required
          value={form.name}
          onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
          placeholder="e.g. CTR Drop Alert"
          className="mt-1 h-8 w-full border border-input bg-background px-2 text-[13px] outline-none focus:border-ring"
        />
      </div>

      {/* Semantic concept */}
      <div>
        <label className="label-xs">
          Semantic concept *{" "}
          <span className="text-muted-foreground">(must have a mapping configured)</span>
        </label>
        <input
          required
          value={form.semantic_concept}
          onChange={(e) => setForm((f) => ({ ...f, semantic_concept: e.target.value }))}
          placeholder="e.g. campaign_clicks"
          className="mt-1 h-8 w-full border border-input bg-background px-2 font-mono text-[12px] outline-none focus:border-ring"
        />
      </div>

      {/* Condition */}
      <div className="border border-border p-3 space-y-2">
        <p className="label-xs">Condition (structured — no SQL or code)</p>

        <div>
          <label className="label-xs text-muted-foreground">Operator</label>
          <select
            value={form.condition.operator}
            onChange={(e) => setCondField("operator", e.target.value as MonitoringOperator)}
            className="mt-1 h-8 w-full border border-input bg-background px-2 text-[12px] outline-none focus:border-ring"
          >
            {OPERATORS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </div>

        {needsField && (
          <>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="label-xs text-muted-foreground">
                  Field name (identifier only)
                </label>
                <input
                  required
                  value={form.condition.metric_field}
                  onChange={(e) => setCondField("metric_field", e.target.value)}
                  placeholder="e.g. clicks"
                  pattern="[a-zA-Z_][a-zA-Z0-9_]*"
                  title="Only letters, digits, and underscores allowed"
                  className="mt-1 h-8 w-full border border-input bg-background px-2 font-mono text-[12px] outline-none focus:border-ring"
                />
              </div>
              <div>
                <label className="label-xs text-muted-foreground">
                  Threshold {isPct ? "(% change)" : "(value)"}
                </label>
                <input
                  required
                  type="number"
                  step="any"
                  value={form.condition.threshold}
                  onChange={(e) => setCondField("threshold", parseFloat(e.target.value) || 0)}
                  className="mt-1 h-8 w-full border border-input bg-background px-2 text-[13px] outline-none focus:border-ring"
                />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="label-xs text-muted-foreground">Aggregation</label>
                <select
                  value={form.condition.aggregate_fn ?? "avg"}
                  onChange={(e) => setCondField("aggregate_fn", e.target.value as MonitoringAggregateFn)}
                  className="mt-1 h-8 w-full border border-input bg-background px-2 text-[12px] outline-none focus:border-ring"
                >
                  {AGG_FNS.map((a) => (
                    <option key={a.value} value={a.value}>
                      {a.label}
                    </option>
                  ))}
                </select>
              </div>
              {isPct && (
                <div>
                  <label className="label-xs text-muted-foreground">
                    Comparison window (hours)
                  </label>
                  <input
                    type="number"
                    min={1}
                    max={720}
                    value={form.condition.comparison_window_hours ?? 24}
                    onChange={(e) => setCondField("comparison_window_hours", parseInt(e.target.value) || 24)}
                    className="mt-1 h-8 w-full border border-input bg-background px-2 text-[13px] outline-none focus:border-ring"
                  />
                </div>
              )}
            </div>
          </>
        )}
      </div>

      {/* Evaluation frequency */}
      <div>
        <label className="label-xs">
          Evaluation frequency{" "}
          <span className="text-muted-foreground">(minimum: hourly)</span>
        </label>
        <div className="mt-1 flex gap-1.5">
          {FREQUENCIES.map((f) => (
            <button
              key={f.value}
              type="button"
              onClick={() => setForm((form) => ({ ...form, evaluation_frequency: f.value }))}
              className={cn(
                "border px-2 py-1 font-mono text-[10px] tracking-[0.1em]",
                form.evaluation_frequency === f.value
                  ? "border-primary text-primary"
                  : "border-border text-muted-foreground hover:text-foreground",
              )}
            >
              {f.label.toUpperCase()}
            </button>
          ))}
        </div>
      </div>

      {/* Action objective */}
      <div>
        <label className="label-xs">
          Action objective *{" "}
          <span className="text-muted-foreground">(what to do when condition is triggered)</span>
        </label>
        <textarea
          required
          rows={2}
          value={form.action_objective}
          onChange={(e) => setForm((f) => ({ ...f, action_objective: e.target.value }))}
          placeholder="e.g. Investigate the CTR drop and create a review task for underperforming campaigns"
          className="mt-1 w-full resize-none border border-input bg-background p-2 text-[13px] outline-none focus:border-ring"
        />
      </div>

      {/* Cooldown */}
      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="label-xs">Cooldown hours (deduplication)</label>
          <input
            type="number"
            min={1}
            max={720}
            value={form.cooldown_hours ?? 24}
            onChange={(e) =>
              setForm((f) => ({ ...f, cooldown_hours: parseInt(e.target.value) || 24 }))
            }
            className="mt-1 h-8 w-full border border-input bg-background px-2 text-[13px] outline-none focus:border-ring"
          />
        </div>
        <div className="flex flex-col justify-end">
          <label className="flex cursor-pointer items-center gap-2 pb-1 text-[12px]">
            <input
              type="checkbox"
              checked={form.require_approval_on_trigger ?? false}
              onChange={(e) =>
                setForm((f) => ({ ...f, require_approval_on_trigger: e.target.checked }))
              }
              className="size-3.5"
            />
            Require approval before executing triggered plan
          </label>
        </div>
      </div>

      {/* Description */}
      <div>
        <label className="label-xs">Description (optional)</label>
        <input
          value={form.description ?? ""}
          onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
          placeholder="Brief description of why this rule exists"
          className="mt-1 h-8 w-full border border-input bg-background px-2 text-[13px] outline-none focus:border-ring"
        />
      </div>

      {/* Submit */}
      <div className="flex gap-2 border-t border-border pt-3">
        <button
          type="submit"
          disabled={isPending}
          className="flex items-center gap-1.5 border border-primary px-4 py-1.5 font-mono text-[10px] tracking-widest text-primary hover:bg-primary/10 disabled:opacity-40"
        >
          {isPending ? (
            <Loader2 className="size-3 animate-spin" />
          ) : (
            <Check className="size-3" strokeWidth={2.5} />
          )}
          {isEditing ? "SAVE CHANGES" : "CREATE RULE"}
        </button>
        <button
          type="button"
          onClick={onClose}
          className="border border-border px-3 py-1.5 font-mono text-[10px] tracking-widest text-muted-foreground hover:text-foreground"
        >
          CANCEL
        </button>
      </div>
    </form>
  );
}

// ── Scheduler status banner ───────────────────────────────────────────────────

function SchedulerBanner({ roleKey }: { roleKey: string }) {
  const { data: status } = useMonitoringStatus();

  if (!status) return null;

  return (
    <div
      className={cn(
        "flex items-start gap-2 border px-3 py-2 text-[11px]",
        status.scheduler_running
          ? "border-success/30 bg-success/5 text-success"
          : "border-border bg-surface-2 text-muted-foreground",
      )}
    >
      {status.scheduler_running ? (
        <Activity className="mt-0.5 size-3.5 shrink-0" strokeWidth={1.5} />
      ) : (
        <Info className="mt-0.5 size-3.5 shrink-0" strokeWidth={1.5} />
      )}
      <div className="flex-1">
        <span className="font-medium">
          {status.scheduler_running ? "Scheduler running" : "Scheduler not running"}
        </span>
        {" — "}
        {status.note}
      </div>
      <span className="shrink-0 font-mono text-[10px]">
        {status.enabled_rules}/{status.total_rules} rules active
      </span>
    </div>
  );
}

// ── Main panel ────────────────────────────────────────────────────────────────

interface MonitoringPanelProps {
  roleKey?: string;
}

export function MonitoringPanel({ roleKey = "DIGITAL_MARKETING_MANAGER" }: MonitoringPanelProps) {
  const { data: rules, isLoading, isError, refetch, isFetching } = useMonitoringRules(roleKey);
  const [creating, setCreating] = useState(false);
  const [editingRule, setEditingRule] = useState<MonitoringRuleFE | null>(null);

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 p-4 text-[13px] text-muted-foreground">
        <Loader2 className="size-4 animate-spin" />
        Loading monitoring rules…
      </div>
    );
  }

  if (isError) {
    return (
      <div className="flex items-center gap-2 p-3 text-[13px] text-destructive">
        <AlertTriangle className="size-4 shrink-0" strokeWidth={1.5} />
        Failed to load monitoring rules. Check backend connection.
      </div>
    );
  }

  const ruleList = rules ?? [];

  return (
    <div className="space-y-3">
      {/* Scheduler status */}
      <SchedulerBanner roleKey={roleKey} />

      {/* Header row */}
      <div className="flex items-center justify-between">
        <p className="text-[12px] text-muted-foreground">
          {ruleList.length} rule{ruleList.length !== 1 ? "s" : ""} configured
          {!USE_REAL_API && (
            <span className="ml-1 text-muted-foreground/60">(simulated)</span>
          )}
        </p>
        <div className="flex items-center gap-1.5">
          <button
            onClick={() => void refetch()}
            disabled={isFetching}
            className="border border-border px-2 py-1 text-muted-foreground hover:text-foreground disabled:opacity-40"
            title="Refresh rules"
          >
            <RefreshCw className={cn("size-3", isFetching && "animate-spin")} strokeWidth={1.5} />
          </button>
          <button
            onClick={() => {
              setEditingRule(null);
              setCreating(true);
            }}
            className="flex items-center gap-1 border border-primary px-2 py-1 font-mono text-[10px] tracking-widest text-primary hover:bg-primary/10"
          >
            <Plus className="size-3" strokeWidth={2.5} />
            NEW RULE
          </button>
        </div>
      </div>

      {/* Create / edit form */}
      {(creating || editingRule) && (
        <RuleForm
          {...(editingRule !== null ? { initial: editingRule } : {})}
          roleKey={roleKey}
          onClose={() => {
            setCreating(false);
            setEditingRule(null);
          }}
        />
      )}

      {/* Rules list */}
      {ruleList.length === 0 && !creating ? (
        <div className="border border-border bg-surface-2 p-6 text-center text-[13px] text-muted-foreground">
          <Activity className="mx-auto mb-2 size-8 opacity-30" strokeWidth={1} />
          <p className="font-medium">No monitoring rules configured</p>
          <p className="mt-1 text-[11px]">
            Create a rule to automatically monitor your company data and trigger
            plans when conditions are met.
          </p>
          {!USE_REAL_API && (
            <p className="mt-2 text-[10px] text-muted-foreground/70">
              Real monitoring requires VITE_USE_REAL_API=true and the backend running.
            </p>
          )}
        </div>
      ) : (
        <div className="border border-border">
          {ruleList.map((rule) => (
            <RuleRow
              key={rule.id}
              rule={rule}
              roleKey={roleKey}
              onEdit={(r) => {
                setEditingRule(r);
                setCreating(false);
              }}
            />
          ))}
        </div>
      )}

      {/* Footer note */}
      <p className="text-[10px] text-muted-foreground">
        Triggered plans appear in the Activity, Tasks, and Planning sections.
        All evaluations go through: rule → authorised data access → structured condition →
        planning engine → action governance → approval (if required) → audit.
      </p>
    </div>
  );
}
