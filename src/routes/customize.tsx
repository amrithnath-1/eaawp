import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { toast } from "sonner";
import { AppShell } from "@/components/eaawp/AppShell";
import { PageHeader, Panel } from "@/components/eaawp/Panel";
import { agentConfigService } from "@/services";
import type { AgentConfig, AutonomyLevel } from "@/services/types";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/customize")({
  head: () => ({
    meta: [
      { title: "Customize the AI employee — EAAWP" },
      { name: "description", content: "Configure AI identity, capabilities, connected tools, permissions and autonomy level for your company agent." },
      { property: "og:title", content: "Customize the AI employee — EAAWP" },
      { property: "og:description", content: "Company-controlled identity, tools, permissions and autonomy." },
    ],
  }),
  component: CustomizePage,
});

const AUTONOMY: { level: AutonomyLevel; name: string; detail: string }[] = [
  { level: 1, name: "Assist", detail: "Answers and prepares material only when asked." },
  { level: 2, name: "Recommend", detail: "Monitors continuously and recommends actions to humans." },
  { level: 3, name: "Execute with approval", detail: "Prepares and executes work after a human approves." },
  { level: 4, name: "Authorized autonomous execution", detail: "Executes pre-authorized action classes and reports afterwards." },
];

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

function CustomizePage() {
  const [cfg, setCfg] = useState<AgentConfig>(() => agentConfigService.get());

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

          <Panel title="Tools & systems">
            {Object.entries(cfg.tools).map(([k, v]) => (
              <Toggle key={k} label={k} on={v} onClick={() => setCfg({ ...cfg, tools: { ...cfg.tools, [k]: !v } })} />
            ))}
          </Panel>

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
