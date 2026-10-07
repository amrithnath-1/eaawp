import type { ReactElement } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { SendHorizonal, CheckCircle, Clock, XCircle, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { AppShell } from "@/components/eaawp/AppShell";
import { AmoebaButton } from "@/components/eaawp/AmoebaButton";
import { useAgentStatus } from "@/state/useAgentStatus";
import { ContextPanel } from "@/components/eaawp/ContextPanel";
import { useSession } from "@/state/session";
import { EmailDraftPreview, parseDraftPreview } from "@/components/eaawp/EmailDraftPreview";
import {
  useAgentExecute, DEFAULT_BLUEPRINT, useRoleConfig, roleConfigToBlueprint,
  useResumePlan, useRejectPlan, type ExecutionPlanFE,
} from "@/hooks/use-api";
import { USE_REAL_API } from "@/lib/api-client";
import { reportError } from "@/lib/error-reporting";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/cabin")({
  component: CabinPage,
});

interface Turn {
  id: string;
  from: "user" | "ai";
  text: string;
  time: string;
  sources: string[];
  requiresApproval: boolean;
  planId?: string | null;
  planStatus?: string | null;
  stepSummaries?: string[];
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
  return (match !== undefined && match in roleMap ? roleMap[match] : undefined) ?? roleMap["Data Intelligence Agent"]!;
}

function clock() {
  return new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

// ── Plan progress display ─────────────────────────────────────────────────────

const PLAN_STATUS_ICON: Record<string, ReactElement> = {
  completed: <CheckCircle className="size-3 text-success" />,
  failed: <XCircle className="size-3 text-destructive" />,
  rejected: <XCircle className="size-3 text-destructive" />,
  awaiting_approval: <Clock className="size-3 text-warning animate-pulse" />,
  running: <RefreshCw className="size-3 text-primary animate-spin" />,
  planning: <RefreshCw className="size-3 text-muted-foreground animate-spin" />,
};

const STEP_STATUS_COLOUR: Record<string, string> = {
  completed: "text-success",
  failed: "text-destructive",
  rejected: "text-destructive",
  skipped: "text-muted-foreground opacity-50",
  awaiting_approval: "text-warning",
  running: "text-primary",
  pending: "text-muted-foreground",
  approved: "text-success",
};

function PlanProgress({
  planId,
  planStatus,
  stepSummaries,
  onResolved,
}: {
  planId: string | null;
  planStatus: string | null;
  stepSummaries: string[];
  onResolved: (plan: ExecutionPlanFE) => void;
}) {
  const resumePlan = useResumePlan();

  if (!stepSummaries.length) return null;

  const statusIcon = planStatus ? (PLAN_STATUS_ICON[planStatus] ?? null) : null;

  return (
    <div className="mt-2 w-full border border-border bg-surface px-3 py-2 text-left">
      <div className="flex items-center gap-1.5 mb-1.5">
        {statusIcon}
        <span className="font-mono text-[10px] tracking-[0.12em] text-muted-foreground">
          {planStatus ? planStatus.replace(/_/g, " ").toUpperCase() : "PLAN"}
        </span>
        {planId && USE_REAL_API && (
          <span className="ml-auto font-mono text-[9px] text-muted-foreground opacity-60">
            {planId.slice(0, 8)}
          </span>
        )}
      </div>
      <ul className="space-y-0.5">
        {stepSummaries.map((s, i) => {
          const parts = s.match(/^\[(\w+)\] (.*?) → (\w+)$/);
          const type = parts?.[1] ?? "";
          const desc = parts?.[2] ?? s;
          const status = parts?.[3] ?? "";
          return (
            <li key={i} className={cn("font-mono text-[10px]", STEP_STATUS_COLOUR[status] ?? "text-muted-foreground")}>
              <span className="opacity-60">{i + 1}. [{type}]</span> {desc}
            </li>
          );
        })}
      </ul>
      {planStatus === "awaiting_approval" && planId && USE_REAL_API && (
        <button
          onClick={() =>
            resumePlan.mutate(
              { planId },
              {
                onSuccess: (plan) => {
                  onResolved(plan);
                  toast.success(plan.status === "completed" ? "Action approved and plan completed." : "Approval processed; review the plan status.");
                },
                onError: (err) => toast.error(err.message),
              },
            )
          }
          disabled={resumePlan.isPending}
          className="mt-2 flex items-center gap-1.5 border border-success/50 px-2 py-1 font-mono text-[10px] text-success hover:bg-success/10 disabled:opacity-40"
        >
          {resumePlan.isPending ? <><RefreshCw className="size-3 animate-spin" /> APPROVING…</> : "APPROVE & RESUME"}
        </button>
      )}
    </div>
  );
}

function CabinPage() {
  const { user, company } = useSession();
  const { status } = useAgentStatus();
  const agentExecute = useAgentExecute();
  const { data: roleConfig } = useRoleConfig("DIGITAL_MARKETING_MANAGER");
  const resumePlan = useResumePlan();
  const rejectPlan = useRejectPlan();

  const [turns, setTurns] = useState<Turn[]>([]);
  const [text, setText] = useState("");
  const [sessionId] = useState(() => `session-${Date.now()}`);
  const boxRef = useRef<HTMLTextAreaElement>(null);
  const endRef = useRef<HTMLDivElement>(null);

  // Use quick prompts from the live role config when available, fall back to local map
  const quickPrompts = roleConfig?.quick_prompts ?? getRoleQuickPrompts(company?.agentRole);

  function syncPlanResult(plan: ExecutionPlanFE) {
    setTurns((current) => current.map((turn) => turn.planId === plan.id
      ? {
          ...turn,
          text: plan.final_message,
          requiresApproval: false,
          planStatus: plan.status,
          stepSummaries: plan.steps.map((step) => `[${step.step_type.toUpperCase()}] ${step.description} → ${step.status}`),
        }
      : turn));
  }

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
      sources: [],
      requiresApproval: false,
    };
    setTurns((t) => [...t, userTurn]);
    setText("");

    try {
      // Build blueprint: use live role config if available,
      // always inject the real tenant_id from session/localStorage
      const realTenantId =
        (typeof window !== "undefined"
          ? window.localStorage.getItem("eaawp.last_company_id")
          : null) ??
        user?.companyId ??
        "default-tenant";

      const blueprint = roleConfig
        ? { ...roleConfigToBlueprint(roleConfig, realTenantId), tenant_id: realTenantId }
        : { ...DEFAULT_BLUEPRINT, tenant_id: realTenantId };

      const result = await agentExecute.mutateAsync({
        blueprint,
        user_prompt: prompt,
        session_id: sessionId,
      });

      setTurns((t) => [
        ...t,
        {
          id: `a-${Date.now()}`,
          from: "ai" as const,
          time: clock(),
          text: result.message,
          sources: result.sources ?? [],
          requiresApproval: result.requires_approval ?? false,
          planId: result.plan_id ?? null,
          planStatus: result.plan_status ?? null,
          stepSummaries: result.step_summaries ?? [],
        },
      ]);
    } catch (err) {
      const errorMessage =
        err instanceof Error ? err.message : "Agent execution failed. Check your connection.";
      reportError(err, { prompt: prompt.slice(0, 100), sessionId });
      toast.error(errorMessage);
      setTurns((t) => [
        ...t,
        {
          id: `err-${Date.now()}`,
          from: "ai" as const,
          time: clock(),
          text: `Error: ${errorMessage}`,
          sources: [],
          requiresApproval: false,
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
                    {/* Email draft preview — shown when the agent prepared a draft */}
                    {t.from === "ai" && (() => {
                      const draft = parseDraftPreview(t.text);
                      return draft ? <EmailDraftPreview draft={draft} /> : null;
                    })()}
                    {t.sources && t.sources.length > 0 && (
                      <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
                        {t.sources.map((s) => (
                          <li
                            key={s}
                            className={cn(
                              "font-mono text-[10px]",
                              s.startsWith("Company data")
                                ? "text-primary"
                                : "text-muted-foreground",
                            )}
                          >
                            {s.startsWith("Company data") ? "● " : "SOURCE · "}{s}
                          </li>
                        ))}
                      </ul>
                    )}
                    {t.requiresApproval && (
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {/* Approve — decide the pending ApprovalRequest then resume the plan */}
                        <button
                          disabled={resumePlan.isPending || rejectPlan.isPending}
                          onClick={() => {
                            if (!USE_REAL_API) {
                              toast.info("Connect real API to use approvals.");
                              return;
                            }
                            if (!t.planId) {
                              toast.error("No plan ID on this turn — cannot approve.");
                              return;
                            }
                            resumePlan.mutate(
                              { planId: t.planId },
                              {
                                onSuccess: (plan) => {
                                  syncPlanResult(plan);
                                  toast.success(plan.status === "completed" ? "Action approved and plan completed." : "Approval processed; review the plan status.");
                                },
                                onError: (err) => {
                                  reportError(err, { planId: t.planId });
                                  toast.error(`Approval failed: ${err.message}`);
                                },
                              },
                            );
                          }}
                          className="border border-success/60 px-2 py-1 font-mono text-[10px] tracking-[0.12em] text-success hover:bg-success/10 disabled:opacity-40"
                        >
                          {resumePlan.isPending ? "APPROVING…" : "APPROVE"}
                        </button>

                        {/* Reject — record a rejection; plan will not continue */}
                        <button
                          disabled={rejectPlan.isPending || resumePlan.isPending}
                          onClick={() => {
                            if (!USE_REAL_API) {
                              toast.info("Connect real API to use approvals.");
                              return;
                            }
                            if (!t.planId) {
                              toast.error("No plan ID on this turn — cannot reject.");
                              return;
                            }
                            rejectPlan.mutate(
                              { planId: t.planId },
                              {
                                onSuccess: (plan) => {
                                  syncPlanResult(plan);
                                  toast.success("Action rejected. It was not executed, and the plan stopped.");
                                },
                                onError: (err) => {
                                  reportError(err, { planId: t.planId });
                                  toast.error(`Rejection failed: ${err.message}`);
                                },
                              },
                            );
                          }}
                          className="border border-destructive/60 px-2 py-1 font-mono text-[10px] tracking-[0.12em] text-destructive hover:bg-destructive/10 disabled:opacity-40"
                        >
                          {rejectPlan.isPending ? "REJECTING…" : "REQUEST CHANGES"}
                        </button>

                        {/* Open task — navigate to the full Approvals page for details */}
                        <a
                          href="/approvals"
                          className="border border-border px-2 py-1 font-mono text-[10px] tracking-[0.12em] text-muted-foreground hover:border-border-strong hover:text-foreground"
                        >
                          OPEN IN APPROVALS
                        </a>
                      </div>
                    )}
                    {/* Plan progress display */}
                    {t.stepSummaries && t.stepSummaries.length > 0 && (
                      <PlanProgress
                        planId={t.planId ?? null}
                        planStatus={t.planStatus ?? null}
                        stepSummaries={t.stepSummaries}
                        onResolved={syncPlanResult}
                      />
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
