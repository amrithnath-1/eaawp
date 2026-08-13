import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { AppShell } from "@/components/eaawp/AppShell";
import { AgentOrganism } from "@/components/eaawp/AgentOrganism";
import { Panel } from "@/components/eaawp/Panel";
import { departmentName, departmentService } from "@/services";
import { departments } from "@/services/mockData";
import type { DepartmentExchange, DepartmentKey } from "@/services/types";
import { cn } from "@/lib/utils";
import { useAgentStatus } from "@/state/useAgentStatus";

export const Route = createFileRoute("/meeting")({
  head: () => ({
    meta: [
      { title: "Meeting Room — company AI network | EAAWP" },
      {
        name: "description",
        content:
          "Observe how the single company AI employee communicates with Finance, Sales, Customer Service, HR and other internal systems in real time.",
      },
      { property: "og:title", content: "Meeting Room — company AI network | EAAWP" },
      { property: "og:description", content: "Live view of AI-to-department system interactions." },
    ],
  }),
  component: MeetingRoom,
});

function MeetingRoom() {
  const { status } = useAgentStatus();
  const [dept, setDept] = useState<DepartmentKey>("finance");
  const [live, setLive] = useState(true);
  const [feed, setFeed] = useState<DepartmentExchange[]>([]);

  useEffect(() => {
    if (!live) return;
    const script = departmentService.liveScript();
    let i = 0;
    setFeed([]);
    const id = setInterval(() => {
      const item = script[i % script.length]!;
      i += 1;
      setFeed((f) => [...f.slice(-14), { ...item, id: `${item.id}-${Date.now()}` }]);
    }, 2200);
    return () => clearInterval(id);
  }, [live]);

  const history = departmentService.forDepartment(dept);

  return (
    <AppShell>
      <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_380px]">
        <div className="grid-canvas relative border-b border-border lg:border-b-0 lg:border-r">
          <div className="flex items-center justify-between px-4 pt-3">
            <div>
              <h1 className="text-base font-semibold tracking-tight">Company agent network</h1>
              <p className="label-xs mt-1">One AI employee · {departments.length} system endpoints</p>
            </div>
            <button
              onClick={() => setLive((l) => !l)}
              className={cn(
                "border px-2.5 py-1 font-mono text-[10px] tracking-[0.14em]",
                live ? "border-primary text-primary" : "border-border text-muted-foreground",
              )}
            >
              {live ? "LIVE MODE ON" : "LIVE MODE OFF"}
            </button>
          </div>
          <AgentOrganism
            status={live ? "COMMUNICATING" : status}
            withNetwork
            activeDepartment={dept}
            onSelectDepartment={setDept}
            height={420}
          />
          <div className="flex flex-wrap gap-1.5 px-4 pb-4">
            {departments.map((d) => (
              <button
                key={d.key}
                onClick={() => setDept(d.key)}
                className={cn(
                  "border px-2 py-1 font-mono text-[10px] tracking-[0.12em]",
                  dept === d.key ? "border-accent text-accent" : "border-border text-muted-foreground hover:text-foreground",
                )}
              >
                {d.name.toUpperCase()}
              </button>
            ))}
          </div>
        </div>

        <div className="flex min-h-0 flex-col lg:h-[calc(100vh-3.5rem)]">
          <Panel title="Live company activity" dense className="min-h-[220px] flex-1 border-b border-border">
            <ul className="h-full overflow-y-auto px-3 py-2">
              {feed.map((f) => (
                <li key={f.id} className="stream-enter border-l-2 border-border pl-2.5 pb-2 last:pb-0">
                  <div className="font-mono text-[10px] text-muted-foreground">
                    {f.from === "AI" ? "AI" : `→ ${departmentName(f.department).toUpperCase()}`}
                  </div>
                  <p className={cn("text-[13px]", f.from === "AI" ? "text-primary" : "text-foreground")}>{f.text}</p>
                </li>
              ))}
              {feed.length === 0 && (
                <li className="py-6 text-center font-mono text-[11px] text-muted-foreground">Live mode paused</li>
              )}
            </ul>
          </Panel>

          <Panel title={`${departmentName(dept)} interaction`} dense className="min-h-[220px] flex-1">
            <ul className="h-full overflow-y-auto px-3 py-2">
              {history.map((h) => (
                <li key={h.id} className="grid grid-cols-[68px_1fr] gap-2 border-b border-border py-2 last:border-0">
                  <span className={cn("font-mono text-[10px]", h.from === "AI" ? "text-primary" : "text-accent")}>
                    {h.from === "AI" ? "AI →" : `${departmentName(h.department).split(" ")[0]} →`}
                  </span>
                  <div>
                    <p className="text-[13px] leading-snug">{h.text}</p>
                    <span className="label-xs">{h.time}</span>
                  </div>
                </li>
              ))}
            </ul>
          </Panel>
        </div>
      </div>
    </AppShell>
  );
}
