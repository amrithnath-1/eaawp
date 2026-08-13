import { useEffect, useState } from "react";
import { departmentName, taskService } from "@/services";
import type { AgentTask } from "@/services/types";
import { Meter } from "./Panel";
import { TaskDetail } from "./TaskDetail";
import { cn } from "@/lib/utils";

const STATUS_LABEL: Record<AgentTask["status"], string> = {
  running: "RUNNING",
  awaiting_approval: "NEEDS APPROVAL",
  completed: "COMPLETED",
  blocked: "BLOCKED",
};

export function ActiveTasks() {
  const [tasks, setTasks] = useState<AgentTask[]>(() => taskService.list());
  const [openId, setOpenId] = useState<string | null>(null);

  useEffect(() => {
    const id = setInterval(() => {
      setTasks((prev) =>
        prev.map((t) =>
          t.status === "running" ? { ...t, progress: Math.min(99, t.progress + Math.round(Math.random() * 2)) } : t,
        ),
      );
    }, 4000);
    return () => clearInterval(id);
  }, []);

  const open = tasks.find((t) => t.id === openId) ?? null;

  return (
    <>
      <ul className="h-full overflow-y-auto">
        {tasks.map((t) => (
          <li key={t.id} className="border-b border-border last:border-0">
            <button onClick={() => setOpenId(t.id)} className="w-full px-3 py-2.5 text-left hover:bg-surface-2">
              <div className="flex items-baseline justify-between gap-2">
                <span className="truncate text-[13px] font-medium">{t.name}</span>
                <span className="font-mono text-[10px] text-muted-foreground">{t.progress}%</span>
              </div>
              <div className="mt-1.5">
                <Meter value={t.progress} />
              </div>
              <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[10px] text-muted-foreground">
                <span className={cn(t.status !== "completed" && "text-foreground")}>{STATUS_LABEL[t.status]}</span>
                <span>{departmentName(t.department)}</span>
                <span>START {t.startedAt}</span>
                {t.requiredAction && <span className="text-foreground">ACTION: {t.requiredAction}</span>}
              </div>
            </button>
          </li>
        ))}
      </ul>
      <TaskDetail task={open} onClose={() => setOpenId(null)} />
    </>
  );
}
