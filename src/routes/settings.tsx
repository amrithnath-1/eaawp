import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { AppShell } from "@/components/eaawp/AppShell";
import { KeyValue, PageHeader, Panel } from "@/components/eaawp/Panel";
import { departments } from "@/services/mockData";
import { agentConfigService } from "@/services";
import { useSession } from "@/state/session";
import { useTheme } from "@/state/theme";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/settings")({
  head: () => ({
    meta: [
      { title: "Workspace settings — EAAWP" },
      { name: "description", content: "Company details, departments, AI configuration summary, security controls and notification preferences." },
      { property: "og:title", content: "Workspace settings — EAAWP" },
      { property: "og:description", content: "Company, AI, security and notification settings." },
    ],
  }),
  component: SettingsPage,
});

const TABS = ["Company", "Appearance", "AI", "Security", "Notifications"] as const;

function SettingsPage() {
  const [tab, setTab] = useState<(typeof TABS)[number]>("Company");
  const { company, user } = useSession();
  const cfg = agentConfigService.get();
  const { theme, setTheme } = useTheme();

  return (
    <AppShell>
      <div className="p-4">
        <PageHeader title="Settings" subtitle="Environment configuration for this company." />
        <div className="mt-3 flex gap-1.5">
          {TABS.map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={cn(
                "border px-3 py-1.5 font-mono text-[10px] tracking-[0.14em]",
                tab === t ? "border-foreground text-foreground" : "border-border text-muted-foreground hover:text-foreground",
              )}
            >
              {t.toUpperCase()}
            </button>
          ))}
        </div>

        <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
          {tab === "Company" && (
            <>
              <Panel title="Company details">
                <KeyValue k="Name" v={company?.name ?? "—"} />
                <KeyValue k="Industry" v={company?.industry ?? "—"} />
                <KeyValue k="Region" v={company?.region ?? "—"} />
                <KeyValue k="Employees" v={company?.employees ?? "—"} />
                <KeyValue k="Working hours" v="08:00 – 18:00 · AI 24×7" />
              </Panel>
              <Panel title="Departments / endpoints">
                {departments.map((d) => (
                  <KeyValue key={d.key} k={d.name} v={d.systems.join(" · ")} />
                ))}
              </Panel>
            </>
          )}

          {tab === "Appearance" && (
            <Panel title="Theme" className="lg:col-span-2">
              <p className="text-xs text-muted-foreground">
                Monochrome enterprise palette. Choose the surface brightness for this browser.
              </p>
              <div className="mt-3 flex gap-1.5">
                {(["dark", "light"] as const).map((t) => (
                  <button
                    key={t}
                    onClick={() => setTheme(t)}
                    className={cn(
                      "border px-3 py-1.5 font-mono text-[10px] tracking-[0.14em]",
                      theme === t
                        ? "border-foreground text-foreground"
                        : "border-border text-muted-foreground hover:text-foreground",
                    )}
                  >
                    {t.toUpperCase()} MODE
                  </button>
                ))}
              </div>
            </Panel>
          )}

          {tab === "AI" && (
            <>
              <Panel title="AI identity">
                <KeyValue k="Agent" v={cfg.name} />
                <KeyValue k="Role" v={cfg.role} />
                <KeyValue k="Style" v={cfg.tone} />
                <KeyValue k="Autonomy" v={`Level ${cfg.autonomy}`} />
              </Panel>
              <Panel title="Capabilities enabled">
                {Object.entries(cfg.capabilities).map(([k, v]) => (
                  <KeyValue key={k} k={k} v={v ? "ON" : "OFF"} />
                ))}
              </Panel>
            </>
          )}

          {tab === "Security" && (
            <>
              <Panel title="Authentication & access">
                <KeyValue k="Signed in as" v={user?.email ?? "—"} />
                <KeyValue k="Role" v={user?.role ?? "—"} />
                <KeyValue k="SSO" v="Enforced" />
                <KeyValue k="Active sessions" v="3" />
              </Panel>
              <Panel title="Keys & audit">
                <KeyValue k="API keys" v="2 active" />
                <KeyValue k="Audit retention" v="24 months" />
                <KeyValue k="External API access" v="Disabled" />
              </Panel>
            </>
          )}

          {tab === "Notifications" && (
            <Panel title="Notification channels" className="lg:col-span-2">
              {["Email", "In-app", "AI alerts", "Task completion", "Approval requests"].map((n) => (
                <KeyValue key={n} k={n} v="Enabled" />
              ))}
            </Panel>
          )}
        </div>
      </div>
    </AppShell>
  );
}
