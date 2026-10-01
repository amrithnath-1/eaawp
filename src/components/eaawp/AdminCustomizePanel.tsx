/**
 * AdminCustomizePanel — Admin AI Control Center
 *
 * Company Admin only. Lets administrators configure the AI workforce in
 * natural language. The system generates a structured plan for review;
 * the admin confirms before anything is applied.
 *
 * Security:
 * - Only shown when the session user has role "Company Admin" or "Admin".
 * - All API calls require a JWT with admin role — backend enforces 403.
 * - Credentials are never collected or displayed here.
 * - The confirmation step re-validates on the backend before execution.
 */
import { useState } from "react";
import { toast } from "sonner";
import {
  Send, Loader2, CheckCircle, XCircle, AlertTriangle,
  ShieldCheck, ChevronDown, ChevronRight, Zap,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useSession } from "@/state/session";
import {
  useGenerateCustomizationPlan,
  useExecuteCustomizationPlan,
  type CustomizationPlan,
  type CustomizationOperation,
  type OperationResult,
} from "@/hooks/use-api";

// ── Quick prompts ─────────────────────────────────────────────────────────────
const QUICK_PROMPTS = [
  "Create a Digital Marketing Manager that uses Google Analytics and Search Console",
  "Connect Google Search Console and grant access to the marketing employee",
  "Create a weekly marketing report workflow every Monday at 9 AM",
  "Require approval before sending anything externally",
  "Create a competitor analysis AI employee",
];

// ── Operation type badge ──────────────────────────────────────────────────────
const OP_COLOURS: Record<string, string> = {
  CREATE_AI_EMPLOYEE:   "border-success/40 text-success",
  UPDATE_AI_EMPLOYEE:   "border-warning/40 text-warning",
  CONNECT_INTEGRATION:  "border-blue-400/40 text-blue-400",
  GRANT_CAPABILITY:     "border-success/40 text-success",
  REVOKE_CAPABILITY:    "border-destructive/40 text-destructive",
  CREATE_WORKFLOW:      "border-purple-400/40 text-purple-400",
  UPDATE_WORKFLOW:      "border-warning/40 text-warning",
  SET_APPROVAL_POLICY:  "border-warning/40 text-warning",
};

function OpBadge({ type }: { type: string }) {
  return (
    <span className={cn("border px-1.5 py-0.5 font-mono text-[9px] tracking-[0.06em]", OP_COLOURS[type] ?? "border-border text-muted-foreground")}>
      {type.replace(/_/g, " ")}
    </span>
  );
}

// ── Plan display ──────────────────────────────────────────────────────────────
function PlanCard({
  plan,
  onConfirm,
  onDiscard,
  confirming,
}: {
  plan: CustomizationPlan;
  onConfirm: () => void;
  onDiscard: () => void;
  confirming: boolean;
}) {
  const [expanded, setExpanded] = useState<number | null>(null);

  return (
    <div className="border border-border bg-surface space-y-3 p-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="font-mono text-[10px] tracking-[0.14em] text-muted-foreground">PROPOSED CUSTOMIZATION PLAN</p>
          <p className="mt-1 text-[12px] text-foreground">{plan.summary}</p>
        </div>
        <ShieldCheck className="size-4 text-muted-foreground shrink-0 mt-0.5" />
      </div>

      {/* Missing information warning */}
      {plan.missing_information.length > 0 && (
        <div className="border border-warning/30 bg-warning/5 p-2 space-y-0.5">
          <div className="flex items-center gap-1 font-mono text-[10px] tracking-[0.08em] text-warning">
            <AlertTriangle className="size-3" /> INFORMATION NEEDED
          </div>
          {plan.missing_information.map((m, i) => (
            <div key={i} className="text-[11px] text-muted-foreground">• {m}</div>
          ))}
        </div>
      )}

      {/* Operations list */}
      {plan.operations.length > 0 && (
        <div className="space-y-1.5">
          <p className="font-mono text-[10px] tracking-[0.12em] text-muted-foreground">
            OPERATIONS ({plan.operations.length})
          </p>
          {plan.operations.map((op, i) => (
            <div key={i} className="border border-border/50 p-2">
              <div className="flex items-start gap-2.5">
                <span className="font-mono text-[10px] text-muted-foreground/60 shrink-0 mt-0.5 w-4">{i + 1}.</span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <OpBadge type={op.type} />
                  </div>
                  <p className="text-[11px] text-foreground mt-0.5">{op.description}</p>
                </div>
                <button
                  onClick={() => setExpanded(expanded === i ? null : i)}
                  className="shrink-0 text-muted-foreground hover:text-foreground"
                >
                  {expanded === i ? <ChevronDown className="size-3" /> : <ChevronRight className="size-3" />}
                </button>
              </div>
              {expanded === i && Object.keys(op.params).length > 0 && (
                <div className="mt-1.5 ml-6 text-[10px] font-mono text-muted-foreground/70 space-y-0.5">
                  {Object.entries(op.params).map(([k, v]) => (
                    <div key={k}>
                      <span className="text-muted-foreground/50">{k}: </span>
                      <span>{String(v).slice(0, 100)}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {plan.operations.length === 0 && plan.missing_information.length === 0 && (
        <p className="text-[12px] text-muted-foreground">
          No operations generated. Please provide more detail in your instruction.
        </p>
      )}

      {/* Confirm / Discard */}
      {plan.operations.length > 0 && (
        <div className="flex gap-2 pt-1">
          <button
            onClick={onConfirm}
            disabled={confirming}
            className="inline-flex items-center gap-1.5 border border-success/40 px-3 py-1 font-mono text-[10px] tracking-[0.08em] text-success hover:bg-success/10 disabled:opacity-50"
          >
            {confirming ? <Loader2 className="size-3 animate-spin" /> : <ShieldCheck className="size-3" />}
            CONFIRM & APPLY
          </button>
          <button
            onClick={onDiscard}
            disabled={confirming}
            className="inline-flex items-center gap-1.5 border border-destructive/40 px-3 py-1 font-mono text-[10px] tracking-[0.08em] text-destructive hover:bg-destructive/10 disabled:opacity-50"
          >
            <XCircle className="size-3" /> DISCARD
          </button>
        </div>
      )}
    </div>
  );
}

// ── Result display ────────────────────────────────────────────────────────────
function ResultCard({ result }: { result: OperationResult }) {
  const icon = result.status === "success"
    ? <CheckCircle className="size-3.5 text-success shrink-0" />
    : result.status === "failed"
    ? <XCircle className="size-3.5 text-destructive shrink-0" />
    : <AlertTriangle className="size-3.5 text-muted-foreground shrink-0" />;

  return (
    <div className="flex items-start gap-2.5 border-b border-border/30 py-2 last:border-0">
      {icon}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <OpBadge type={result.type} />
          <span className={cn("font-mono text-[10px]",
            result.status === "success" ? "text-success" :
            result.status === "failed" ? "text-destructive" : "text-muted-foreground"
          )}>
            {result.status.toUpperCase()}
          </span>
        </div>
        <p className="text-[11px] text-muted-foreground mt-0.5">{result.detail}</p>
      </div>
    </div>
  );
}

// ── Main panel ────────────────────────────────────────────────────────────────
export function AdminCustomizePanel() {
  const { user } = useSession();
  const [instruction, setInstruction] = useState("");
  const [currentPlan, setCurrentPlan] = useState<CustomizationPlan | null>(null);
  const [executionResult, setExecutionResult] = useState<import("@/hooks/use-api").AdminCustomizationResult | null>(null);

  const generateMutation = useGenerateCustomizationPlan();
  const executeMutation = useExecuteCustomizationPlan();

  // Role gate: Company Admin and Admin only (backend also enforces 403)
  const isAdmin = user?.role?.toLowerCase().includes("admin") ?? false;

  if (!isAdmin) {
    return (
      <div className="border border-destructive/30 bg-destructive/5 p-4 space-y-1">
        <div className="flex items-center gap-2 font-mono text-[11px] tracking-[0.08em] text-destructive">
          <ShieldCheck className="size-3.5" /> ADMIN ACCESS REQUIRED
        </div>
        <p className="text-[12px] text-muted-foreground">
          This panel is only accessible to Company Administrators.
        </p>
      </div>
    );
  }

  function handleGenerate() {
    if (!instruction.trim()) return;
    setCurrentPlan(null);
    setExecutionResult(null);
    generateMutation.mutate(
      { instruction: instruction.trim(), requested_by: user?.email ?? "admin" },
      {
        onSuccess: (plan) => {
          setCurrentPlan(plan);
          if (plan.missing_information.length > 0) {
            toast.info("Some information is needed before proceeding — see the plan below.");
          }
        },
        onError: (e) => toast.error(e.message),
      }
    );
  }

  function handleConfirm() {
    if (!currentPlan) return;
    executeMutation.mutate(
      { plan: currentPlan, confirmed_by: user?.email ?? "admin" },
      {
        onSuccess: (result) => {
          setExecutionResult(result);
          setCurrentPlan(null);
          setInstruction("");
          if (result.operations_failed === 0) {
            toast.success(`Plan applied: ${result.operations_succeeded} operation(s) succeeded.`);
          } else {
            toast.error(`${result.operations_failed} operation(s) failed. See results below.`);
          }
        },
        onError: (e) => toast.error(e.message),
      }
    );
  }

  function handleDiscard() {
    setCurrentPlan(null);
    toast.info("Plan discarded — no changes were made.");
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div>
        <h3 className="font-mono text-[11px] tracking-[0.14em] text-muted-foreground">
          ADMIN AI CONTROL CENTER
        </h3>
        <p className="mt-1 text-[13px] text-foreground">
          Tell EAAWP how you want your company AI workforce configured.
          The system generates a plan for your review before applying any changes.
        </p>
        <p className="text-[12px] text-muted-foreground mt-0.5">
          No credentials or secrets are passed through this interface.
          HIGH-risk actions still require human approval.
        </p>
      </div>

      {/* Instruction input */}
      <div className="border border-border bg-surface p-3 space-y-3">
        <p className="font-mono text-[10px] tracking-[0.14em] text-muted-foreground">DESCRIBE YOUR CUSTOMIZATION</p>
        <textarea
          value={instruction}
          onChange={(e) => setInstruction(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && e.ctrlKey) { e.preventDefault(); handleGenerate(); } }}
          placeholder={
            'e.g. "Create a Digital Marketing Manager that uses Google Analytics and Search Console, ' +
            'prepares a report every Monday at 9 AM, and requires approval before sending anything externally."'
          }
          rows={4}
          disabled={generateMutation.isPending || executeMutation.isPending}
          className="w-full border border-input bg-background px-2 py-1.5 text-[12px] outline-none focus:border-ring resize-none"
        />
        <div className="flex items-center gap-2 flex-wrap">
          <button
            onClick={handleGenerate}
            disabled={generateMutation.isPending || !instruction.trim() || !!currentPlan}
            className="inline-flex items-center gap-2 border border-foreground/20 bg-foreground/5 px-3 py-1.5 font-mono text-[11px] tracking-[0.08em] hover:bg-foreground/10 disabled:opacity-50"
          >
            {generateMutation.isPending ? (
              <Loader2 className="size-3.5 animate-spin" />
            ) : (
              <Zap className="size-3.5" />
            )}
            GENERATE PLAN
          </button>
          <span className="text-[10px] text-muted-foreground font-mono">Ctrl+Enter</span>
        </div>
      </div>

      {/* Quick prompts */}
      <div className="flex flex-wrap gap-1">
        {QUICK_PROMPTS.map((p) => (
          <button
            key={p}
            onClick={() => { setInstruction(p); setCurrentPlan(null); setExecutionResult(null); }}
            disabled={generateMutation.isPending || executeMutation.isPending}
            className="border border-border/50 px-2 py-0.5 font-mono text-[9px] tracking-[0.04em] text-muted-foreground hover:border-foreground/30 hover:text-foreground disabled:opacity-40"
          >
            {p.slice(0, 50)}{p.length > 50 ? "..." : ""}
          </button>
        ))}
      </div>

      {/* Proposed plan */}
      {currentPlan && (
        <PlanCard
          plan={currentPlan}
          onConfirm={handleConfirm}
          onDiscard={handleDiscard}
          confirming={executeMutation.isPending}
        />
      )}

      {/* Execution result */}
      {executionResult && (
        <div className="border border-border bg-surface p-3 space-y-2">
          <div className="flex items-center justify-between">
            <p className="font-mono text-[10px] tracking-[0.14em] text-muted-foreground">EXECUTION RESULT</p>
            <span className={cn("font-mono text-[10px]",
              executionResult.operations_failed === 0 ? "text-success" : "text-warning"
            )}>
              {executionResult.operations_succeeded}/{executionResult.operations_total} SUCCEEDED
            </span>
          </div>
          <p className="text-[12px] text-foreground">{executionResult.plan_summary}</p>
          <div className="border border-border divide-y divide-border/30">
            {executionResult.results.map((r, i) => (
              <div key={i} className="px-3">
                <ResultCard result={r} />
              </div>
            ))}
          </div>
          <p className="text-[10px] text-muted-foreground font-mono">
            Audit ID: {executionResult.audit_id} · {new Date(executionResult.executed_at).toLocaleString()}
          </p>
          <button
            onClick={() => { setExecutionResult(null); setInstruction(""); }}
            className="font-mono text-[10px] text-muted-foreground hover:text-foreground"
          >
            CLEAR RESULTS
          </button>
        </div>
      )}
    </div>
  );
}

export default AdminCustomizePanel;
