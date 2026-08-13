import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { AppShell } from "@/components/eaawp/AppShell";
import { PageHeader } from "@/components/eaawp/Panel";
import { auditService, departmentName } from "@/services";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/audit")({
  component: AuditPage,
});

const ACTORS = ["All", "AI", "Manager", "Company Admin", "System", "Employee"] as const;

function AuditPage() {
  const rows = auditService.list();
  const [actor, setActor] = useState<(typeof ACTORS)[number]>("All");
  const [q, setQ] = useState("");

  const filtered = useMemo(
    () => rows.filter((r) => (actor === "All" || r.actor === actor) && r.event.toLowerCase().includes(q.toLowerCase())),
    [rows, actor, q],
  );

  return (
    <AppShell>
      <div className="p-4">
        <PageHeader title="Audit / activity" subtitle="Immutable record of what the AI and people did inside this environment." />
        <div className="mt-3 flex flex-wrap items-center gap-1.5">
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Filter events…"
            className="h-8 w-56 border border-input bg-surface px-2 text-xs outline-none focus:border-ring"
          />
          {ACTORS.map((a) => (
            <button
              key={a}
              onClick={() => setActor(a)}
              className={cn(
                "border px-2 py-1 font-mono text-[10px] tracking-[0.1em]",
                actor === a ? "border-primary text-primary" : "border-border text-muted-foreground hover:text-foreground",
              )}
            >
              {a.toUpperCase()}
            </button>
          ))}
        </div>

        <div className="mt-4 border border-border">
          <div className="grid grid-cols-[70px_2fr_1fr_1fr_90px] gap-3 border-b border-border bg-surface-2 px-3 py-2">
            {["Time", "Event", "Actor", "Department", "Status"].map((h) => (
              <span key={h} className="label-xs">{h}</span>
            ))}
          </div>
          {filtered.map((r) => (
            <div key={r.id} className="grid grid-cols-[70px_2fr_1fr_1fr_90px] gap-3 border-b border-border px-3 py-2 last:border-0 hover:bg-surface">
              <span className="font-mono text-[11px] text-muted-foreground">{r.time}</span>
              <span className="text-[13px]">{r.event}</span>
              <span className={cn("font-mono text-[11px]", r.actor === "AI" ? "text-primary" : "text-foreground")}>{r.actor}</span>
              <span className="font-mono text-[11px] text-muted-foreground">{r.department ? departmentName(r.department) : "—"}</span>
              <span
                className={cn(
                  "font-mono text-[10px] tracking-[0.12em]",
                  r.status === "ok" ? "text-success" : r.status === "pending" ? "text-warning" : "text-destructive",
                )}
              >
                {r.status.toUpperCase()}
              </span>
            </div>
          ))}
        </div>
      </div>
    </AppShell>
  );
}
