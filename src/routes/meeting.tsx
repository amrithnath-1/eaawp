import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { AppShell } from "@/components/eaawp/AppShell";
import { AgentOrganism } from "@/components/eaawp/AgentOrganism";
import { Panel } from "@/components/eaawp/Panel";
import { departmentName, departmentService } from "@/services";
import { departments } from "@/services/mockData";
import type { DepartmentExchange, DepartmentKey } from "@/services/types";
import { cn } from "@/lib/utils";
import { useAgentStatus } from "@/state/useAgentStatus";
import { SendHorizonal } from "lucide-react";
import { useAgentExecute, DEFAULT_BLUEPRINT } from "@/hooks/use-api";

export const Route = createFileRoute("/meeting")({
  component: MeetingRoom,
});

function MeetingRoom() {
  const { status } = useAgentStatus();
  const [dept, setDept] = useState<DepartmentKey>("finance");
  const [live, setLive] = useState(true);
  const [feed, setFeed] = useState<DepartmentExchange[]>([]);
  const [promptInput, setPromptInput] = useState("");
  const [latestPrompt, setLatestPrompt] = useState("");
  const [agentReply, setAgentReply] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const [sessionId] = useState(() => `meeting-${Date.now()}`);

  const agentExecute = useAgentExecute();

  function submitPrompt() {
    const trimmed = promptInput.trim();
    if (!trimmed || agentExecute.isPending) return;
    setLatestPrompt(trimmed);
    setAgentReply("");
    setPromptInput("");
    inputRef.current?.focus();

    agentExecute.mutate(
      { blueprint: DEFAULT_BLUEPRINT, user_prompt: trimmed, session_id: sessionId },
      {
        onSuccess: (res) => setAgentReply(res.message),
        onError: (err) => setAgentReply(`Error: ${err.message}`),
      },
    );
  }

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

          {/* Latest submitted prompt display */}
          <div className="mx-4 mb-2 min-h-[40px] border border-border bg-surface px-3 py-2">
            {latestPrompt ? (
              <p className="text-[13px] leading-snug text-foreground">{latestPrompt}</p>
            ) : (
              <p className="text-[13px] text-muted-foreground">No prompt submitted yet…</p>
            )}
          </div>

          {/* Agent reply display */}
          {(agentExecute.isPending || agentReply) && (
            <div className="mx-4 mb-2 border border-primary/40 bg-surface px-3 py-2">
              {agentExecute.isPending ? (
                <p className="animate-pulse text-[13px] text-muted-foreground">Agent thinking…</p>
              ) : (
                <p className="text-[13px] leading-snug text-primary">{agentReply}</p>
              )}
            </div>
          )}

          {/* Prompt input area */}
          <div className="mx-4 mb-4 flex items-center gap-2 border border-border bg-surface px-3 py-2">
            <input
              ref={inputRef}
              value={promptInput}
              onChange={(e) => setPromptInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") submitPrompt(); }}
              placeholder="Type a prompt…"
              className="flex-1 bg-transparent text-[13px] outline-none placeholder:text-muted-foreground"
              disabled={agentExecute.isPending}
            />
            <button
              onClick={submitPrompt}
              disabled={agentExecute.isPending || !promptInput.trim()}
              aria-label="Send prompt"
              className={cn(
                "grid size-7 shrink-0 place-items-center border border-border text-muted-foreground disabled:opacity-40",
                promptInput.trim() && !agentExecute.isPending && "border-foreground bg-foreground text-background",
              )}
            >
              <SendHorizonal className="size-3.5" strokeWidth={1.5} />
            </button>
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
