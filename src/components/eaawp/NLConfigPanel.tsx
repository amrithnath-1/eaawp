/**
 * NLConfigPanel — Natural-Language Role Configuration
 *
 * Lets a Company Administrator type a plain-English instruction to configure
 * the Digital Marketing Manager role. The system interprets the instruction,
 * generates a structured proposal, and requires explicit approval before any
 * configuration change is persisted.
 *
 * Security: the AI never modifies configuration autonomously.
 * All changes go through: interpret → show proposal → require approval → apply.
 */
import { useRef, useState } from "react";
import { SendHorizonal, Check, X, AlertTriangle, Info, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import {
  useNLConfigure,
  useApproveProposal,
  useRejectProposal,
  type ConfigProposal,
  type ProposedChangeLine,
} from "@/hooks/use-api";
import { USE_REAL_API } from "@/lib/api-client";

// ── Sub-components ────────────────────────────────────────────────────────────

function ChangeLineRow({ line }: { line: ProposedChangeLine }) {
  const color =
    line.action === "add"
      ? "text-success"
      : line.action === "remove"
        ? "text-destructive"
        : "text-warning";
  return (
    <div className="flex items-start gap-2 border-b border-border py-1.5 last:border-0">
      <span className="label-xs mt-0.5 w-28 shrink-0 text-muted-foreground">{line.section}</span>
      <span className={cn("text-[13px] leading-snug", color)}>{line.description}</span>
    </div>
  );
}

interface ProposalCardProps {
  proposal: ConfigProposal;
  onApprove: () => void;
  onReject: () => void;
  approving: boolean;
  rejecting: boolean;
}

function ProposalCard({ proposal, onApprove, onReject, approving, rejecting }: ProposalCardProps) {
  const isSettled = proposal.approval_status !== "pending";
  const hasErrors = proposal.validation_errors.length > 0;

  return (
    <div
      className={cn(
        "border bg-surface",
        isSettled && proposal.approval_status === "approved" && "border-success/40",
        isSettled && proposal.approval_status === "rejected" && "border-border opacity-60",
        !isSettled && hasErrors && "border-destructive/40",
        !isSettled && !hasErrors && "border-primary/40",
      )}
    >
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border px-3 py-2">
        <div className="flex items-center gap-2">
          <span className="font-mono text-[10px] tracking-[0.14em] text-muted-foreground">
            PROPOSED CHANGE
          </span>
          {isSettled && (
            <span
              className={cn(
                "font-mono text-[10px] tracking-[0.1em]",
                proposal.approval_status === "approved" ? "text-success" : "text-muted-foreground",
              )}
            >
              · {proposal.approval_status.toUpperCase()}
            </span>
          )}
        </div>
        <span className="font-mono text-[10px] text-muted-foreground">
          {new Date(proposal.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
        </span>
      </div>

      {/* Interpreted intent */}
      <div className="border-b border-border px-3 py-2">
        <p className="text-[11px] text-muted-foreground">Interpreted as:</p>
        <p className="mt-0.5 text-[13px] leading-snug">{proposal.interpreted_intent}</p>
      </div>

      {/* Proposed changes */}
      {proposal.proposed_changes.length > 0 && (
        <div className="border-b border-border px-3 py-1">
          {proposal.proposed_changes.map((line, i) => (
            <ChangeLineRow key={i} line={line} />
          ))}
        </div>
      )}

      {/* Validation errors */}
      {hasErrors && (
        <div className="border-b border-border bg-destructive/5 px-3 py-2">
          {proposal.validation_errors.map((e, i) => (
            <div key={i} className="flex items-start gap-1.5">
              <AlertTriangle className="mt-0.5 size-3 shrink-0 text-destructive" />
              <p className="text-[12px] text-destructive">{e}</p>
            </div>
          ))}
        </div>
      )}

      {/* Warnings */}
      {proposal.validation_warnings.length > 0 && (
        <div className="border-b border-border bg-warning/5 px-3 py-2">
          {proposal.validation_warnings.map((w, i) => (
            <div key={i} className="flex items-start gap-1.5">
              <Info className="mt-0.5 size-3 shrink-0 text-warning" />
              <p className="text-[12px] text-warning">{w}</p>
            </div>
          ))}
        </div>
      )}

      {/* Actions — only shown when pending and no errors */}
      {!isSettled && !hasErrors && (
        <div className="flex items-center gap-2 px-3 py-2">
          <button
            onClick={onApprove}
            disabled={approving || rejecting}
            className="flex items-center gap-1.5 border border-success/60 bg-success/10 px-3 py-1.5 font-mono text-[10px] tracking-[0.12em] text-success hover:bg-success/20 disabled:opacity-40"
          >
            {approving ? <RefreshCw className="size-3 animate-spin" /> : <Check className="size-3" />}
            APPROVE
          </button>
          <button
            onClick={onReject}
            disabled={approving || rejecting}
            className="flex items-center gap-1.5 border border-border px-3 py-1.5 font-mono text-[10px] tracking-[0.12em] text-muted-foreground hover:border-destructive hover:text-destructive disabled:opacity-40"
          >
            {rejecting ? <RefreshCw className="size-3 animate-spin" /> : <X className="size-3" />}
            REJECT
          </button>
          <p className="ml-auto text-[11px] text-muted-foreground">
            Approve to apply · Reject to discard
          </p>
        </div>
      )}

      {/* Settled state */}
      {isSettled && proposal.approval_status === "approved" && (
        <div className="px-3 py-2 text-[12px] text-success">
          ✓ Configuration updated by {proposal.approved_by ?? "admin"}
        </div>
      )}
      {isSettled && proposal.approval_status === "rejected" && (
        <div className="px-3 py-2 text-[12px] text-muted-foreground">
          Rejected — configuration unchanged
        </div>
      )}
    </div>
  );
}

// ── Example instructions shown as placeholder hints ───────────────────────────
const EXAMPLE_INSTRUCTIONS = [
  "You are responsible for monitoring our digital marketing campaigns.",
  "Every Monday at 9 AM, analyse our marketing performance.",
  "Monitor conversion rate and alert me if it drops significantly.",
  "Focus on social media campaign performance.",
  "Do not send anything externally without my approval.",
];

// ── Main panel ────────────────────────────────────────────────────────────────

interface NLConfigPanelProps {
  roleKey?: string;
  className?: string;
}

export function NLConfigPanel({ roleKey = "DIGITAL_MARKETING_MANAGER", className }: NLConfigPanelProps) {
  const [instruction, setInstruction] = useState("");
  const [proposals, setProposals] = useState<ConfigProposal[]>([]);
  const [approvedIds, setApprovedIds] = useState<Set<string>>(new Set());
  const [rejectedIds, setRejectedIds] = useState<Set<string>>(new Set());
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const nlConfigure = useNLConfigure(roleKey);
  const approveProposal = useApproveProposal(roleKey);
  const rejectProposal = useRejectProposal(roleKey);

  const [exampleIdx, setExampleIdx] = useState(0);
  const placeholder = EXAMPLE_INSTRUCTIONS[exampleIdx % EXAMPLE_INSTRUCTIONS.length] ?? "";

  async function submit() {
    const trimmed = instruction.trim();
    if (!trimmed || nlConfigure.isPending) return;
    setInstruction("");
    setExampleIdx((i) => i + 1);

    nlConfigure.mutate(
      { instruction: trimmed },
      {
        onSuccess: (proposal) => {
          setProposals((prev) => [proposal, ...prev]);
        },
        onError: (err) => {
          toast.error(err.message || "Failed to interpret instruction. Try again.");
        },
      },
    );
  }

  function handleApprove(proposalId: string) {
    setApprovedIds((s) => new Set(s).add(proposalId));
    approveProposal.mutate(
      { proposalId },
      {
        onSuccess: (updated) => {
          setProposals((prev) =>
            prev.map((p) => (p.id === proposalId ? updated : p)),
          );
          toast.success("Configuration updated successfully.");
        },
        onError: (err) => {
          setApprovedIds((s) => { const n = new Set(s); n.delete(proposalId); return n; });
          toast.error(err.message || "Approval failed.");
        },
      },
    );
  }

  function handleReject(proposalId: string) {
    setRejectedIds((s) => new Set(s).add(proposalId));
    rejectProposal.mutate(
      { proposalId },
      {
        onSuccess: (updated) => {
          setProposals((prev) =>
            prev.map((p) => (p.id === proposalId ? updated : p)),
          );
        },
        onError: () => {
          setRejectedIds((s) => { const n = new Set(s); n.delete(proposalId); return n; });
        },
      },
    );
  }

  return (
    <div className={cn("flex flex-col gap-3", className)}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <p className="text-[13px] font-semibold tracking-tight">
            Natural-Language Configuration
          </p>
          <p className="label-xs mt-0.5 text-muted-foreground">
            Describe a change in plain English. The system will propose structured changes for your approval.
          </p>
        </div>
        {!USE_REAL_API && (
          <span className="font-mono text-[9px] tracking-[0.1em] text-warning">MOCK MODE</span>
        )}
      </div>

      {/* Input */}
      <div className="border border-border bg-background focus-within:border-ring">
        <textarea
          ref={textareaRef}
          value={instruction}
          onChange={(e) => setInstruction(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void submit();
            }
          }}
          rows={3}
          placeholder={`e.g. "${placeholder}"`}
          disabled={nlConfigure.isPending}
          className="w-full resize-none bg-transparent p-3 text-[13px] outline-none placeholder:text-muted-foreground disabled:opacity-50"
        />
        <div className="flex items-center justify-between border-t border-border px-3 py-2">
          <p className="text-[11px] text-muted-foreground">
            Shift+Enter for new line · Enter to submit
          </p>
          <button
            onClick={() => void submit()}
            disabled={nlConfigure.isPending || !instruction.trim()}
            className={cn(
              "flex items-center gap-1.5 border px-3 py-1.5 font-mono text-[10px] tracking-[0.12em]",
              instruction.trim() && !nlConfigure.isPending
                ? "border-primary text-primary hover:bg-primary/10"
                : "border-border text-muted-foreground opacity-40",
            )}
          >
            {nlConfigure.isPending
              ? <><RefreshCw className="size-3 animate-spin" /> INTERPRETING…</>
              : <><SendHorizonal className="size-3" /> INTERPRET</>
            }
          </button>
        </div>
      </div>

      {/* Proposals */}
      {proposals.length > 0 && (
        <div className="space-y-3">
          {proposals.map((proposal) => (
            <ProposalCard
              key={proposal.id}
              proposal={proposal}
              onApprove={() => handleApprove(proposal.id)}
              onReject={() => handleReject(proposal.id)}
              approving={approvedIds.has(proposal.id) && approveProposal.isPending}
              rejecting={rejectedIds.has(proposal.id) && rejectProposal.isPending}
            />
          ))}
        </div>
      )}

      {proposals.length === 0 && !nlConfigure.isPending && (
        <div className="border border-dashed border-border p-4 text-center">
          <p className="text-[12px] text-muted-foreground">
            No proposals yet. Type an instruction above to get started.
          </p>
          <div className="mt-2 flex flex-wrap justify-center gap-1.5">
            {EXAMPLE_INSTRUCTIONS.slice(0, 3).map((ex) => (
              <button
                key={ex}
                onClick={() => setInstruction(ex)}
                className="border border-border px-2 py-1 text-[11px] text-muted-foreground hover:border-primary hover:text-foreground"
              >
                {ex.slice(0, 50)}{ex.length > 50 ? "…" : ""}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
