/**
 * ApprovalCenterPanel — Centralized Approval Review
 *
 * Shows all pending and resolved approval requests.
 * Administrators can approve or reject actions here.
 *
 * Security:
 * - No secrets are displayed.
 * - Approval/rejection goes through the backend — not just frontend state.
 * - Parameter summaries are truncated to prevent information leakage.
 * - The panel refetches every 15 seconds for real-time pending approvals.
 */
import { useState } from "react";
import { toast } from "sonner";
import {
  CheckCircle, XCircle, Clock, AlertTriangle, Loader2,
  ShieldCheck, ShieldOff, ChevronDown, ChevronRight,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useSession } from "@/state/session";
import { IS_ADMIN_ROLE } from "@/lib/workspace";
import {
  useApprovalRequests,
  useActionAudits,
  useApproveAction,
  useExecutionPlans,
  useRejectAction,
  useRejectPlan,
  useResumePlan,
  type ApprovalRequestOut,
} from "@/hooks/use-api";

type FilterStatus = "all" | "pending" | "approved" | "rejected";

function RiskBadge({ risk }: { risk: string | null | undefined }) {
  if (!risk) return null;   // no linked governed action: no risk is claimed
  const cls = risk === "high" ? "text-destructive border-destructive/40"
    : risk === "medium" ? "text-warning border-warning/40" : "text-success border-success/40";
  return (
    <span className={cn("border px-1 py-0.5 font-mono text-[9px] tracking-[0.06em]", cls)}>
      {risk.toUpperCase()} RISK
    </span>
  );
}

const EXECUTION_TEXT: Record<string, string> = {
  pending: "Not executed yet",
  executed: "Executed",
  failed: "Execution failed",
  skipped: "Not executed (rejected)",
  rejected: "Not executed (rejected)",
};

function StatusIcon({ status }: { status: string }) {
  if (status === "approved") return <CheckCircle className="size-3.5 text-success" />;
  if (status === "rejected") return <XCircle className="size-3.5 text-destructive" />;
  return <Clock className="size-3.5 text-warning animate-pulse" />;
}

function ApprovalCard({
  request,
  onDecide,
  deciding,
  canDecide,
}: {
  request: ApprovalRequestOut;
  onDecide: (id: string, decision: "approved" | "rejected") => void;
  deciding: boolean;
  canDecide: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const isPending = request.status === "pending";

  // Safe truncated detail summary — never show secrets
  const safeDetail = request.detail.slice(0, 300) + (request.detail.length > 300 ? "..." : "");

  return (
    <div className={cn(
      "border bg-surface p-3 space-y-2",
      isPending ? "border-warning/30" : "border-border"
    )}>
      <div className="flex items-start gap-2.5">
        <StatusIcon status={request.status} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-mono text-[11px] tracking-[0.06em]">{request.tool_name ? request.tool_name.replace(/_/g, " ") : request.action}</span>
            <RiskBadge risk={request.risk_level} />
            {request.execution_status && (
              <span className="font-mono text-[9px] tracking-[0.06em] text-muted-foreground">
                · {EXECUTION_TEXT[request.execution_status] ?? request.execution_status}
              </span>
            )}
          </div>
          <p className="text-[11px] text-muted-foreground mt-0.5">
            Requested by <span className="text-foreground">{request.ai_employee ?? request.requested_by}</span>
            {request.requested_for && <> in a conversation with <span className="text-foreground">{request.requested_for}</span></>}
            {" · "}
            {new Date(request.created_at.endsWith("Z") || request.created_at.includes("+") ? request.created_at : `${request.created_at}Z`).toLocaleString()}
          </p>
          {request.reason && <p className="mt-0.5 text-[11px] text-muted-foreground">Why approval is needed: {request.reason}</p>}
        </div>
        <button
          onClick={() => setExpanded((e) => !e)}
          className="shrink-0 text-muted-foreground hover:text-foreground"
        >
          {expanded ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
        </button>
      </div>

      {expanded && (
        <div className="border-t border-border/40 pt-2 space-y-1.5">
          {request.parameters && Object.keys(request.parameters).length > 0 ? (
            <dl className="border border-border/30 bg-muted/20 p-2 text-[11px]">
              {Object.entries(request.parameters).map(([k, v]) => (
                <div key={k} className="flex gap-2">
                  <dt className="font-mono text-[10px] text-muted-foreground">{k}:</dt>
                  <dd className="min-w-0 break-words">{typeof v === "string" ? v : JSON.stringify(v)}</dd>
                </div>
              ))}
            </dl>
          ) : (
            <div className="rounded-none border border-border/30 bg-muted/20 p-2 font-mono text-[10px] text-muted-foreground whitespace-pre-wrap break-all">
              {safeDetail}
            </div>
          )}
          {request.execution_error && (
            <p className="text-[11px] text-destructive">Execution result: {request.execution_error}</p>
          )}
          {request.plan_status && (
            <p className="text-[11px] text-muted-foreground">Plan status: {request.plan_status.replace(/_/g, " ")}</p>
          )}
          {request.reviewed_by && (
            <p className="text-[11px] text-muted-foreground">
              Reviewed by <span className="text-foreground">{request.reviewer_name ?? request.reviewed_by}</span>
              {request.review_note && ` — "${request.review_note}"`}
            </p>
          )}
          {request.resolved_at && (
            <p className="text-[11px] text-muted-foreground">
              Resolved: {new Date(request.resolved_at).toLocaleString()}
            </p>
          )}
        </div>
      )}

      {isPending && !canDecide && (
        <p className="pt-1 text-[11px] text-muted-foreground">Waiting for a company administrator to decide. Nothing has been executed.</p>
      )}
      {isPending && canDecide && (
        <div className="flex gap-2 pt-1">
          <button
            onClick={() => onDecide(request.id, "approved")}
            disabled={deciding}
            className="inline-flex items-center gap-1 border border-success/40 px-2 py-0.5 font-mono text-[10px] tracking-[0.08em] text-success hover:bg-success/10 disabled:opacity-50"
          >
            {deciding ? <Loader2 className="size-2.5 animate-spin" /> : <ShieldCheck className="size-2.5" />}
            APPROVE
          </button>
          <button
            onClick={() => onDecide(request.id, "rejected")}
            disabled={deciding}
            className="inline-flex items-center gap-1 border border-destructive/40 px-2 py-0.5 font-mono text-[10px] tracking-[0.08em] text-destructive hover:bg-destructive/10 disabled:opacity-50"
          >
            {deciding ? <Loader2 className="size-2.5 animate-spin" /> : <ShieldOff className="size-2.5" />}
            REJECT
          </button>
        </div>
      )}
    </div>
  );
}

export function ApprovalCenterPanel() {
  const { user } = useSession();
  const canDecide = IS_ADMIN_ROLE(user?.role);
  const [filter, setFilter] = useState<FilterStatus>("all");
  const [decidingId, setDecidingId] = useState<string | null>(null);

  const { data: approvals = [], isLoading } = useApprovalRequests(
    filter === "all" ? undefined : filter
  );
  const { data: plans = [], isLoading: plansLoading } = useExecutionPlans();
  const { data: audits = [], isLoading: auditsLoading } = useActionAudits();
  const resumePlan = useResumePlan();
  const rejectPlan = useRejectPlan();
  const approveAction = useApproveAction();
  const rejectAction = useRejectAction();

  async function handleDecide(approvalId: string, decision: "approved" | "rejected") {
    setDecidingId(approvalId);
    try {
      // Plans own the paused agent run. Resume/reject through the planner so
      // the decision and the plan state remain in sync.
      const plan = plans.find((candidate) =>
        candidate.status === "awaiting_approval" &&
        candidate.steps.some((step) => step.approval_request_id === approvalId),
      );
      if (plan) {
        const result = decision === "approved"
          ? await resumePlan.mutateAsync({ planId: plan.id })
          : await rejectPlan.mutateAsync({ planId: plan.id });
        if (decision === "approved" && result.status === "failed") {
          throw new Error(result.final_message || "The action failed after approval.");
        }
        if (decision === "rejected" && result.status !== "rejected") {
          throw new Error(result.final_message || "The plan could not be rejected.");
        }
        toast.success(decision === "approved"
          ? (result.status === "completed" ? "Action approved and plan resumed." : result.final_message || "Approval processed.")
          : (result.final_message || "Action rejected; plan stopped."));
        return;
      }

      // Standalone governed actions use their audit record to revalidate and
      // execute on approval, or to permanently reject without execution.
      const audit = audits.find((candidate) =>
        candidate.approval_request_id === approvalId && candidate.approval_status === "proposed",
      );
      if (!audit) {
        throw new Error("No pending action record is linked to this approval. Refresh the page and check the action audit.");
      }
      const result = decision === "approved"
        ? await approveAction.mutateAsync({ auditId: audit.id })
        : await rejectAction.mutateAsync({ auditId: audit.id });
      if (result.status !== (decision === "approved" ? "executed" : "rejected")) {
        throw new Error(result.message || `The action was not ${decision}.`);
      }
      toast.success(result.message || (decision === "approved" ? "Action approved and executed." : "Action rejected."));
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not process this approval.");
    } finally {
      setDecidingId(null);
    }
  }

  const pending = approvals.filter((a) => a.status === "pending");

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="font-mono text-[11px] tracking-[0.14em] text-muted-foreground">APPROVAL CENTER</h3>
          <p className="mt-1 text-[13px] text-foreground">
            Review and approve or reject actions requested by AI employees.
          </p>
          {pending.length > 0 && (
            <div className="mt-1 inline-flex items-center gap-1.5 border border-warning/40 px-2 py-0.5">
              <AlertTriangle className="size-3 text-warning" />
              <span className="font-mono text-[10px] tracking-[0.08em] text-warning">
                {pending.length} PENDING
              </span>
            </div>
          )}
        </div>
      </div>

      {/* Filter tabs */}
      <div className="flex gap-1 border-b border-border pb-2">
        {(["all", "pending", "approved", "rejected"] as FilterStatus[]).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={cn(
              "border px-2.5 py-0.5 font-mono text-[10px] tracking-[0.08em] capitalize",
              filter === f
                ? "border-foreground/30 bg-foreground/5 text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground"
            )}
          >
            {f}
          </button>
        ))}
      </div>

      {/* Security notice */}
      <div className="border border-border/40 p-2 text-[11px] text-muted-foreground">
        Parameter details are shown in truncated form. No secrets, tokens, or credentials are displayed.
      </div>

      {/* Approval list */}
      {isLoading ? (
        <div className="flex items-center gap-2 text-[12px] text-muted-foreground py-4">
          <Loader2 className="size-3.5 animate-spin" /> Loading approvals...
        </div>
      ) : approvals.length === 0 ? (
        <div className="border border-border/40 p-4 text-center text-[12px] text-muted-foreground">
          {filter === "pending" ? "No pending approvals." : "No approvals found."}
        </div>
      ) : (
        <div className="space-y-2">
          {approvals.map((a) => (
            <ApprovalCard
              key={a.id}
              request={a}
              onDecide={handleDecide}
              deciding={decidingId === a.id || (a.status === "pending" && (plansLoading || auditsLoading))}
              canDecide={canDecide}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export default ApprovalCenterPanel;
