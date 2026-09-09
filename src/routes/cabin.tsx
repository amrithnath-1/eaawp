import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { Mic, Paperclip, SendHorizonal } from "lucide-react";
import { toast } from "sonner";
import { AppShell } from "@/components/eaawp/AppShell";
import { AmoebaButton } from "@/components/eaawp/AmoebaButton";
import { useAgentStatus } from "@/state/useAgentStatus";
import { ContextPanel } from "@/components/eaawp/ContextPanel";
import { useSession } from "@/state/session";
import { useAgentExecute } from "@/hooks/use-api";
import { USE_REAL_API } from "@/lib/api-client";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/cabin")({
  component: CabinPage,
});

interface Turn {
  id: string;
  from: "user" | "ai";
  text: string;
  time: string;
  sources?: string[];
  requiresApproval?: boolean;
}

function getRoleQuickPrompts(agentRole: string | undefined): string[] {
  // Role-specific prompts — will be driven by role config once backend is live
  const roleMap: Record<string, string[]> = {
    "Digital Marketing Manager": [
      "Analyse campaign performance this week",
      "What content is trending?",
      "Prepare monthly marketing report",
      "Which channels are underperforming?",
      "Suggest A/B test ideas",
    ],
    "Data Intelligence Agent": [
      "Analyse sales performance",
      "Prepare monthly report",
      "Compare customer trends",
      "Check pending tasks",
      "Generate management summary",
    ],
    "Operations Analyst Agent": [
      "Summarise operational bottlenecks",
      "Check hub throughput",
      "Review SLA compliance",
      "Identify process delays",
      "Generate ops report",
    ],
    "Financial Reporting Agent": [
      "Prepare period close summary",
      "Flag revenue anomalies",
      "Compare actuals to forecast",
      "Audit ledger entries",
      "Generate finance report",
    ],
  };

  const match = agentRole ? Object.keys(roleMap).find((k) => agentRole.includes(k.split(" ")[0]!)) : undefined;
  return (match && roleMap[match]) ?? roleMap["Data Intelligence Agent"]!;
}

function clock() {
  return new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function CabinPage() {
  const { user, company } = useSession();
  const { status } = useAgentStatus();
  const agentExecute = useAgentExecute();

  const [turns, setTurns] = useState<Turn[]>([]);
  const [text, setText] = useState("");
  const [sessionId] = useState(() => `session-${Date.now()}`);
  const boxRef = useRef<HTMLTextAreaElement>(null);
  const endRef = useRef<HTMLDivElement>(null);

  const quickPrompts = getRoleQuickPrompts(company?.agentRole);

  useEffect(() => {
    boxRef.current?.focus();
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns, agentExecute.isPending]);

  async function send(value?: string) {
    const prompt = (value ?? text).trim();
    if (!prompt) return;

    const userTurn: Turn = {
      id: `u-${Date.now()}`,
      from: "user",
      text: prompt,
      time: clock(),
    };
    setTurns((t) => [...t, userTurn]);
    setText("");

    try {
      const result = await agentExecute.mutateAsync({
        user_prompt: prompt,
        session_id: sessionId,
      });

      setTurns((t) => [
        ...t,
        {
          id: `a-${Date.now()}`,
          from: "ai",
          time: clock(),
          text: result.message,
          sources: result.sources,
          requiresApproval: result.requires_approval,
        },
      ]);
    } catch (err) {
      const errorMessage =
        err instanceof Error ? err.message : "Agent execution failed. Check your connection.";
      toast.error(errorMessage);
      setTurns((t) => [
        ...t,
        {
          id: `err-${Date.now()}`,
          from: "ai",
          time: clock(),
          text: `Error: ${errorMessage}`,
        },
      ]);
    }

    boxRef.current?.focus();
  }

  const empty = turns.length === 0 && !agentExecute.isPending;
  const isThinking = agentExecute.isPending;

  return (
    <AppShell>
      <div className="grid h-full grid-cols-1 xl:grid-cols-[minmax(0,1fr)_340px]">
        <section className="relative flex min-h-0 min-w-0 flex-col border-border xl:border-r">
          <AmoebaButton
            status={status}
            size={104}
            className="absolute right-4 top-3 z-10 hidden xl:block"
          />
          <div className="shrink-0 border-b border-border px-4 py-2">
            <p className="text-[13px] font-semibold tracking-tight">
              Agent Control Center — Autonomous Operations &amp; Approval Gateways
            </p>
            <div className="flex items-center gap-2">
              <p className="label-xs mt-0.5">
                Direct interaction with your company AI employee · all actions are audited
              </p>
              {!USE_REAL_API && (
                <span className="mt-0.5 font-mono text-[9px] tracking-[0.1em] text-warning">
                  · MOCK MODE
                </span>
              )}
            </div>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto">
            {empty ? (
              <div className="mx-auto flex h-full max-w-[680px] flex-col items-center justify-center px-4 py-10 text-center">
                <h1 className="text-2xl font-medium tracking-tight">
                  Hello {user?.name.split(" ")[0]},
                </h1>
                <p className="mt-1 text-2xl font-medium tracking-tight text-muted-foreground">
                  How can I help you today?
                </p>
                <p className="mt-3 text-[13px] text-muted-foreground">
                  Your {company?.agentRole} is ready to assist. It works continuously in the background.
                </p>
                <div className="mt-6 flex flex-wrap justify-center gap-1.5">
                  {quickPrompts.map((q) => (
                    <button
                      key={q}
                      onClick={() => void send(q)}
                      className="border border-border px-3 py-1.5 text-[12px] text-muted-foreground hover:border-border-strong hover:text-foreground"
                    >
                      {q}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <div className="mx-auto flex max-w-[760px] flex-col gap-4 px-4 py-5">
                {turns.map((t) => (
                  <article
                    key={t.id}
                    className={cn(
                      "flex max-w-[85%] flex-col",
                      t.from === "user"
                        ? "items-end self-end text-right"
                        : "items-start self-start text-left",
                    )}
                  >
                    <div className="flex items-baseline gap-2 font-mono text-[10px] tracking-[0.14em] text-muted-foreground">
                      <span className="text-foreground">
                        {t.from === "ai"
                          ? (company?.agentRole ?? "AGENT").toUpperCase()
                          : "YOU"}
                      </span>
                      <span>{t.time}</span>
                    </div>
                    <p
                      className={cn(
                        "mt-1.5 text-[13px] leading-relaxed",
                        t.from === "user" && "border border-border bg-surface px-3 py-2",
                        t.id.startsWith("err-") && "text-destructive",
                      )}
                    >
                      {t.text}
                    </p>
                    {t.sources && t.sources.length > 0 && (
                      <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
                        {t.sources.map((s) => (
                          <li key={s} className="font-mono text-[10px] text-muted-foreground">
                            SOURCE · {s}
                          </li>
                        ))}
                      </ul>
                    )}
                    {t.requiresApproval && (
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {["Approve", "Request changes", "Open task"].map((a) => (
                          <button
                            key={a}
                            onClick={() =>
                              toast.success(`${a} — sent to agent orchestrator`)
                            }
                            className="border border-border px-2 py-1 font-mono text-[10px] tracking-[0.12em] text-muted-foreground hover:border-border-strong hover:text-foreground"
                          >
                            {a.toUpperCase()}
                          </button>
                        ))}
                      </div>
                    )}
                  </article>
                ))}
                {isThinking && (
                  <p className="self-start font-mono text-[10px] tracking-[0.16em] text-muted-foreground">
                    AGENT WORKING…
                  </p>
                )}
                <div ref={endRef} />
              </div>
            )}
          </div>

          <div className="shrink-0 border-t border-border bg-surface">
            <div className="mx-auto max-w-[760px] px-4 py-3">
              <div className="flex items-end gap-1.5 rounded-2xl border border-border bg-background px-2 py-1.5 focus-within:border-border-strong">
                <button
                  onClick={() => toast("Attach file — connect storage service")}
                  aria-label="Attach file"
                  className="grid size-8 shrink-0 place-items-center rounded-full text-muted-foreground hover:text-foreground"
                >
                  <Paperclip className="size-4" strokeWidth={1.5} />
                </button>
                <textarea
                  ref={boxRef}
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      void send();
                    }
                  }}
                  rows={1}
                  placeholder="Ask your agent anything…"
                  disabled={isThinking}
                  className="max-h-40 min-h-[34px] flex-1 resize-none self-center bg-transparent py-1.5 text-[13px] outline-none placeholder:text-muted-foreground disabled:opacity-50"
                />
                <button
                  onClick={() => toast("Voice capture — connect speech service")}
                  aria-label="Record voice"
                  className="grid size-8 shrink-0 place-items-center rounded-full text-muted-foreground hover:text-foreground"
                >
                  <Mic className="size-4" strokeWidth={1.5} />
                </button>
                <button
                  onClick={() => void send()}
                  disabled={isThinking || !text.trim()}
                  aria-label="Send prompt"
                  className={cn(
                    "grid size-8 shrink-0 place-items-center rounded-full border border-border text-muted-foreground",
                    text.trim() && !isThinking && "border-foreground bg-foreground text-background",
                    (isThinking || !text.trim()) && "opacity-40 cursor-not-allowed",
                  )}
                >
                  <SendHorizonal className="size-3.5" strokeWidth={1.5} />
                </button>
              </div>

              <p className="mt-1.5 text-center text-[11px] text-muted-foreground">
                Agent may make mistakes. Review important information before approving actions.
              </p>
            </div>
          </div>
        </section>

        <div className="hidden min-h-0 xl:block">
          <ContextPanel className="h-full" />
        </div>
      </div>
    </AppShell>
  );
}
