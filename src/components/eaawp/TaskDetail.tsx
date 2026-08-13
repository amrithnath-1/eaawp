import { X } from "lucide-react";
import { toast } from "sonner";
import { departmentName } from "@/services";
import type { AgentTask } from "@/services/types";
import { cn } from "@/lib/utils";
import { Meter } from "./Panel";

export function TaskDetail({ task, onClose }: { task: AgentTask | null; onClose: () => void }) {
  if (!task) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-background/70" onClick={onClose} />
      <aside className="relative flex h-full w-full max-w-[520px] flex-col border-l border-border bg-surface">
        <header className="flex h-12 shrink-0 items-center justify-between border-b border-border px-4">
          <span className="label-xs text-foreground">Task · Decision timeline</span>
          <button onClick={onClose} aria-label="Close task detail">
            <X className="size-4 text-muted-foreground hover:text-foreground" />
          </button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="border-b border-border p-4">
            <h3 className="text-base font-semibold tracking-tight">{task.name}</h3>
            <p className="mt-1 text-xs text-muted-foreground">{task.goal}</p>
            <div className="mt-3"><Meter value={task.progress} tone={task.status === "completed" ? "success" : "primary"} /></div>
            <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 font-mono text-[10px] text-muted-foreground">
              <span>PROGRESS {task.progress}%</span>
              <span>DEPT {departmentName(task.department).toUpperCase()}</span>
              <span>STARTED {task.startedAt}</span>
            </div>
          </div>

          <div className="p-4">
            <h4 className="label-xs mb-3">AI process</h4>
            <ol className="relative border-l border-border pl-4">
              {task.steps.map((s, i) => (
                <li key={i} className="relative pb-4 last:pb-0">
                  <span
                    className={cn(
                      "absolute -left-[21px] top-1 size-2.5 border",
                      s.state === "done" && "border-success bg-success",
                      s.state === "active" && "border-primary bg-primary pulse-dot",
                      s.state === "pending" && "border-border-strong bg-surface",
                    )}
                  />
                  <div className="text-[13px] font-medium">{s.label}</div>
                  <div className="mt-0.5 text-xs text-muted-foreground">{s.detail}</div>
                </li>
              ))}
            </ol>
          </div>

          <div className="border-t border-border p-4">
            <h4 className="label-xs mb-2">AI response sources</h4>
            <ul className="space-y-1">
              {task.sources.map((s) => (
                <li key={s} className="flex items-center gap-2 font-mono text-[11px] text-foreground">
                  <span className="size-1 bg-primary" /> {s}
                </li>
              ))}
            </ul>
          </div>
        </div>

        <footer className="flex shrink-0 flex-wrap gap-2 border-t border-border p-3">
          {["Approve", "Request changes", "Ask AI", "Export"].map((a) => (
            <button
              key={a}
              onClick={() => toast.success(`${a} — sent to agent orchestrator`)}
              className={cn(
                "border px-3 py-1.5 font-mono text-[10px] tracking-[0.14em]",
                a === "Approve"
                  ? "border-primary text-primary hover:bg-primary/10"
                  : "border-border text-muted-foreground hover:text-foreground",
              )}
            >
              {a.toUpperCase()}
            </button>
          ))}
        </footer>
      </aside>
    </div>
  );
}
