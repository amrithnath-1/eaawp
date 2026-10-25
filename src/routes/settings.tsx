import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { AppShell } from "@/components/eaawp/AppShell";
import { KeyValue, PageHeader, Panel } from "@/components/eaawp/Panel";
import { useSession } from "@/state/session";
import { useTheme } from "@/state/theme";
import { cn } from "@/lib/utils";
import { USE_REAL_API } from "@/lib/api-client";
import { NotificationSettingsPanel } from "@/components/eaawp/NotificationSettingsPanel";
import { CompanyProfilePanel } from "@/components/eaawp/CompanyProfilePanel";
import { IS_ADMIN_ROLE } from "@/lib/workspace";

export const Route = createFileRoute("/settings")({
  component: SettingsPage,
});

const TABS = ["Company", "Appearance", "AI", "Security", "Notifications"] as const;

function SettingsPage() {
  const [tab, setTab] = useState<(typeof TABS)[number]>("Company");
  const { company, user } = useSession();
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
                <KeyValue k="Working hours" v="Not configured" />
              </Panel>
              <Panel title="Departments / endpoints">
                <p className="text-xs text-muted-foreground">No real company systems are listed here until an administrator connects and tests them in Integrations.</p>
              </Panel>
              {USE_REAL_API && <CompanyProfilePanel canEdit={IS_ADMIN_ROLE(user?.role)} />}
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
            <Panel title="AI role configuration" className="lg:col-span-2">
              <p className="text-xs text-muted-foreground">{USE_REAL_API ? "Role settings are managed in Customize. No sample capabilities are displayed here." : "Simulation mode uses sample role settings."}</p>
            </Panel>
          )}

          {tab === "Security" && (
            <>
              <Panel title="Authentication & access">
                <KeyValue k="Signed in as" v={user?.email ?? "—"} />
                <KeyValue k="Role" v={user?.role ?? "—"} />
                <KeyValue k="SSO" v="Not configured" />
                <KeyValue k="Active sessions" v="Current browser session" />
              </Panel>
              <Panel title="Keys & audit">
                <KeyValue k="API keys" v="Managed by deployment configuration" />
                <KeyValue k="Audit retention" v="Not configured" />
                <KeyValue k="External API access" v="Controlled by connected integrations" />
              </Panel>
            </>
          )}

          {tab === "Notifications" && (USE_REAL_API ? <NotificationSettingsPanel /> : (
            <Panel title="Notification channels" className="lg:col-span-2">
              <p className="text-xs text-muted-foreground">Notifications need the live API.</p>
            </Panel>
          ))}
        </div>
      </div>
    </AppShell>
  );
}
