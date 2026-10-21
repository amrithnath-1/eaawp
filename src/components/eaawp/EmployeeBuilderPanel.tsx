/**
 * EmployeeBuilderPanel — Dynamic AI Employee Builder
 *
 * Lets an administrator create a new AI employee using natural language.
 * "Create a competitor analysis AI employee."
 *
 * Flow:
 *   1. User describes the employee they want.
 *   2. LLM generates a blueprint proposal (backend).
 *   3. Blueprint shows: name, purpose, required capabilities,
 *      MISSING integrations that must be connected first.
 *   4. Human reviews and approves or rejects.
 *   5. On approval → AIEmployee record created, employee goes ACTIVE.
 *
 * Security:
 * - LLM cannot set credentials, tenant_id, or bypass governance.
 * - Blueprint must be approved before employee is activated.
 * - Approval goes through the backend — frontend cannot self-approve.
 */
import { useState } from "react";
import { toast } from "sonner";
import {
  Plus, Loader2, CheckCircle, XCircle, AlertTriangle,
  ChevronDown, ChevronRight, ShieldCheck, ShieldOff,
  User, Zap, Globe, Clock,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { EmployeeDetailPanel } from "@/components/eaawp/EmployeeDetailPanel";
import {
  useBuildEmployee,
  useEmployeeBlueprints,
  useApproveBlueprint,
  useRejectBlueprint,
  useEmployees,
  type EmployeeBlueprintProposal,
  type EmployeeOut,
} from "@/hooks/use-api";

// ── Status badge ──────────────────────────────────────────────────────────────
function ApprovalBadge({ status }: { status: string }) {
  const cfg = {
    pending:  { cls: "text-warning border-warning/40",  label: "PENDING APPROVAL" },
    approved: { cls: "text-success border-success/40",  label: "APPROVED" },
    rejected: { cls: "text-destructive border-destructive/40", label: "REJECTED" },
  }[status] ?? { cls: "text-muted-foreground border-muted-foreground/40", label: status.toUpperCase() };

  return (
    <span className={cn("inline-flex items-center gap-1 border px-1.5 py-0.5 font-mono text-[10px] tracking-[0.08em]", cfg.cls)}>
      {cfg.label}
    </span>
  );
}

// ── Blueprint card ────────────────────────────────────────────────────────────
function BlueprintCard({
  blueprint,
  onApprove,
  onReject,
}: {
  blueprint: EmployeeBlueprintProposal;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="border border-border bg-surface p-3 space-y-2">
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-mono text-[11px] tracking-[0.06em]">{blueprint.name}</span>
            <ApprovalBadge status={blueprint.approval_status} />
          </div>
          <p className="mt-0.5 text-[11px] text-muted-foreground">{blueprint.purpose}</p>
        </div>
        <button
          onClick={() => setExpanded((e) => !e)}
          className="shrink-0 text-muted-foreground hover:text-foreground"
        >
          {expanded ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
        </button>
      </div>

      {/* Missing integrations warning */}
      {blueprint.missing_integrations.length > 0 && (
        <div className="border border-warning/30 bg-warning/5 p-2 space-y-0.5">
          <div className="flex items-center gap-1 font-mono text-[10px] tracking-[0.08em] text-warning">
            <AlertTriangle className="size-3" /> MISSING INTEGRATIONS
          </div>
          {blueprint.missing_integrations.map((mi) => (
            <div key={mi.provider_type} className="text-[11px] text-muted-foreground">
              • <span className="text-foreground">{mi.display_name}</span> — {mi.reason}
            </div>
          ))}
        </div>
      )}

      {/* Expanded details */}
      {expanded && (
        <div className="space-y-2 pt-1 border-t border-border/50">
          {blueprint.responsibilities.length > 0 && (
            <div>
              <p className="font-mono text-[9px] tracking-[0.1em] text-muted-foreground mb-1">RESPONSIBILITIES</p>
              {blueprint.responsibilities.map((r, i) => (
                <div key={i} className="text-[11px] text-muted-foreground">• {r}</div>
              ))}
            </div>
          )}
          {blueprint.required_capabilities.length > 0 && (
            <div>
              <p className="font-mono text-[9px] tracking-[0.1em] text-muted-foreground mb-1">REQUIRED CAPABILITIES</p>
              {blueprint.required_capabilities.map((rc, i) => (
                <div key={i} className="flex items-center gap-1.5 text-[11px]">
                  {rc.is_available ? (
                    <CheckCircle className="size-2.5 text-success shrink-0" />
                  ) : (
                    <XCircle className="size-2.5 text-destructive shrink-0" />
                  )}
                  <span className="text-muted-foreground">{rc.provider_type}</span>
                  <span className="text-muted-foreground/60">›</span>
                  <span>{rc.capability_key}</span>
                </div>
              ))}
            </div>
          )}
          <div className="flex gap-2 flex-wrap text-[11px] text-muted-foreground">
            <span>Tools: {blueprint.allowed_tools.length}</span>
            <span>Model: {blueprint.llm_model}</span>
            <span>Style: {blueprint.communication_style}</span>
            {blueprint.suggested_schedule && <span>Schedule: {blueprint.suggested_schedule}</span>}
          </div>
        </div>
      )}

      {/* Approve / Reject */}
      {blueprint.approval_status === "pending" && (
        <div className="flex gap-2 pt-1">
          <button
            onClick={() => onApprove(blueprint.id)}
            className="inline-flex items-center gap-1 border border-success/40 px-2 py-0.5 font-mono text-[10px] tracking-[0.08em] text-success hover:bg-success/10"
          >
            <ShieldCheck className="size-2.5" /> APPROVE & ACTIVATE
          </button>
          <button
            onClick={() => onReject(blueprint.id)}
            className="inline-flex items-center gap-1 border border-destructive/40 px-2 py-0.5 font-mono text-[10px] tracking-[0.08em] text-destructive hover:bg-destructive/10"
          >
            <ShieldOff className="size-2.5" /> REJECT
          </button>
        </div>
      )}
    </div>
  );
}

// ── Active employees list ─────────────────────────────────────────────────────
function EmployeeCard({ employee }: { employee: EmployeeOut }) {
  const [open, setOpen] = useState(false);
  const statusColor =
    employee.status === "ACTIVE" ? "text-success border-success/40" :
    employee.status === "PAUSED" ? "text-warning border-warning/40" :
    "text-muted-foreground border-muted-foreground/40";

  return (
    <div className="border border-border bg-surface">
      <button onClick={() => setOpen((o) => !o)} aria-expanded={open} className="flex w-full items-center gap-3 p-2.5 text-left">
        <User className="size-4 text-muted-foreground shrink-0" />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-mono text-[11px] tracking-[0.06em]">{employee.name}</span>
            <span className={cn("border px-1.5 py-0.5 font-mono text-[9px] tracking-[0.06em]", statusColor)}>
              {employee.status}
            </span>
          </div>
          <p className="text-[11px] text-muted-foreground">{employee.role_key}</p>
        </div>
        {open ? <ChevronDown className="size-3.5 text-muted-foreground" /> : <ChevronRight className="size-3.5 text-muted-foreground" />}
      </button>
      {open && <EmployeeDetailPanel employeeId={employee.id} />}
    </div>
  );
}

// ── Main panel ────────────────────────────────────────────────────────────────
export function EmployeeBuilderPanel() {
  const [instruction, setInstruction] = useState("");
  const { data: blueprints = [], isLoading: loadingBlueprints } = useEmployeeBlueprints();
  const { data: employees = [], isLoading: loadingEmployees } = useEmployees();
  const buildMutation = useBuildEmployee();
  const approveMutation = useApproveBlueprint();
  const rejectMutation = useRejectBlueprint();

  async function handleBuild() {
    if (!instruction.trim()) return;
    buildMutation.mutate(
      { instruction: instruction.trim(), requested_by: "admin" },
      {
        onSuccess: () => {
          toast.success("Blueprint proposal created — review below.");
          setInstruction("");
        },
        onError: (e) => toast.error(e.message),
      }
    );
  }

  function handleApprove(id: string) {
    approveMutation.mutate(
      { proposal_id: id, reviewed_by: "admin" },
      {
        onSuccess: (emp) => toast.success(`${emp.name} is now ACTIVE.`),
        onError: (e) => toast.error(e.message),
      }
    );
  }

  function handleReject(id: string) {
    rejectMutation.mutate(
      { proposal_id: id, reviewed_by: "admin", review_note: "Rejected via admin panel" },
      {
        onSuccess: () => toast.success("Blueprint rejected."),
        onError: (e) => toast.error(e.message),
      }
    );
  }

  const pendingBlueprints = blueprints.filter((b) => b.approval_status === "pending");
  const pastBlueprints = blueprints.filter((b) => b.approval_status !== "pending");

  return (
    <div className="space-y-4">
      {/* Header */}
      <div>
        <h3 className="font-mono text-[11px] tracking-[0.14em] text-muted-foreground">AI EMPLOYEE BUILDER</h3>
        <p className="mt-1 text-[13px] text-foreground">
          Describe the AI employee you want to create. The system will analyse requirements,
          identify needed integrations, and generate a blueprint for your approval.
        </p>
      </div>

      {/* Create form */}
      <div className="border border-border bg-surface p-3 space-y-3">
        <p className="font-mono text-[10px] tracking-[0.14em] text-muted-foreground">DESCRIBE NEW EMPLOYEE</p>
        <textarea
          value={instruction}
          onChange={(e) => setInstruction(e.target.value)}
          placeholder={
            "e.g. Create a competitor analysis AI employee that monitors our competitors' " +
            "websites, tracks their content and marketing, and prepares weekly reports."
          }
          rows={4}
          className="w-full border border-input bg-background px-2 py-1.5 text-[12px] outline-none focus:border-ring resize-none"
          disabled={buildMutation.isPending}
        />
        <button
          onClick={() => void handleBuild()}
          disabled={buildMutation.isPending || !instruction.trim()}
          className="inline-flex items-center gap-2 border border-foreground/20 bg-foreground/5 px-3 py-1.5 font-mono text-[11px] tracking-[0.08em] hover:bg-foreground/10 disabled:opacity-50"
        >
          {buildMutation.isPending ? (
            <Loader2 className="size-3.5 animate-spin" />
          ) : (
            <Zap className="size-3.5" />
          )}
          GENERATE BLUEPRINT
        </button>
      </div>

      {/* Active employees */}
      {employees.length > 0 && (
        <div className="space-y-2">
          <p className="font-mono text-[10px] tracking-[0.14em] text-muted-foreground">
            ACTIVE EMPLOYEES ({employees.length})
          </p>
          {employees.map((e) => <EmployeeCard key={e.id} employee={e} />)}
        </div>
      )}

      {/* Pending blueprints */}
      {pendingBlueprints.length > 0 && (
        <div className="space-y-2">
          <p className="font-mono text-[10px] tracking-[0.14em] text-muted-foreground">
            AWAITING APPROVAL ({pendingBlueprints.length})
          </p>
          {pendingBlueprints.map((b) => (
            <BlueprintCard
              key={b.id}
              blueprint={b}
              onApprove={handleApprove}
              onReject={handleReject}
            />
          ))}
        </div>
      )}

      {/* Past blueprints */}
      {pastBlueprints.length > 0 && (
        <div className="space-y-2">
          <p className="font-mono text-[10px] tracking-[0.14em] text-muted-foreground">
            PAST PROPOSALS ({pastBlueprints.length})
          </p>
          {pastBlueprints.map((b) => (
            <BlueprintCard
              key={b.id}
              blueprint={b}
              onApprove={handleApprove}
              onReject={handleReject}
            />
          ))}
        </div>
      )}

      {loadingBlueprints && (
        <div className="flex items-center gap-2 text-[12px] text-muted-foreground">
          <Loader2 className="size-3.5 animate-spin" /> Loading blueprints...
        </div>
      )}

      {!loadingBlueprints && blueprints.length === 0 && employees.length === 0 && (
        <div className="border border-border/40 p-3 text-center text-[12px] text-muted-foreground">
          No employees or blueprints yet. Describe an employee above to get started.
        </div>
      )}
    </div>
  );
}

export default EmployeeBuilderPanel;
