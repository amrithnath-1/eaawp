import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { toast } from "sonner";
import { Check, Lock, X, ChevronDown } from "lucide-react";
import { AppShell } from "@/components/eaawp/AppShell";
import { PageHeader, Panel } from "@/components/eaawp/Panel";
import { agentConfigService } from "@/services";
import type { AgentConfig, AutonomyLevel, ToolGovernance, ToolScopeEntry } from "@/services/types";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/customize")({
  component: CustomizePage,
});

const AUTONOMY: { level: AutonomyLevel; name: string; detail: string }[] = [
  { level: 1, name: "Assist", detail: "Answers and prepares material only when asked." },
  { level: 2, name: "Recommend", detail: "Monitors continuously and recommends actions to humans." },
  { level: 3, name: "Execute with approval", detail: "Prepares and executes work after a human approves." },
  { level: 4, name: "Authorized autonomous execution", detail: "Executes pre-authorized action classes and reports afterwards." },
];

const GOVERNANCE_CYCLE: ToolGovernance[] = ["enabled", "requires_approval", "disabled"];

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

function GovernanceBadge({ governance }: { governance: ToolGovernance }) {
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

function blueprintJSON(cfg: AgentConfig): string {
  return JSON.stringify(
    {
      agent: { name: cfg.name, role: cfg.role, tone: cfg.tone, autonomy: cfg.autonomy },
      capabilities: cfg.capabilities,
      toolScopes: cfg.toolScopes.map((t) => ({ name: t.name, governance: t.governance })),
      permissions: cfg.permissions,
    },
    null,
    2,
  );
}

function CustomizePage() {
  const [cfg, setCfg] = useState<AgentConfig>(() => agentConfigService.get());
  const [blueprintOpen, setBlueprintOpen] = useState(false);

  function cycleGovernance(idx: number) {
    setCfg((prev) => {
      const scopes = [...prev.toolScopes];
      const current = scopes[idx]!.governance;
      const next = GOVERNANCE_CYCLE[(GOVERNANCE_CYCLE.indexOf(current) + 1) % GOVERNANCE_CYCLE.length]!;
      scopes[idx] = { ...scopes[idx]!, governance: next };
      return { ...prev, toolScopes: scopes };
    });
  }

  return (
    <AppShell>
      <div className="p-4">
        <PageHeader
          title="Customize"
          subtitle="The company defines who the AI employee is, what it may touch and how far it may act alone."
          actions={
            <button
              onClick={() => toast.success("Agent configuration saved")}
              className="border border-primary px-3 py-1.5 font-mono text-[10px] tracking-[0.14em] text-primary hover:bg-primary/10"
            >
              SAVE CONFIGURATION
            </button>
          }
        />

        <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-3">
          {/* AI Identity */}
          <Panel title="AI identity">
            <label className="label-xs">Agent name</label>
            <input
              value={cfg.name}
              onChange={(e) => setCfg({ ...cfg, name: e.target.value })}
              className="mb-3 mt-1 h-8 w-full border border-input bg-background px-2 text-sm outline-none focus:border-ring"
            />
            <label className="label-xs">Professional role</label>
            <input
              value={cfg.role}
              onChange={(e) => setCfg({ ...cfg, role: e.target.value })}
              className="mb-3 mt-1 h-8 w-full border border-input bg-background px-2 text-sm outline-none focus:border-ring"
            />
            <label className="label-xs">Description</label>
            <textarea
              value={cfg.description}
              onChange={(e) => setCfg({ ...cfg, description: e.target.value })}
              rows={4}
              className="mb-3 mt-1 w-full resize-none border border-input bg-background p-2 text-[13px] outline-none focus:border-ring"
            />
            <label className="label-xs">Communication style</label>
            <div className="mt-1 flex gap-1.5">
              {(["Formal", "Concise", "Consultative"] as const).map((t) => (
                <button
                  key={t}
                  onClick={() => setCfg({ ...cfg, tone: t })}
                  className={cn(
                    "border px-2 py-1 font-mono text-[10px] tracking-[0.1em]",
                    cfg.tone === t ? "border-primary text-primary" : "border-border text-muted-foreground",
                  )}
                >
                  {t.toUpperCase()}
                </button>
              ))}
            </div>
          </Panel>

          {/* Capabilities */}
          <Panel title="Capabilities">
            {Object.entries(cfg.capabilities).map(([k, v]) => (
              <Toggle
                key={k}
                label={k}
                on={v}
                onClick={() => setCfg({ ...cfg, capabilities: { ...cfg.capabilities, [k]: !v } })}
              />
            ))}
          </Panel>

          {/* Tools & systems */}
          <Panel title="Tools & systems">
            {Object.entries(cfg.tools).map(([k, v]) => (
              <Toggle key={k} label={k} on={v} onClick={() => setCfg({ ...cfg, tools: { ...cfg.tools, [k]: !v } })} />
            ))}
          </Panel>

          {/* ── Feature 1: Tool Scope & Governance ── */}
          <Panel title="Tool scope & governance" className="xl:col-span-3">
            <p className="mb-3 text-[12px] text-muted-foreground">
              Controls what this agent is permitted to call. Click a badge to cycle its governance state.
              Changes are reflected in the Blueprint JSON below.
            </p>
            <div className="grid grid-cols-1 gap-px border border-border bg-border md:grid-cols-2 xl:grid-cols-3">
              {cfg.toolScopes.map((tool: ToolScopeEntry, idx: number) => (
                <div key={tool.name} className="flex items-start justify-between gap-3 bg-surface px-3 py-2.5">
                  <div className="min-w-0">
                    <p className="truncate text-[13px] font-medium">{tool.name}</p>
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

            {/* Blueprint JSON output */}
            <div className="mt-4">
              <button
                onClick={() => setBlueprintOpen((o) => !o)}
                className="flex items-center gap-1.5 font-mono text-[10px] tracking-[0.14em] text-primary"
              >
                <ChevronDown
                  className={cn("size-3 transition-transform", blueprintOpen && "rotate-180")}
                  strokeWidth={2}
                />
                {blueprintOpen ? "HIDE" : "SHOW"} AGENT BLUEPRINT JSON
              </button>
              {blueprintOpen && (
                <pre className="mt-2 max-h-64 overflow-y-auto border border-border bg-surface-2 p-3 font-mono text-[11px] text-muted-foreground">
                  {blueprintJSON(cfg)}
                </pre>
              )}
            </div>
          </Panel>

          {/* Permissions */}
          <Panel title="Permissions" className="xl:col-span-2">
            <div className="grid grid-cols-[1fr_auto] gap-2">
              {cfg.permissions.map((p, idx) => (
                <div key={p.action} className="contents">
                  <span className="border-b border-border py-2 text-[13px]">{p.action}</span>
                  <span className="flex gap-1 border-b border-border py-1.5">
                    {(["auto", "approval", "restricted"] as const).map((m) => (
                      <button
                        key={m}
                        onClick={() =>
                          setCfg({
                            ...cfg,
                            permissions: cfg.permissions.map((x, i) => (i === idx ? { ...x, mode: m } : x)),
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
                onClick={() => setCfg({ ...cfg, autonomy: a.level })}
                className={cn(
                  "mb-1.5 block w-full border-l-2 px-3 py-2 text-left transition-colors",
                  cfg.autonomy === a.level ? "border-l-primary bg-surface-2" : "border-l-border hover:bg-surface-2/50",
                )}
              >
                <div className="font-mono text-[10px] tracking-[0.14em] text-muted-foreground">LEVEL {a.level}</div>
                <div className="text-[13px] font-medium">{a.name}</div>
                <div className="mt-0.5 text-xs text-muted-foreground">{a.detail}</div>
              </button>
            ))}
          </Panel>
        </div>
      </div>
    </AppShell>
  );
}
