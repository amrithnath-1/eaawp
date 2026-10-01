import { createFileRoute } from "@tanstack/react-router";
import { useState, useEffect } from "react";
import { toast } from "sonner";
import { Check, Lock, X, ChevronDown, RefreshCw } from "lucide-react";
import { AppShell } from "@/components/eaawp/AppShell";
import { PageHeader, Panel } from "@/components/eaawp/Panel";
import { NLConfigPanel } from "@/components/eaawp/NLConfigPanel";
import { MonitoringPanel } from "@/components/eaawp/MonitoringPanel";
import { CampaignsPanel } from "@/components/eaawp/CampaignsPanel";
import { StrategyPanel } from "@/components/eaawp/StrategyPanel";
import { ContentPanel } from "@/components/eaawp/ContentPanel";
import { ReportingPanel } from "@/components/eaawp/ReportingPanel";
import { AdminCustomizePanel } from "@/components/eaawp/AdminCustomizePanel";
import { useSession } from "@/state/session";
import { cn } from "@/lib/utils";
import {
  useRoleConfig,
  useUpdateRoleConfig,
  useActiveBlueprint,
  type RoleConfigFull,
  type RoleToolScope,
  type RoleApprovalRule,
  type ToolGovernanceApi,
} from "@/hooks/use-api";

export const Route = createFileRoute("/customize")({
  component: CustomizePage,
});

// ── Autonomy levels ───────────────────────────────────────────────────────────

const AUTONOMY: { level: number; name: string; detail: string }[] = [
  { level: 1, name: "Assist", detail: "Answers and prepares material only when asked." },
  { level: 2, name: "Recommend", detail: "Monitors continuously and recommends actions to humans." },
  { level: 3, name: "Execute with approval", detail: "Prepares and executes work after a human approves." },
  { level: 4, name: "Authorized autonomous execution", detail: "Executes pre-authorized action classes and reports afterwards." },
];

const GOVERNANCE_CYCLE: ToolGovernanceApi[] = ["enabled", "requires_approval", "disabled"];

// ── Sub-components ────────────────────────────────────────────────────────────

function Toggle({ on, onClick, label }: { on: boolean; onClick: () => void; label: string }) {
  return (
    <button
      onClick={onClick}
      className="flex w-full items-center justify-between border-b border-border py-2 text-left last:border-0"
    >
      <span className="text-[13px]">{label}</span>
      <span className={cn("h-3.5 w-7 border transition-colors", on ? "border-primary bg-primary/30" : "border-border-strong bg-muted")}>
        <span className={cn("block size-3 transition-transform", on ? "translate-x-[14px] bg-primary" : "bg-muted-foreground")} />
      </span>
    </button>
  );
}

function GovernanceBadge({ governance }: { governance: ToolGovernanceApi }) {
  if (governance === "enabled") {
    return (
      <span className="inline-flex items-center gap-1 border border-success/40 bg-success/10 px-1.5 py-0.5 font-mono text-[10px] tracking-[0.1em] text-success">
        <Check className="size-2.5" strokeWidth={2.5} /> ENABLED
      </span>
    );
  }
  if (governance === "requires_approval") {
    return (
      <span className="inline-flex items-center gap-1 border border-warning/40 bg-warning/10 px-1.5 py-0.5 font-mono text-[10px] tracking-[0.1em] text-warning">
        <Lock className="size-2.5" strokeWidth={2.5} /> REQUIRES APPROVAL
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 border border-destructive/40 bg-destructive/10 px-1.5 py-0.5 font-mono text-[10px] tracking-[0.1em] text-destructive">
      <X className="size-2.5" strokeWidth={2.5} /> DISABLED
    </span>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

function CustomizePage() {
  const { user } = useSession();
  const isAdmin = user?.role?.toLowerCase().includes("admin") ?? false;
  const ROLE_KEY = "DIGITAL_MARKETING_MANAGER";

  const { data: remoteConfig, isLoading, isError } = useRoleConfig(ROLE_KEY);
  const { data: activeBlueprint, isLoading: blueprintLoading } = useActiveBlueprint(ROLE_KEY);
  const updateConfig = useUpdateRoleConfig(ROLE_KEY);

  // Local draft — initialised from remote once loaded
  const [draft, setDraft] = useState<RoleConfigFull | null>(null);
  const [blueprintOpen, setBlueprintOpen] = useState(false);

  useEffect(() => {
    if (remoteConfig && !draft) {
      setDraft(remoteConfig);
    }
  }, [remoteConfig, draft]);

  if (isLoading || !draft) {
    return (
      <AppShell>
        <div className="flex h-full items-center justify-center">
          <RefreshCw className="size-5 animate-spin text-muted-foreground" />
          <span className="ml-2 text-[13px] text-muted-foreground">Loading role configuration…</span>
        </div>
      </AppShell>
    );
  }

  if (isError) {
    return (
      <AppShell>
        <div className="flex h-full items-center justify-center">
          <p className="text-[13px] text-destructive">Failed to load role configuration. Check backend connection.</p>
        </div>
      </AppShell>
    );
  }

  function cycleGovernance(idx: number) {
    if (!draft) return;
    const scopes = [...draft.tool_scopes];
    const current = scopes[idx]!.governance;
    const next = GOVERNANCE_CYCLE[(GOVERNANCE_CYCLE.indexOf(current) + 1) % GOVERNANCE_CYCLE.length]!;
    scopes[idx] = { ...scopes[idx]!, governance: next };
    // Recompute allowed/guarded from scopes
    const allowed = scopes.filter((s) => s.governance === "enabled").map((s) => s.tool_key);
    const guarded = scopes.filter((s) => s.governance === "requires_approval").map((s) => s.tool_key);
    setDraft({ ...draft, tool_scopes: scopes, allowed_tools: allowed, guarded_tools: guarded });
  }

  async function save() {
    if (!draft) return;
    await updateConfig.mutateAsync({
      role_name: draft.role_name,
      agent_name: draft.agent_name,
      description: draft.description,
      responsibilities: draft.responsibilities,
      objectives: draft.objectives,
      instructions: draft.instructions,
      tool_scopes: draft.tool_scopes,
      capabilities: draft.capabilities,
      permissions: draft.permissions,
      workflows: draft.workflows,
      monitoring_rules: draft.monitoring_rules,
      communication_style: draft.communication_style,
      schedule_preferences: draft.schedule_preferences,
      memory_settings: draft.memory_settings,
      llm_model: draft.llm_model,
      autonomy_level: draft.autonomy_level,
      quick_prompts: draft.quick_prompts,
    });
    toast.success("Role configuration saved");
  }

  const blueprintPreview = activeBlueprint
    ? JSON.stringify({
        role_key: activeBlueprint.role_key,
        agent_id: activeBlueprint.agent_id,
        system_persona: activeBlueprint.system_persona.slice(0, 120) + "…",
        allowed_tools: activeBlueprint.allowed_tools,
        guarded_tools: activeBlueprint.guarded_tools,
        llm_model: activeBlueprint.llm_model,
      }, null, 2)
    : "Loading…";

  return (
    <AppShell>
      <div className="p-4">
        <PageHeader
          title="Customize"
          subtitle="The company defines who the AI employee is, what it may touch and how far it may act alone."
          actions={
            <button
              onClick={() => void save()}
              disabled={updateConfig.isPending}
              className="border border-primary px-3 py-1.5 font-mono text-[10px] tracking-[0.14em] text-primary hover:bg-primary/10 disabled:opacity-40"
            >
              {updateConfig.isPending ? "SAVING…" : "SAVE CONFIGURATION"}
            </button>
          }
        />

        <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-3">
          {/* Admin AI Control Center — Company Admin only */}
          {isAdmin && (
            <Panel title="Admin AI Control Center" className="xl:col-span-3"
              actions={<span className="font-mono text-[10px] tracking-[0.1em] text-muted-foreground">ADMIN ONLY</span>}>
              <div className="p-3"><AdminCustomizePanel /></div>
            </Panel>
          )}
          <Panel title="AI identity">
            <label className="label-xs">Agent name</label>
            <input
              value={draft.agent_name}
              onChange={(e) => setDraft({ ...draft, agent_name: e.target.value })}
              className="mb-3 mt-1 h-8 w-full border border-input bg-background px-2 text-sm outline-none focus:border-ring"
            />
            <label className="label-xs">Professional role</label>
            <input
              value={draft.role_name}
              onChange={(e) => setDraft({ ...draft, role_name: e.target.value })}
              className="mb-3 mt-1 h-8 w-full border border-input bg-background px-2 text-sm outline-none focus:border-ring"
            />
            <label className="label-xs">Description</label>
            <textarea
              value={draft.description}
              onChange={(e) => setDraft({ ...draft, description: e.target.value })}
              rows={3}
              className="mb-3 mt-1 w-full resize-none border border-input bg-background p-2 text-[13px] outline-none focus:border-ring"
            />
            <label className="label-xs">Communication style</label>
            <div className="mt-1 flex gap-1.5">
              {(["Formal", "Concise", "Consultative"] as const).map((t) => (
                <button
                  key={t}
                  onClick={() => setDraft({ ...draft, communication_style: t })}
                  className={cn(
                    "border px-2 py-1 font-mono text-[10px] tracking-[0.1em]",
                    draft.communication_style === t ? "border-primary text-primary" : "border-border text-muted-foreground",
                  )}
                >
                  {t.toUpperCase()}
                </button>
              ))}
            </div>
          </Panel>

          {/* Responsibilities */}
          <Panel title="Responsibilities">
            {draft.responsibilities.map((r, i) => (
              <div key={i} className="flex items-start gap-2 border-b border-border py-1.5 last:border-0">
                <span className="mt-0.5 font-mono text-[10px] text-muted-foreground">{i + 1}.</span>
                <input
                  value={r}
                  onChange={(e) => {
                    const updated = [...draft.responsibilities];
                    updated[i] = e.target.value;
                    setDraft({ ...draft, responsibilities: updated });
                  }}
                  className="flex-1 bg-transparent text-[13px] outline-none"
                />
              </div>
            ))}
          </Panel>

          {/* Objectives */}
          <Panel title="Objectives">
            {draft.objectives.map((o, i) => (
              <div key={i} className="flex items-start gap-2 border-b border-border py-1.5 last:border-0">
                <span className="mt-0.5 font-mono text-[10px] text-muted-foreground">{i + 1}.</span>
                <input
                  value={o}
                  onChange={(e) => {
                    const updated = [...draft.objectives];
                    updated[i] = e.target.value;
                    setDraft({ ...draft, objectives: updated });
                  }}
                  className="flex-1 bg-transparent text-[13px] outline-none"
                />
              </div>
            ))}
          </Panel>

          {/* Capabilities */}
          <Panel title="Capabilities">
            {Object.entries(draft.capabilities).map(([k, v]) => (
              <Toggle
                key={k}
                label={k}
                on={v}
                onClick={() => setDraft({ ...draft, capabilities: { ...draft.capabilities, [k]: !v } })}
              />
            ))}
          </Panel>

          {/* LLM Model */}
          <Panel title="LLM model">
            <p className="mb-3 text-[12px] text-muted-foreground">
              Select the language model this role uses for inference.
            </p>
            <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground/60">OpenAI</p>
            {(["gpt-4o-mini", "gpt-4o", "gpt-4-turbo", "gpt-3.5-turbo"] as const).map((m) => (
              <button
                key={m}
                onClick={() => setDraft({ ...draft, llm_model: m })}
                className={cn(
                  "mb-1.5 block w-full border-l-2 px-3 py-2 text-left transition-colors font-mono text-[12px]",
                  draft.llm_model === m ? "border-l-primary bg-surface-2 text-primary" : "border-l-border text-muted-foreground hover:bg-surface-2/50",
                )}
              >
                {m}
              </button>
            ))}
            <p className="mb-1.5 mt-3 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground/60">Google Gemini</p>
            {(["gemini-3.5-flash-lite", "gemini-3.8-flash", "gemini-2.5-flash", "gemini-1.5-flash"] as const).map((m) => (
              <button
                key={m}
                onClick={() => setDraft({ ...draft, llm_model: m })}
                className={cn(
                  "mb-1.5 block w-full border-l-2 px-3 py-2 text-left transition-colors font-mono text-[12px]",
                  draft.llm_model === m ? "border-l-primary bg-surface-2 text-primary" : "border-l-border text-muted-foreground hover:bg-surface-2/50",
                )}
              >
                {m}
              </button>
            ))}
            <p className="mt-2 text-[11px] text-muted-foreground">
              Current: <span className="text-foreground">{draft.llm_model}</span>
            </p>
          </Panel>

          {/* Memory settings */}
          <Panel title="Memory settings">
            <label className="label-xs">Conversation window (turns)</label>
            <input
              type="number"
              min={1}
              max={100}
              value={draft.memory_settings.conversation_window}
              onChange={(e) =>
                setDraft({
                  ...draft,
                  memory_settings: {
                    ...draft.memory_settings,
                    conversation_window: Number(e.target.value),
                  },
                })
              }
              className="mb-3 mt-1 h-8 w-full border border-input bg-background px-2 text-sm outline-none focus:border-ring"
            />
            <label className="label-xs">Summarise after (turns)</label>
            <input
              type="number"
              min={5}
              max={200}
              value={draft.memory_settings.summarise_after_turns}
              onChange={(e) =>
                setDraft({
                  ...draft,
                  memory_settings: {
                    ...draft.memory_settings,
                    summarise_after_turns: Number(e.target.value),
                  },
                })
              }
              className="mb-3 mt-1 h-8 w-full border border-input bg-background px-2 text-sm outline-none focus:border-ring"
            />
            <Toggle
              label="Retain tool results in context"
              on={draft.memory_settings.retain_tool_results}
              onClick={() =>
                setDraft({
                  ...draft,
                  memory_settings: {
                    ...draft.memory_settings,
                    retain_tool_results: !draft.memory_settings.retain_tool_results,
                  },
                })
              }
            />
          </Panel>

          {/* Tool scope & governance */}
          <Panel title="Tool scope & governance" className="xl:col-span-3">
            <p className="mb-3 text-[12px] text-muted-foreground">
              Controls what this agent is permitted to call. Click a badge to cycle its governance state.
              Only tools in MASTER_TOOL_REGISTRY can be enabled.
            </p>
            <div className="grid grid-cols-1 gap-px border border-border bg-border md:grid-cols-2 xl:grid-cols-3">
              {draft.tool_scopes.map((tool, idx) => (
                <div key={tool.tool_key} className="flex items-start justify-between gap-3 bg-surface px-3 py-2.5">
                  <div className="min-w-0">
                    <p className="truncate text-[13px] font-medium">{tool.name}</p>
                    <p className="mt-0.5 font-mono text-[10px] text-muted-foreground">{tool.tool_key}</p>
                    <p className="mt-0.5 text-[11px] text-muted-foreground">{tool.description}</p>
                  </div>
                  <button
                    onClick={() => cycleGovernance(idx)}
                    title="Click to cycle governance state"
                    className="mt-0.5 shrink-0"
                  >
                    <GovernanceBadge governance={tool.governance} />
                  </button>
                </div>
              ))}
            </div>
            <p className="mt-2 text-[11px] text-muted-foreground">
              Allowed: <span className="text-foreground">{draft.allowed_tools.join(", ") || "none"}</span>
              {" · "}
              Guarded: <span className="text-warning">{draft.guarded_tools.join(", ") || "none"}</span>
            </p>

            {/* Live blueprint preview */}
            <div className="mt-4">
              <button
                onClick={() => setBlueprintOpen((o) => !o)}
                className="flex items-center gap-1.5 font-mono text-[10px] tracking-[0.14em] text-primary"
              >
                <ChevronDown
                  className={cn("size-3 transition-transform", blueprintOpen && "rotate-180")}
                  strokeWidth={2}
                />
                {blueprintOpen ? "HIDE" : "SHOW"} ACTIVE BLUEPRINT JSON
                {blueprintLoading && <RefreshCw className="ml-1 size-3 animate-spin" />}
              </button>
              {blueprintOpen && (
                <pre className="mt-2 max-h-64 overflow-y-auto border border-border bg-surface-2 p-3 font-mono text-[11px] text-muted-foreground">
                  {blueprintPreview}
                </pre>
              )}
            </div>
          </Panel>

          {/* Permissions / approval rules */}
          <Panel title="Approval rules" className="xl:col-span-2">
            <div className="grid grid-cols-[1fr_auto] gap-2">
              {draft.permissions.map((p, idx) => (
                <div key={p.action} className="contents">
                  <span className="border-b border-border py-2 text-[13px]">{p.action}</span>
                  <span className="flex gap-1 border-b border-border py-1.5">
                    {(["auto", "approval", "restricted"] as const).map((m) => (
                      <button
                        key={m}
                        onClick={() =>
                          setDraft({
                            ...draft,
                            permissions: draft.permissions.map((x, i) =>
                              i === idx ? { ...x, mode: m } : x,
                            ),
                          })
                        }
                        className={cn(
                          "border px-2 py-0.5 font-mono text-[10px] tracking-[0.1em]",
                          p.mode === m
                            ? m === "restricted"
                              ? "border-destructive text-destructive"
                              : m === "approval"
                                ? "border-warning text-warning"
                                : "border-primary text-primary"
                            : "border-border text-muted-foreground",
                        )}
                      >
                        {m.toUpperCase()}
                      </button>
                    ))}
                  </span>
                </div>
              ))}
            </div>
          </Panel>

          {/* Autonomy */}
          <Panel title="Autonomy">
            <p className="mb-3 text-xs text-muted-foreground">
              Autonomy is granted by the company and can be revoked at any time. Every action stays in the audit trail.
            </p>
            {AUTONOMY.map((a) => (
              <button
                key={a.level}
                onClick={() => setDraft({ ...draft, autonomy_level: a.level })}
                className={cn(
                  "mb-1.5 block w-full border-l-2 px-3 py-2 text-left transition-colors",
                  draft.autonomy_level === a.level
                    ? "border-l-primary bg-surface-2"
                    : "border-l-border hover:bg-surface-2/50",
                )}
              >
                <div className="font-mono text-[10px] tracking-[0.14em] text-muted-foreground">LEVEL {a.level}</div>
                <div className="text-[13px] font-medium">{a.name}</div>
                <div className="mt-0.5 text-xs text-muted-foreground">{a.detail}</div>
              </button>
            ))}
          </Panel>

          {/* Workflows */}
          <Panel title="Workflows" className="xl:col-span-2">
            <div className="space-y-2">
              {draft.workflows.map((w, idx) => (
                <div key={w.id} className="flex items-center justify-between border-b border-border pb-2 last:border-0">
                  <div>
                    <p className="text-[13px] font-medium">{w.name}</p>
                    <p className="text-[11px] text-muted-foreground">{w.description}</p>
                    <p className="font-mono text-[10px] text-muted-foreground">
                      Trigger: {w.trigger}
                    </p>
                  </div>
                  <button
                    onClick={() => {
                      const updated = [...draft.workflows];
                      updated[idx] = { ...w, enabled: !w.enabled };
                      setDraft({ ...draft, workflows: updated });
                    }}
                    className={cn(
                      "border px-2 py-1 font-mono text-[10px] tracking-[0.1em]",
                      w.enabled ? "border-primary text-primary" : "border-border text-muted-foreground",
                    )}
                  >
                    {w.enabled ? "ENABLED" : "DISABLED"}
                  </button>
                </div>
              ))}
            </div>
          </Panel>

          {/* Monitoring rules */}
          <Panel title="Monitoring rules">
            <div className="space-y-2">
              {draft.monitoring_rules.map((m, idx) => (
                <div key={m.id} className="flex items-start justify-between gap-3 border-b border-border pb-2 last:border-0">
                  <div className="min-w-0">
                    <p className="text-[13px] font-medium">{m.name}</p>
                    <p className="text-[11px] text-muted-foreground">{m.condition}</p>
                    <p className="text-[11px] text-accent">→ {m.action}</p>
                  </div>
                  <button
                    onClick={() => {
                      const updated = [...draft.monitoring_rules];
                      updated[idx] = { ...m, enabled: !m.enabled };
                      setDraft({ ...draft, monitoring_rules: updated });
                    }}
                    className={cn(
                      "shrink-0 border px-2 py-1 font-mono text-[10px] tracking-[0.1em]",
                      m.enabled ? "border-primary text-primary" : "border-border text-muted-foreground",
                    )}
                  >
                    {m.enabled ? "ON" : "OFF"}
                  </button>
                </div>
              ))}
            </div>
          </Panel>

          {/* Schedule preferences */}
          <Panel title="Schedule preferences" className="xl:col-span-2">
            <div className="space-y-2">
              {draft.schedule_preferences.map((s, idx) => (
                <div key={s.task} className="flex items-center justify-between border-b border-border pb-2 last:border-0">
                  <div>
                    <p className="text-[13px] font-medium">{s.task}</p>
                    <p className="text-[11px] text-muted-foreground">{s.frequency}</p>
                  </div>
                  <button
                    onClick={() => {
                      const updated = [...draft.schedule_preferences];
                      updated[idx] = { ...s, enabled: !s.enabled };
                      setDraft({ ...draft, schedule_preferences: updated });
                    }}
                    className={cn(
                      "border px-2 py-1 font-mono text-[10px] tracking-[0.1em]",
                      s.enabled ? "border-primary text-primary" : "border-border text-muted-foreground",
                    )}
                  >
                    {s.enabled ? "ACTIVE" : "PAUSED"}
                  </button>
                </div>
              ))}
            </div>
          </Panel>

          {/* Instructions */}
          <Panel title="Instructions" className="xl:col-span-1">
            <p className="mb-2 text-[11px] text-muted-foreground">
              Additional instructions appended to the system persona. Keep concise.
            </p>
            <textarea
              value={draft.instructions}
              onChange={(e) => setDraft({ ...draft, instructions: e.target.value })}
              rows={5}
              className="w-full resize-none border border-input bg-background p-2 text-[13px] outline-none focus:border-ring"
            />
          </Panel>

          {/* Natural-Language Configuration */}
          <Panel
            title="Configure with natural language"
            className="xl:col-span-3"
            actions={
              <span className="font-mono text-[10px] tracking-[0.1em] text-muted-foreground">
                REQUIRES APPROVAL
              </span>
            }
          >
            <div className="p-3">
              <NLConfigPanel roleKey={ROLE_KEY} />
            </div>
          </Panel>

          {/* Autonomous Monitoring */}
          <Panel title="Autonomous monitoring" className="xl:col-span-3"
            actions={<span className="font-mono text-[10px] tracking-[0.1em] text-muted-foreground">TRIGGER ENGINE</span>}>
            <div className="p-3"><MonitoringPanel roleKey={ROLE_KEY} /></div>
          </Panel>

          {/* Campaign workspace */}
          <Panel title="Campaign workspace" className="xl:col-span-3"
            actions={<span className="font-mono text-[10px] tracking-[0.1em] text-muted-foreground">INTERNAL RECORDS</span>}>
            <div className="p-3"><CampaignsPanel /></div>
          </Panel>

          {/* Marketing strategy */}
          <Panel title="Marketing strategy & priorities" className="xl:col-span-3"
            actions={<span className="font-mono text-[10px] tracking-[0.1em] text-muted-foreground">DECISION INTELLIGENCE</span>}>
            <div className="p-3"><StrategyPanel /></div>
          </Panel>

          {/* Content intelligence */}
          <Panel title="Content intelligence" className="xl:col-span-3"
            actions={<span className="font-mono text-[10px] tracking-[0.1em] text-muted-foreground">GENERATE · ANALYSE</span>}>
            <div className="p-3"><ContentPanel /></div>
          </Panel>

          {/* Marketing reports */}
          <Panel title="Marketing reports" className="xl:col-span-3"
            actions={<span className="font-mono text-[10px] tracking-[0.1em] text-muted-foreground">SUMMARY</span>}>
            <div className="p-3"><ReportingPanel /></div>
          </Panel>
        </div>
      </div>
    </AppShell>
  );
}
