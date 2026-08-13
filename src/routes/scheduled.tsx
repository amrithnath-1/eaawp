import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { toast } from "sonner";
import { AppShell } from "@/components/eaawp/AppShell";
import { PageHeader } from "@/components/eaawp/Panel";
import { departmentName, scheduleService } from "@/services";
import type { Schedule } from "@/services/types";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/scheduled")({
  head: () => ({
    meta: [
      { title: "Scheduled AI tasks — EAAWP" },
      { name: "description", content: "Recurring work the company AI employee runs automatically: frequency, next execution, owner and status." },
      { property: "og:title", content: "Scheduled AI tasks — EAAWP" },
      { property: "og:description", content: "Recurring agent schedules with owners, next run and controls." },
    ],
  }),
  component: ScheduledPage,
});

function ScheduledPage() {
  const [rows, setRows] = useState<Schedule[]>(() => scheduleService.list());

  return (
    <AppShell>
      <div className="p-4">
        <PageHeader
          title="Scheduled"
          subtitle="Recurring responsibilities executed by the AI without human prompting."
          actions={
            <button
              onClick={() => toast.success("New schedule draft created")}
              className="border border-primary px-3 py-1.5 font-mono text-[10px] tracking-[0.14em] text-primary hover:bg-primary/10"
            >
              CREATE SCHEDULE
            </button>
          }
        />

        <div className="mt-4 border border-border">
          <div className="grid grid-cols-[1.4fr_1fr_1fr_0.8fr_0.9fr_auto] gap-3 border-b border-border bg-surface-2 px-3 py-2">
            {["Task", "Frequency", "Next execution", "Status", "Owner", ""].map((h) => (
              <span key={h} className="label-xs">{h}</span>
            ))}
          </div>
          {rows.map((s) => (
            <div key={s.id} className="grid grid-cols-[1.4fr_1fr_1fr_0.8fr_0.9fr_auto] items-center gap-3 border-b border-border px-3 py-2.5 last:border-0 hover:bg-surface">
              <div>
                <div className="text-[13px] font-medium">{s.task}</div>
                <div className="label-xs mt-0.5">{departmentName(s.department)}</div>
              </div>
              <span className="font-mono text-[11px] text-muted-foreground">{s.frequency}</span>
              <span className="font-mono text-[11px] text-muted-foreground">{s.nextRun}</span>
              <span className={cn("font-mono text-[10px] tracking-[0.12em]", s.status === "active" ? "text-success" : "text-muted-foreground")}>
                {s.status.toUpperCase()}
              </span>
              <span className="font-mono text-[11px] text-muted-foreground">{s.owner}</span>
              <div className="flex gap-1.5">
                <button
                  onClick={() =>
                    setRows((r) => r.map((x) => (x.id === s.id ? { ...x, status: x.status === "active" ? "paused" : "active" } : x)))
                  }
                  className="border border-border px-2 py-1 font-mono text-[10px] text-muted-foreground hover:text-foreground"
                >
                  {s.status === "active" ? "DISABLE" : "ENABLE"}
                </button>
                <button
                  onClick={() => toast("Schedule editor — connect scheduling service")}
                  className="border border-border px-2 py-1 font-mono text-[10px] text-muted-foreground hover:text-foreground"
                >
                  EDIT
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </AppShell>
  );
}
