import type { ReactElement } from "react";
import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import {
  SendHorizonal,
  CheckCircle,
  Clock,
  XCircle,
  RefreshCw,
  ExternalLink,
  Square,
  RotateCcw,
  MessageSquarePlus,
  History,
} from "lucide-react";
import { toast } from "sonner";
import { useQueryClient } from "@tanstack/react-query";
import { AppShell } from "@/components/eaawp/AppShell";
import { AmoebaButton } from "@/components/eaawp/AmoebaButton";
import { useAgentStatus } from "@/state/useAgentStatus";
import { ContextPanel } from "@/components/eaawp/ContextPanel";
import { useSession } from "@/state/session";
import { useCurrentWorkspace } from "@/state/workspace";
import { EmailDraftPreview, parseDraftPreview } from "@/components/eaawp/EmailDraftPreview";
import { AdminProviderConfigPanel } from "@/components/eaawp/AdminProviderConfigPanel";
import { PendingTaskPanel } from "@/components/eaawp/PendingTaskPanel";
import { ChatMarkdown } from "@/components/eaawp/ChatMarkdown";
import { ToolStatusBar } from "@/components/eaawp/ToolStatusBar";
import { HistoryPanel } from "@/components/eaawp/HistoryPanel";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import {
  useAgentExecute,
  useResumePlan,
  useRejectPlan,
  type ExecutionPlanFE,
  useGscAuthorize,
  useGaAuthorize,
  type AgentExecutionResponse,
} from "@/hooks/use-api";
import {
  conversationKeys,
  fetchOlderMessages,
  useConversation,
  type ConversationMessage,
  type IntegrationActionMeta,
} from "@/hooks/use-conversations";
import { ApiError, USE_REAL_API, apiErrorMessage } from "@/lib/api-client";
import { reportError } from "@/lib/error-reporting";
import { cn } from "@/lib/utils";
import { IS_ADMIN_ROLE } from "@/lib/workspace";

// ── Integration action metadata helpers ──────────────────────────────────────

const ACTION_MARKER = "__integration_action__:";

function parseIntegrationAction(sources: string[]): IntegrationActionMeta | null {
  const marker = sources.find((s) => s.startsWith(ACTION_MARKER));
  if (!marker) return null;
  try {
    return JSON.parse(marker.slice(ACTION_MARKER.length)) as IntegrationActionMeta;
  } catch {
    return null;
  }
}

const PROVIDER_DISPLAY_NAMES: Record<string, string> = {
  google_search_console: "Google Search Console",
  google_analytics: "Google Analytics",
  facebook: "Meta / Facebook",
  github: "GitHub",
  postgresql: "PostgreSQL",
  mysql: "MySQL",
  mcp: "MCP Server",
};

// ── Integration action UI card ────────────────────────────────────────────────

function IntegrationActionCard({ meta }: { meta: IntegrationActionMeta }) {
  const gscAuth = useGscAuthorize();
  const gaAuth = useGaAuthorize();
  const [configured, setConfigured] = useState(false);
  const provider = String(meta.action_data.provider_type ?? "");
  const providerName = PROVIDER_DISPLAY_NAMES[provider] ?? provider;

  if (meta.next_action === "CONFIGURATION_REQUIRED") {
    return (
      <div className="mt-3 w-full">
        <AdminProviderConfigPanel
          providerType={provider}
          providerDisplayName={providerName}
          onConfigured={() => setConfigured(true)}
        />
        {configured && (
          <div className="mt-2 border border-success/40 bg-success/5 p-2 text-[12px] text-success">
            ✓ Configuration saved. You can now proceed with authorization.
          </div>
        )}
      </div>
    );
  }

  if (meta.next_action === "REDIRECT_TO_OAUTH") {
    const isGA = provider === "google_analytics";
    return (
      <div className="mt-3 w-full border border-border bg-surface p-3">
        <p className="mb-2 text-[12px] text-muted-foreground">
          Click below to authorize {providerName} via Google:
        </p>
        <button
          disabled={gscAuth.isPending || gaAuth.isPending}
          onClick={() => {
            const auth = isGA ? gaAuth : gscAuth;
            auth.mutate(undefined, {
              onSuccess: (data) => {
                window.location.href = data.authorization_url;
              },
              onError: (err) => {
                toast.error(`Authorization failed: ${err.message}`);
              },
            });
          }}
          className="inline-flex items-center gap-2 border border-border bg-foreground/5 px-3 py-1.5 font-mono text-[11px] tracking-[0.08em] hover:bg-foreground/10 disabled:opacity-40"
        >
          <ExternalLink className="size-3.5" />
          {gscAuth.isPending || gaAuth.isPending
            ? "OPENING…"
            : `CONNECT WITH GOOGLE — ${providerName.toUpperCase()}`}
        </button>
      </div>
    );
  }

  if (meta.next_action === "OPEN_INTEGRATIONS") {
    return (
      <a
        href={`/integrations?tab=${encodeURIComponent(provider)}`}
        className="mt-2 inline-flex items-center gap-1.5 border border-border px-2 py-1 font-mono text-[10px] tracking-[0.1em] hover:bg-foreground/5"
      >
        <ExternalLink className="size-3" /> OPEN INTEGRATIONS · {providerName.toUpperCase()}
      </a>
    );
  }

  if (meta.next_action === "SHOW_STATUS" && meta.action_data.integration_id) {
    return (
      <div className="mt-2 flex flex-wrap items-center gap-2 border border-success/40 bg-success/5 p-2 text-[12px] text-success">
        ✓ {providerName} is connected.
        <a href={`/integrations?tab=${encodeURIComponent(provider)}`} className="underline">
          View connection and access
        </a>
      </div>
    );
  }

  return null;
}

export const Route = createFileRoute("/cabin")({
  validateSearch: (s: Record<string, unknown>): { c?: string } =>
    typeof s["c"] === "string" && /^[0-9a-f-]{36}$/i.test(s["c"]) ? { c: s["c"] } : {},
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
  integrationAction?: IntegrationActionMeta | null;
  error?: boolean;
  /** For a failed request: the prompt that can be sent again. */
  retryPrompt?: string;
}

function clock(d: Date = new Date()) {
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function parseServerTime(iso: string): Date {
  return new Date(iso.endsWith("Z") || iso.includes("+") ? iso : `${iso}Z`);
}

function turnFromMessage(m: ConversationMessage): Turn {
  return {
    id: m.id,
    from: m.sender === "user" ? "user" : "ai",
    text: m.content,
    time: clock(parseServerTime(m.created_at)),
    sources: m.sources ?? [],
    requiresApproval: !!m.requires_approval,
    planId: m.plan_id,
    planStatus: m.plan_status ?? null,
    stepSummaries: m.step_summaries ?? [],
    integrationAction: m.integration_action ?? null,
    error: !!m.error,
  };
}

function turnFromResponse(result: AgentExecutionResponse): Turn {
  const sources = result.sources ?? [];
  return {
    id: `a-${Date.now()}`,
    from: "ai",
    time: clock(),
    text: result.message,
    sources: sources.filter((s) => !s.startsWith(ACTION_MARKER)),
    integrationAction: parseIntegrationAction(sources),
    requiresApproval: result.requires_approval ?? false,
    planId: result.plan_id ?? null,
    planStatus: result.plan_status ?? null,
    stepSummaries: result.step_summaries ?? [],
  };
}

// ── Plan progress display ─────────────────────────────────────────────────────

const PLAN_STATUS_ICON: Record<string, ReactElement> = {
  completed: <CheckCircle className="size-3 text-success" />,
  failed: <XCircle className="size-3 text-destructive" />,
  rejected: <XCircle className="size-3 text-destructive" />,
  awaiting_approval: <Clock className="size-3 text-warning animate-pulse" />,
  awaiting_setup: <Clock className="size-3 text-warning" />,
  running: <RefreshCw className="size-3 text-primary animate-spin" />,
  planning: <RefreshCw className="size-3 text-muted-foreground animate-spin" />,
};

const PLAN_STATUS_TEXT: Record<string, string> = {
  completed: "COMPLETED",
  failed: "FAILED — NOTHING FURTHER WAS DONE",
  rejected: "REJECTED — THE ACTION WAS NOT EXECUTED",
  awaiting_approval: "PROPOSED — WAITING FOR APPROVAL (NOT EXECUTED YET)",
  awaiting_setup: "SAVED — WAITING FOR SETUP",
  running: "RUNNING",
  planning: "PLANNING",
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
  canApprove,
  onResolved,
}: {
  planId: string | null;
  planStatus: string | null;
  stepSummaries: string[];
  canApprove: boolean;
  onResolved: (plan: ExecutionPlanFE) => void;
}) {
  const resumePlan = useResumePlan();

  if (!stepSummaries.length) return null;

  const statusIcon = planStatus ? (PLAN_STATUS_ICON[planStatus] ?? null) : null;

  return (
    <div className="mt-2 w-full border border-border bg-surface px-3 py-2 text-left">
      <div className="mb-1.5 flex items-center gap-1.5">
        {statusIcon}
        <span className="font-mono text-[10px] tracking-[0.12em] text-muted-foreground">
          {planStatus
            ? (PLAN_STATUS_TEXT[planStatus] ?? planStatus.replace(/_/g, " ").toUpperCase())
            : "PLAN"}
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
            <li
              key={i}
              className={cn(
                "font-mono text-[10px]",
                STEP_STATUS_COLOUR[status] ?? "text-muted-foreground",
              )}
            >
              <span className="opacity-60">
                {i + 1}. [{type}]
              </span>{" "}
              {desc}
              {status ? ` — ${status.replace(/_/g, " ")}` : ""}
            </li>
          );
        })}
      </ul>
      {planStatus === "awaiting_approval" && planId && USE_REAL_API && canApprove && (
        <button
          onClick={() =>
            resumePlan.mutate(
              { planId },
              {
                onSuccess: (plan) => {
                  onResolved(plan);
                  toast.success(
                    plan.status === "completed"
                      ? "Action approved and plan completed."
                      : "Approval processed; review the plan status.",
                  );
                },
                onError: (err) => toast.error(err.message),
              },
            )
          }
          disabled={resumePlan.isPending}
          className="mt-2 flex items-center gap-1.5 border border-success/50 px-2 py-1 font-mono text-[10px] text-success hover:bg-success/10 disabled:opacity-40"
        >
          {resumePlan.isPending ? (
            <>
              <RefreshCw className="size-3 animate-spin" /> APPROVING…
            </>
          ) : (
            "APPROVE & RESUME"
          )}
        </button>
      )}
    </div>
  );
}

function CabinPage() {
  const { user } = useSession();
  const { status } = useAgentStatus();
  const agentExecute = useAgentExecute();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { c: conversationParam } = Route.useSearch();
  // The AI runs as the person's selected workspace role; the server decides the role, its persona, tools and
  // knowledge itself, so nothing here can widen what the agent may do.
  const ws = useCurrentWorkspace().data;
  const ai = ws?.ai ?? null;
  const roleKey = ai?.role_key ?? ws?.selected?.role_key;
  const agentLabel = ai?.role_name ?? "AI employee";
  const isAdmin = IS_ADMIN_ROLE(user?.role);
  const resumePlan = useResumePlan();
  const rejectPlan = useRejectPlan();

  const [turns, setTurns] = useState<Turn[]>([]);
  const [text, setText] = useState("");
  const [activeId, setActiveId] = useState<string | null>(conversationParam ?? null);
  const loadedId = useRef<string | null>(null);
  const [olderCursor, setOlderCursor] = useState<string | null>(null);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const boxRef = useRef<HTMLTextAreaElement>(null);
  const endRef = useRef<HTMLDivElement>(null);

  const conversation = useConversation(activeId && activeId !== loadedId.current ? activeId : null);
  const readOnlyRole =
    conversation.data && roleKey && conversation.data.role_key !== roleKey
      ? conversation.data.role_name
      : null;
  const [openRoleName, setOpenRoleName] = useState<string | null>(null);

  // The URL is the source of truth for which conversation is open (History links set ?c=...).
  useEffect(() => {
    const next = conversationParam ?? null;
    if (next !== activeId) {
      setActiveId(next);
      if (next === null) {
        loadedId.current = null;
        setTurns([]);
        setOlderCursor(null);
        setOpenRoleName(null);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversationParam]);

  // Load a saved conversation once per id.
  useEffect(() => {
    const d = conversation.data;
    if (!d || d.id !== activeId || loadedId.current === d.id) return;
    loadedId.current = d.id;
    setTurns(d.messages.map(turnFromMessage));
    setOlderCursor(d.has_more && d.messages.length ? d.messages[0]!.created_at : null);
    setOpenRoleName(roleKey && d.role_key !== roleKey ? d.role_name : null);
  }, [conversation.data, activeId, roleKey]);

  useEffect(() => {
    if (conversation.isError && activeId && loadedId.current !== activeId) {
      toast.error("That conversation could not be opened. It may have been deleted.");
      void navigate({ to: "/cabin", search: {}, replace: true });
    }
  }, [conversation.isError, activeId, navigate]);

  const quickPrompts = ai?.quick_prompts ?? [];

  function syncPlanResult(plan: ExecutionPlanFE) {
    setTurns((current) =>
      current.map((turn) =>
        turn.planId === plan.id
          ? {
              ...turn,
              text: plan.final_message || turn.text,
              requiresApproval: false,
              planStatus: plan.status,
              stepSummaries: plan.steps.map(
                (step) => `[${step.step_type.toUpperCase()}] ${step.description} → ${step.status}`,
              ),
            }
          : turn,
      ),
    );
    void qc.invalidateQueries({ queryKey: conversationKeys.all });
    void qc.invalidateQueries({ queryKey: ["workspace-tools"] });
  }

  /** A saved request was run after setup: show the original question and the real answer. */
  function showResumedResult(prompt: string, result: AgentExecutionResponse) {
    setTurns((t) => [
      ...t,
      {
        id: `u-${Date.now()}`,
        from: "user" as const,
        text: prompt,
        time: clock(),
        sources: [],
        requiresApproval: false,
      },
      turnFromResponse(result),
    ]);
    void qc.invalidateQueries({ queryKey: conversationKeys.all });
  }

  useEffect(() => {
    boxRef.current?.focus();
  }, [activeId]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns, agentExecute.isPending]);

  useEffect(() => {
    if (startedAt === null) return;
    const t = window.setInterval(
      () => setElapsed(Math.round((Date.now() - startedAt) / 1000)),
      1000,
    );
    return () => window.clearInterval(t);
  }, [startedAt]);

  async function loadOlder() {
    if (!activeId || !olderCursor) return;
    setLoadingOlder(true);
    try {
      const page = await fetchOlderMessages(activeId, olderCursor);
      setTurns((t) => [...page.messages.map(turnFromMessage), ...t]);
      setOlderCursor(page.has_more && page.messages.length ? page.messages[0]!.created_at : null);
    } catch (err) {
      toast.error(apiErrorMessage(err));
    } finally {
      setLoadingOlder(false);
    }
  }

  function stopWaiting() {
    abortRef.current?.abort();
  }

  async function send(value?: string) {
    const prompt = (value ?? text).trim();
    if (!prompt || agentExecute.isPending || openRoleName) return;

    setTurns((t) => [
      ...t,
      {
        id: `u-${Date.now()}`,
        from: "user",
        text: prompt,
        time: clock(),
        sources: [],
        requiresApproval: false,
      },
    ]);
    setText("");
    const controller = new AbortController();
    abortRef.current = controller;
    setStartedAt(Date.now());
    setElapsed(0);

    try {
      const tenantId = user?.companyId ?? "";
      const result = await agentExecute.mutateAsync({
        blueprint: {
          agent_id: `cabin-${roleKey ?? "agent"}`,
          role_name: agentLabel,
          ...(roleKey ? { role_key: roleKey } : {}),
          // The server replaces persona and tools with the role's own configuration.
          system_persona: "Defined by the server for this AI employee.",
          allowed_tools: [],
          guarded_tools: [],
          tenant_id: tenantId,
        },
        user_prompt: prompt,
        ...(activeId ? { conversation_id: activeId } : {}),
        signal: controller.signal,
      });

      setTurns((t) => [...t, turnFromResponse(result)]);
      if (result.conversation_id && result.conversation_id !== activeId) {
        loadedId.current = result.conversation_id;
        setActiveId(result.conversation_id);
        void navigate({ to: "/cabin", search: { c: result.conversation_id }, replace: true });
      }
    } catch (err) {
      if (controller.signal.aborted) {
        setTurns((t) => [
          ...t,
          {
            id: `stop-${Date.now()}`,
            from: "ai",
            time: clock(),
            sources: [],
            requiresApproval: false,
            error: true,
            text:
              "You stopped waiting for this answer. The AI employee may still finish the request on the server; " +
              "if it does, the answer is saved in History. Nothing was retried automatically.",
          },
        ]);
        window.setTimeout(
          () => void qc.invalidateQueries({ queryKey: conversationKeys.all }),
          5000,
        );
      } else {
        const conflict = err instanceof ApiError && err.status === 409;
        const errorMessage = apiErrorMessage(err) || "The request failed. Check your connection.";
        reportError(err, { prompt: prompt.slice(0, 100) });
        if (!conflict) toast.error(errorMessage);
        setTurns((t) => [
          ...t,
          {
            id: `err-${Date.now()}`,
            from: "ai",
            time: clock(),
            sources: [],
            requiresApproval: false,
            error: true,
            text: conflict
              ? errorMessage
              : `${errorMessage} Nothing was executed for this request.`,
            ...(conflict ? {} : { retryPrompt: prompt }),
          },
        ]);
      }
      void qc.invalidateQueries({ queryKey: conversationKeys.all });
    } finally {
      abortRef.current = null;
      setStartedAt(null);
    }

    boxRef.current?.focus();
  }

  const isThinking = agentExecute.isPending;
  const loadingConversation = !!activeId && activeId !== loadedId.current && conversation.isLoading;
  const empty = turns.length === 0 && !isThinking && !loadingConversation;

  return (
    <AppShell>
      <div className="grid h-full grid-cols-1 xl:grid-cols-[minmax(0,1fr)_340px]">
        <section className="relative flex min-h-0 min-w-0 flex-col border-border xl:border-r">
          <AmoebaButton
            status={status}
            size={104}
            className="absolute right-4 top-3 z-10 hidden xl:block"
          />
          <div className="shrink-0 border-b border-border px-4 py-2 xl:pr-32">
            <div className="flex flex-wrap items-center gap-2">
              <p data-testid="cabin-title" className="text-[13px] font-semibold tracking-tight">
                {ai?.agent_name ?? "AI employee"} — {agentLabel} workspace
              </p>
              <Sheet>
                <SheetTrigger asChild>
                  <button className="inline-flex items-center gap-1 border border-border px-1.5 py-0.5 font-mono text-[9px] tracking-[0.1em] text-muted-foreground hover:text-foreground xl:hidden">
                    <History className="size-3" /> HISTORY
                  </button>
                </SheetTrigger>
                <SheetContent side="right" className="flex w-[320px] flex-col p-0 sm:w-[360px]">
                  <SheetHeader className="border-b border-border p-3 text-left">
                    <SheetTitle className="text-[13px]">History</SheetTitle>
                    <SheetDescription className="text-[11px]">
                      Your saved conversations. Only you can see them.
                    </SheetDescription>
                  </SheetHeader>
                  <div className="min-h-0 flex-1">
                    <HistoryPanel />
                  </div>
                </SheetContent>
              </Sheet>
              {activeId && (
                <Link
                  to="/cabin"
                  search={{}}
                  className="inline-flex items-center gap-1 border border-border px-1.5 py-0.5 font-mono text-[9px] tracking-[0.1em] text-muted-foreground hover:text-foreground"
                >
                  <MessageSquarePlus className="size-3" /> NEW CHAT
                </Link>
              )}
            </div>
            <div className="flex flex-wrap items-center gap-x-2">
              <p className="label-xs mt-0.5">
                Direct interaction with your company AI employee · all actions are audited · chats
                are saved to your private History
              </p>
              {USE_REAL_API && ai && <ToolStatusBar roleKey={roleKey} />}
              {!USE_REAL_API && (
                <span className="mt-0.5 font-mono text-[9px] tracking-[0.1em] text-warning">
                  · MOCK MODE
                </span>
              )}
            </div>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto" aria-live="polite">
            <PendingTaskPanel onResult={showResumedResult} />
            {loadingConversation ? (
              <p className="flex items-center justify-center gap-2 p-10 text-[12px] text-muted-foreground">
                <RefreshCw className="size-3 animate-spin" /> Opening conversation…
              </p>
            ) : empty ? (
              <div className="mx-auto flex h-full max-w-[680px] flex-col items-center justify-center px-4 py-10 text-center">
                <h1 className="text-2xl font-medium tracking-tight">
                  Hello {user?.name.split(" ")[0]},
                </h1>
                <p className="mt-1 text-2xl font-medium tracking-tight text-muted-foreground">
                  How can I help you today?
                </p>
                <p className="mt-3 text-[13px] text-muted-foreground">
                  You are working with the {agentLabel}. It answers from your company Library, the
                  approved company profile and the services an administrator connected, and asks for
                  approval before changing or sending anything.
                </p>
                {quickPrompts.length > 0 && (
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
                )}
              </div>
            ) : (
              <div className="mx-auto flex max-w-[760px] flex-col gap-4 px-4 py-5">
                {olderCursor && (
                  <button
                    onClick={() => void loadOlder()}
                    disabled={loadingOlder}
                    className="self-center border border-border px-2 py-1 font-mono text-[10px] tracking-[0.1em] text-muted-foreground hover:text-foreground disabled:opacity-40"
                  >
                    {loadingOlder ? "LOADING…" : "LOAD EARLIER MESSAGES"}
                  </button>
                )}
                {turns.map((t) => (
                  <article
                    key={t.id}
                    className={cn(
                      "flex min-w-0 flex-col",
                      t.from === "user"
                        ? "max-w-[92%] items-end self-end text-right sm:max-w-[85%]"
                        : "w-full items-start self-start text-left",
                    )}
                  >
                    <div className="flex items-baseline gap-2 font-mono text-[10px] tracking-[0.14em] text-muted-foreground">
                      <span className="text-foreground">
                        {t.from === "ai" ? agentLabel.toUpperCase() : "YOU"}
                      </span>
                      <span>{t.time}</span>
                    </div>
                    {t.from === "user" ? (
                      <p className="mt-1.5 whitespace-pre-wrap border border-border bg-surface px-3 py-2 text-left text-[13px] leading-relaxed">
                        {t.text}
                      </p>
                    ) : (
                      <ChatMarkdown
                        text={t.text}
                        className={cn("mt-1.5 w-full", t.error && "text-destructive")}
                      />
                    )}
                    {t.retryPrompt && (
                      <button
                        onClick={() => void send(t.retryPrompt)}
                        disabled={isThinking}
                        className="mt-2 inline-flex items-center gap-1 border border-border px-2 py-1 font-mono text-[10px] tracking-[0.1em] hover:bg-foreground/5 disabled:opacity-40"
                      >
                        <RotateCcw className="size-3" /> TRY AGAIN
                      </button>
                    )}
                    {/* Email draft preview — shown when the agent prepared a draft */}
                    {t.from === "ai" &&
                      (() => {
                        const draft = parseDraftPreview(t.text);
                        return draft ? <EmailDraftPreview draft={draft} /> : null;
                      })()}
                    {t.sources.length > 0 && (
                      <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1" aria-label="Sources">
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
                            {s.startsWith("Company data") ? "● " : "SOURCE · "}
                            {s}
                          </li>
                        ))}
                      </ul>
                    )}
                    {t.from === "ai" && t.integrationAction && (
                      <IntegrationActionCard meta={t.integrationAction} />
                    )}
                    {t.requiresApproval && t.planStatus === "awaiting_approval" && (
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {isAdmin ? (
                          <>
                            <button
                              disabled={resumePlan.isPending || rejectPlan.isPending}
                              onClick={() => {
                                if (!t.planId) return;
                                resumePlan.mutate(
                                  { planId: t.planId },
                                  {
                                    onSuccess: (plan) => {
                                      syncPlanResult(plan);
                                      toast.success(
                                        plan.status === "completed"
                                          ? "Action approved and plan completed."
                                          : "Approval processed; review the plan status.",
                                      );
                                    },
                                    onError: (err) => {
                                      reportError(err, { planId: t.planId });
                                      toast.error(`Approval failed: ${apiErrorMessage(err)}`);
                                    },
                                  },
                                );
                              }}
                              className="border border-success/60 px-2 py-1 font-mono text-[10px] tracking-[0.12em] text-success hover:bg-success/10 disabled:opacity-40"
                            >
                              {resumePlan.isPending ? "APPROVING…" : "APPROVE"}
                            </button>
                            <button
                              disabled={rejectPlan.isPending || resumePlan.isPending}
                              onClick={() => {
                                if (!t.planId) return;
                                rejectPlan.mutate(
                                  { planId: t.planId },
                                  {
                                    onSuccess: (plan) => {
                                      syncPlanResult(plan);
                                      toast.success(
                                        "Action rejected. It was not executed, and the plan stopped.",
                                      );
                                    },
                                    onError: (err) => {
                                      reportError(err, { planId: t.planId });
                                      toast.error(`Rejection failed: ${apiErrorMessage(err)}`);
                                    },
                                  },
                                );
                              }}
                              className="border border-destructive/60 px-2 py-1 font-mono text-[10px] tracking-[0.12em] text-destructive hover:bg-destructive/10 disabled:opacity-40"
                            >
                              {rejectPlan.isPending ? "REJECTING…" : "REJECT"}
                            </button>
                          </>
                        ) : (
                          <p className="text-[11px] text-muted-foreground">
                            A company administrator must approve this action before it runs.
                          </p>
                        )}
                        <Link
                          to="/approvals"
                          className="border border-border px-2 py-1 font-mono text-[10px] tracking-[0.12em] text-muted-foreground hover:border-border-strong hover:text-foreground"
                        >
                          OPEN IN APPROVALS
                        </Link>
                      </div>
                    )}
                    {t.stepSummaries && t.stepSummaries.length > 0 && (
                      <PlanProgress
                        planId={t.planId ?? null}
                        planStatus={t.planStatus ?? null}
                        stepSummaries={t.stepSummaries}
                        canApprove={false}
                        onResolved={syncPlanResult}
                      />
                    )}
                  </article>
                ))}
                {isThinking && (
                  <div className="flex items-center gap-3 self-start" role="status">
                    <span className="font-mono text-[10px] tracking-[0.16em] text-muted-foreground">
                      {agentLabel.toUpperCase()} IS WORKING… {elapsed > 2 ? `${elapsed}s` : ""}
                    </span>
                    <button
                      onClick={stopWaiting}
                      className="inline-flex items-center gap-1 border border-border px-2 py-0.5 font-mono text-[10px] tracking-[0.1em] text-muted-foreground hover:text-foreground"
                    >
                      <Square className="size-2.5" /> STOP WAITING
                    </button>
                  </div>
                )}
                <div ref={endRef} />
              </div>
            )}
          </div>

          <div className="shrink-0 border-t border-border bg-surface">
            <div className="mx-auto max-w-[760px] px-4 py-3">
              {openRoleName || readOnlyRole ? (
                <div className="flex flex-wrap items-center justify-between gap-2 border border-warning/50 bg-warning/5 px-3 py-2 text-[12px]">
                  <span>
                    This conversation is with the {openRoleName ?? readOnlyRole}. Switch AI employee
                    to continue it.
                  </span>
                  <span className="flex gap-1.5">
                    <Link
                      to="/select-role"
                      className="border border-border px-2 py-1 font-mono text-[10px] hover:bg-foreground/5"
                    >
                      SWITCH AI EMPLOYEE
                    </Link>
                    <Link
                      to="/cabin"
                      search={{}}
                      className="border border-border px-2 py-1 font-mono text-[10px] hover:bg-foreground/5"
                    >
                      NEW CHAT
                    </Link>
                  </span>
                </div>
              ) : (
                <div className="flex items-end gap-1.5 rounded-2xl border border-border bg-background px-2 py-1.5 focus-within:border-border-strong">
                  <textarea
                    ref={boxRef}
                    value={text}
                    onChange={(e) => setText(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                        e.preventDefault();
                        void send();
                      }
                    }}
                    rows={1}
                    aria-label={`Message the ${agentLabel}`}
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
                      text.trim() &&
                        !isThinking &&
                        "border-foreground bg-foreground text-background",
                      (isThinking || !text.trim()) && "opacity-40 cursor-not-allowed",
                    )}
                  >
                    <SendHorizonal className="size-3.5" strokeWidth={1.5} />
                  </button>
                </div>
              )}

              <p className="mt-1.5 text-center text-[11px] text-muted-foreground">
                Agent may make mistakes. Review important information before approving actions.
              </p>
            </div>
          </div>
        </section>

        <div className="hidden min-h-0 xl:block">
          <ContextPanel className="h-full" defaultTab="History" />
        </div>
      </div>
    </AppShell>
  );
}
