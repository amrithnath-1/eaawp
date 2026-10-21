/**
 * EmployeeDetailPanel - what an AI employee is configured to do, plain-language changes with
 * approval, version history with rollback, and pause/resume. All state lives on the server.
 */
import { useState } from "react";
import { toast } from "sonner";
import { Loader2, Pause, Play, RotateCcw, Check, X, Wand2 } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  useEmployeeDetail, useReviseEmployee, useEmployeeVersionAction, usePauseEmployee,
  type EmployeeVersionFE,
} from "@/hooks/use-api";

const FIELD_LABEL: Record<string, string> = {
  name: "Name", purpose: "Purpose", responsibilities: "Responsibilities", objectives: "Objectives",
  system_persona: "Instructions to the agent", communication_style: "Tone", llm_model: "Model",
  allowed_tools: "Tools it may use freely", guarded_tools: "Tools that need approval each time",
};

function show(v: unknown): string {
  if (Array.isArray(v)) return v.length ? v.join(", ") : "none";
  return v === null || v === undefined || v === "" ? "none" : String(v);
}

function VersionBadge({ status }: { status: EmployeeVersionFE["status"] }) {
  const cls = {
    current: "text-success border-success/40", proposed: "text-warning border-warning/40",
    superseded: "text-muted-foreground border-muted-foreground/40", rejected: "text-destructive border-destructive/40",
  }[status];
  return <span className={cn("border px-1.5 py-0.5 font-mono text-[9px] tracking-[0.06em]", cls)}>{status.toUpperCase()}</span>;
}

export function EmployeeDetailPanel({ employeeId }: { employeeId: string }) {
  const q = useEmployeeDetail(employeeId, true);
  const revise = useReviseEmployee(employeeId);
  const act = useEmployeeVersionAction(employeeId);
  const pause = usePauseEmployee(employeeId);
  const [text, setText] = useState("");

  if (q.isLoading) return <p className="p-3 font-mono text-[11px] text-muted-foreground">Loading…</p>;
  if (q.isError || !q.data) return <p className="p-3 text-[12px] text-destructive">Could not load this employee.</p>;
  const d = q.data;
  const proposal = d.versions.find((v) => v.status === "proposed");
  const paused = d.status === "PAUSED";
  const busy = act.isPending || pause.isPending;
  const run = (p: Promise<unknown>, ok: string) => p.then(() => toast.success(ok)).catch((e: Error) => toast.error(e.message));

  return (
    <div className="space-y-3 border-t border-border/60 p-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-[12px] text-muted-foreground">
          Version {d.current_version ?? "—"} in use{paused ? " · paused: it cannot be asked to work or be delegated to" : ""}
        </p>
        <button disabled={busy} onClick={() => void run(pause.mutateAsync(!paused), paused ? "Employee resumed" : "Employee paused")}
          className="inline-flex items-center gap-1 border border-border px-2 py-1 font-mono text-[10px] hover:border-foreground disabled:opacity-40">
          {paused ? <Play className="size-3" /> : <Pause className="size-3" />} {paused ? "RESUME" : "PAUSE"}
        </button>
      </div>

      {d.config && (
        <dl className="grid grid-cols-1 gap-x-4 gap-y-1 text-[12px] sm:grid-cols-[170px_1fr]">
          {(["purpose", "communication_style", "llm_model", "allowed_tools", "guarded_tools", "responsibilities"] as const).map((k) => (
            <div key={k} className="contents">
              <dt className="text-muted-foreground">{FIELD_LABEL[k]}</dt>
              <dd className="break-words">{show(d.config![k])}</dd>
            </div>
          ))}
        </dl>
      )}

      <div className="space-y-2 border border-border bg-surface p-2.5">
        <p className="label-xs">CHANGE THIS EMPLOYEE IN PLAIN LANGUAGE</p>
        <div className="flex gap-2">
          <input value={text} onChange={(e) => setText(e.target.value)} placeholder="e.g. Make the tone formal and let it draft emails"
            className="flex-1 border border-input bg-background px-2 py-1.5 text-[12px] outline-none focus:border-ring" />
          <button disabled={revise.isPending || text.trim().length < 3}
            onClick={() => void run(revise.mutateAsync(text.trim()).then(() => setText("")), "Change proposed — review it below")}
            className="inline-flex items-center gap-1 border border-foreground/20 bg-foreground/5 px-2 py-1 font-mono text-[10px] disabled:opacity-40">
            {revise.isPending ? <Loader2 className="size-3 animate-spin" /> : <Wand2 className="size-3" />} PROPOSE
          </button>
        </div>
        <p className="text-[11px] text-muted-foreground">Nothing changes until you approve it. Risky actions (sending, creating, updating) always keep needing approval.</p>
      </div>

      {proposal && (
        <div className="space-y-2 border border-warning/40 bg-warning/5 p-2.5">
          <p className="font-mono text-[10px] tracking-[0.1em] text-warning">PROPOSED CHANGE · VERSION {proposal.version}</p>
          {proposal.instruction && <p className="text-[12px]">“{proposal.instruction}”</p>}
          <ul className="space-y-1 text-[12px]">
            {d.versions.length > 0 && proposal.changes.length === 0 && <li className="text-muted-foreground">{proposal.change_summary}</li>}
            {proposal.changes.map((c) => (
              <li key={c.field}><span className="text-muted-foreground">{FIELD_LABEL[c.field] ?? c.field}:</span>{" "}
                <span className="line-through opacity-60">{show(c.before)}</span> → <span>{show(c.after)}</span></li>
            ))}
          </ul>
          {proposal.warnings.map((w) => <p key={w} className="text-[11px] text-warning">{w}</p>)}
          <div className="flex gap-2">
            <button disabled={busy} onClick={() => void run(act.mutateAsync({ number: proposal.version, verb: "approve" }), `Version ${proposal.version} is now in use`)}
              className="inline-flex items-center gap-1 border border-success/40 px-2 py-1 font-mono text-[10px] text-success disabled:opacity-40"><Check className="size-3" /> APPROVE</button>
            <button disabled={busy} onClick={() => void run(act.mutateAsync({ number: proposal.version, verb: "reject" }), "Change rejected")}
              className="inline-flex items-center gap-1 border border-destructive/40 px-2 py-1 font-mono text-[10px] text-destructive disabled:opacity-40"><X className="size-3" /> REJECT</button>
          </div>
        </div>
      )}

      <div>
        <p className="label-xs mb-1">VERSION HISTORY</p>
        <ul className="space-y-1">
          {d.versions.map((v) => (
            <li key={v.id} className="flex items-center gap-2 border border-border/60 px-2 py-1 text-[11px]">
              <span className="font-mono">v{v.version}</span><VersionBadge status={v.status} />
              <span className="min-w-0 flex-1 truncate text-muted-foreground" title={v.change_summary}>{v.change_summary}</span>
              <span className="hidden font-mono text-[9px] text-muted-foreground sm:inline">{new Date(v.created_at).toLocaleDateString()}</span>
              {v.status === "superseded" && (
                <button disabled={busy} onClick={() => void run(act.mutateAsync({ number: v.version, verb: "rollback" }), `Restored version ${v.version}`)}
                  className="inline-flex items-center gap-1 border border-border px-1.5 py-0.5 font-mono text-[9px] hover:border-foreground disabled:opacity-40">
                  <RotateCcw className="size-3" /> RESTORE
                </button>
              )}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
