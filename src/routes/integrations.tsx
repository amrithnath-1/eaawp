import { createFileRoute } from "@tanstack/react-router";
import { useState, useEffect } from "react";
import { toast } from "sonner";
import { Plug, Search, BarChart2, Github, Server } from "lucide-react";
import { AppShell } from "@/components/eaawp/AppShell";
import { PageHeader, Panel } from "@/components/eaawp/Panel";
import { NLIntegrationPanel } from "@/components/eaawp/NLIntegrationPanel";
import { GoogleSearchConsolePanel } from "@/components/eaawp/GoogleSearchConsolePanel";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/integrations")({
  component: IntegrationsPage,
});

type Tab = "setup" | "gsc" | "analytics" | "github" | "mcp";

const TABS: { id: Tab; label: string; icon: React.ElementType }[] = [
  { id: "setup",     label: "Setup Assistant",          icon: Plug },
  { id: "gsc",       label: "Search Console",           icon: Search },
  { id: "analytics", label: "Google Analytics",         icon: BarChart2 },
  { id: "github",    label: "GitHub",                   icon: Github },
  { id: "mcp",       label: "MCP Server",               icon: Server },
];

function IntegrationsPage() {
  const [activeTab, setActiveTab] = useState<Tab>("setup");

  // Handle OAuth callback redirect params
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const success = params.get("success");
    const error = params.get("error");
    const provider = params.get("integration");
    if (success === "true") {
      toast.success(`Integration connected successfully.`);
      // Navigate to the relevant tab
      if (provider === "google_analytics") setActiveTab("analytics");
      else if (provider === "google_search_console") setActiveTab("gsc");
      // Clean URL
      window.history.replaceState({}, "", window.location.pathname);
    } else if (error) {
      toast.error(`Authorization failed: ${params.get("error_description") ?? error}`);
      window.history.replaceState({}, "", window.location.pathname);
    }
  }, []);

  return (
    <AppShell>
      <div className="p-4 md:p-6 max-w-4xl mx-auto space-y-4">
        <PageHeader
          title="Integration Manager"
          subtitle="Connect external services and manage capability grants for your AI employees."
        />

        {/* Tab bar */}
        <div className="flex flex-wrap gap-1 border-b border-border pb-2">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={cn(
                "inline-flex items-center gap-1.5 border px-3 py-1 font-mono text-[10px] tracking-[0.08em]",
                activeTab === tab.id
                  ? "border-foreground/30 bg-foreground/5 text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              )}
            >
              <tab.icon className="size-3" />
              {tab.label}
            </button>
          ))}
        </div>

        {/* Tab content */}
        <Panel>
          {activeTab === "setup" && <NLIntegrationPanel />}
          {activeTab === "gsc" && <GoogleSearchConsolePanel />}
          {activeTab === "analytics" && (
            <div className="space-y-3">
              <p className="font-mono text-[10px] tracking-[0.14em] text-muted-foreground">
                GOOGLE ANALYTICS
              </p>
              <p className="text-[13px] text-foreground">
                Connect Google Analytics 4 to give AI employees access to traffic,
                engagement, and conversion data.
              </p>
              <p className="text-[12px] text-muted-foreground">
                Uses the same Google OAuth credentials as Search Console.
                Scope: <span className="font-mono text-[10px]">analytics.readonly</span>
              </p>
              <button
                onClick={() => {
                  window.location.href = `${import.meta.env["VITE_API_BASE_URL"] ?? "http://localhost:8000"}/api/v1/oauth/google/analytics/authorize`;
                }}
                className="inline-flex items-center gap-2 border border-foreground/20 bg-foreground/5 px-3 py-1.5 font-mono text-[11px] tracking-[0.08em] hover:bg-foreground/10"
              >
                <BarChart2 className="size-3.5" /> CONNECT GOOGLE ANALYTICS
              </button>
            </div>
          )}
          {activeTab === "github" && (
            <div className="space-y-3">
              <p className="font-mono text-[10px] tracking-[0.14em] text-muted-foreground">
                GITHUB
              </p>
              <p className="text-[13px] text-foreground">
                Connect GitHub using a Personal Access Token (PAT).
                Supports read access to repositories, issues, and pull requests.
              </p>
              <p className="text-[12px] text-muted-foreground">
                Write capabilities (create issue, create PR) require human approval.
              </p>
              <div className="border border-border bg-surface p-3 space-y-2">
                <p className="font-mono text-[10px] text-muted-foreground">MANUAL SETUP REQUIRED</p>
                <ol className="text-[12px] text-muted-foreground space-y-1">
                  <li>1. Create a PAT at github.com/settings/tokens (select repo scope)</li>
                  <li>2. Go to Integrations → use the Integration Manager API</li>
                  <li>3. POST /api/v1/integration-manager/integrations with provider_type=github and credentials&#123;github_token&#125;</li>
                </ol>
              </div>
            </div>
          )}
          {activeTab === "mcp" && (
            <div className="space-y-3">
              <p className="font-mono text-[10px] tracking-[0.14em] text-muted-foreground">
                MCP SERVER
              </p>
              <p className="text-[13px] text-foreground">
                Connect any Model Context Protocol (MCP) server to expose its tools
                as capabilities for your AI employees.
              </p>
              <p className="text-[12px] text-muted-foreground">
                All discovered tools require an explicit capability grant before any
                AI employee can use them. Risk is auto-classified by tool name prefix.
              </p>
              <div className="border border-border bg-surface p-3 space-y-2">
                <p className="font-mono text-[10px] text-muted-foreground">MANUAL SETUP REQUIRED</p>
                <ol className="text-[12px] text-muted-foreground space-y-1">
                  <li>1. Deploy your MCP server with HTTP transport</li>
                  <li>2. POST /api/v1/integration-manager/integrations with:</li>
                  <li className="ml-4 font-mono text-[10px]">provider_type: "mcp", credentials: &#123;server_url, api_key&#125;</li>
                  <li>3. POST …/test to discover available tools</li>
                  <li>4. Grant capabilities to AI employees as needed</li>
                </ol>
              </div>
            </div>
          )}
        </Panel>
      </div>
    </AppShell>
  );
}
