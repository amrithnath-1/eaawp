import { createFileRoute } from "@tanstack/react-router";
import { useState, useEffect, type FormEvent } from "react";
import { toast } from "sonner";
import { Plug, Search, BarChart2, Github, Server, Loader2 } from "lucide-react";
import { AppShell } from "@/components/eaawp/AppShell";
import { PageHeader, Panel } from "@/components/eaawp/Panel";
import { McpToolsPanel } from "@/components/eaawp/McpToolsPanel";
import { NLIntegrationPanel } from "@/components/eaawp/NLIntegrationPanel";
import { GoogleSearchConsolePanel } from "@/components/eaawp/GoogleSearchConsolePanel";
import { ConnectedAccountsPanel, connectionState } from "@/components/eaawp/ConnectedAccountsPanel";
import { cn } from "@/lib/utils";
import { apiErrorMessage } from "@/lib/api-client";
import { useCapabilityGrants, useCreateIntegration, useGaAuthorize, useIntegrations, useTestIntegration, type IntegrationOut } from "@/hooks/use-api";

type Tab = "setup" | "gsc" | "analytics" | "github" | "mcp";
const TAB_FOR_PROVIDER: Record<string, Tab> = {
  google_search_console: "gsc", gsc: "gsc", google_analytics: "analytics", analytics: "analytics",
  github: "github", mcp: "mcp", setup: "setup",
};

export const Route = createFileRoute("/integrations")({
  validateSearch: (s: Record<string, unknown>): { tab?: Tab } => {
    const t = typeof s["tab"] === "string" ? TAB_FOR_PROVIDER[s["tab"]] : undefined;
    return t ? { tab: t } : {};
  },
  component: IntegrationsPage,
});

const PROVIDER_LABEL: Record<string, string> = {
  google_search_console: "Google Search Console", google_analytics: "Google Analytics", github: "GitHub",
  mcp: "MCP server", facebook: "Meta / Facebook", postgresql: "PostgreSQL", mysql: "MySQL",
};

function OverviewRow({ i, onOpen }: { i: IntegrationOut; onOpen: (t: Tab) => void }) {
  const { data: grants = [] } = useCapabilityGrants(i.id);
  const st = connectionState(i, grants.filter((g) => g.is_granted).length);
  const tab = TAB_FOR_PROVIDER[i.provider_type];
  return (
    <li className="flex flex-wrap items-center justify-between gap-2 border-b border-border py-1.5 last:border-0">
      <span className="text-[12px]">{i.display_name} <span className="text-muted-foreground">· {PROVIDER_LABEL[i.provider_type] ?? i.provider_type}</span></span>
      <span className="flex items-center gap-2">
        <span className={cn("border px-1.5 py-0.5 font-mono text-[9px]", st.tone)}>{st.label}</span>
        {tab && <button onClick={() => onOpen(tab)} className="font-mono text-[9px] underline">OPEN</button>}
      </span>
    </li>
  );
}

function ConnectionsOverview({ onOpen }: { onOpen: (t: Tab) => void }) {
  const { data, isLoading } = useIntegrations();
  return (
    <section aria-label="Connected services" className="mb-4 border border-border p-3">
      <p className="font-mono text-[10px] tracking-[0.14em] text-muted-foreground">CONNECTED SERVICES</p>
      {isLoading ? <p className="mt-1 text-[12px] text-muted-foreground">Loading…</p>
        : !data?.length ? <p className="mt-1 text-[12px] text-muted-foreground">No service is connected yet.</p>
        : <ul className="mt-1">{data.map((i) => <OverviewRow key={i.id} i={i} onOpen={onOpen} />)}</ul>}
    </section>
  );
}

const TABS: { id: Tab; label: string; icon: React.ElementType }[] = [
  { id: "setup",     label: "Setup Assistant",          icon: Plug },
  { id: "gsc",       label: "Search Console",           icon: Search },
  { id: "analytics", label: "Google Analytics",         icon: BarChart2 },
  { id: "github",    label: "GitHub",                   icon: Github },
  { id: "mcp",       label: "MCP Server",               icon: Server },
];

function IntegrationsPage() {
  const { tab: initialTab } = Route.useSearch();
  const [activeTab, setActiveTab] = useState<Tab>(initialTab ?? "setup");
  useEffect(() => { if (initialTab) setActiveTab(initialTab); }, [initialTab]);
  // The authorize endpoint needs the Bearer token, so it must be called with the
  // API client (which sends it) - never by navigating the browser to its URL.
  const gaAuth = useGaAuthorize();

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
          {activeTab === "setup" && (
            <>
              <ConnectionsOverview onOpen={setActiveTab} />
              <NLIntegrationPanel onOpenTab={(tab) => setActiveTab(tab)} />
            </>
          )}
          {activeTab === "gsc" && (
            <div className="space-y-4">
              <ConnectedAccountsPanel providerType="google_search_console" title="Search Console connections" />
              <GoogleSearchConsolePanel />
            </div>
          )}
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
                Uses the same Google OAuth client as Search Console (set it up in the Setup Assistant if
                you have not yet). Scope: <span className="font-mono text-[10px]">analytics.readonly</span>
              </p>
              <button
                disabled={gaAuth.isPending}
                onClick={() => {
                  gaAuth.mutate(undefined, {
                    onSuccess: (r) => { window.location.href = r.authorization_url; },
                    onError: (e) => toast.error(`Could not start Google authorisation: ${apiErrorMessage(e)}`),
                  });
                }}
                className="inline-flex items-center gap-2 border border-foreground/20 bg-foreground/5 px-3 py-1.5 font-mono text-[11px] tracking-[0.08em] hover:bg-foreground/10 disabled:opacity-40"
              >
                <BarChart2 className="size-3.5" /> {gaAuth.isPending ? "OPENING…" : "CONNECT GOOGLE ANALYTICS"}
              </button>
              <ConnectedAccountsPanel providerType="google_analytics" title="Google Analytics connections" />
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
                Write capabilities (create issue, create pull request) are high risk: an AI employee never runs them, even
                when granted. Grant only the read capabilities an AI employee needs.
              </p>
              <ConnectedAccountsPanel providerType="github" title="GitHub connections" />
              <ProviderConnectionForm providerType="github" title="Connect another GitHub account" tokenLabel="GitHub personal access token (fine-grained, read-only recommended)" />
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
                AI employee can use them. Each tool is granted separately, per AI employee role. Risk is classified from every word of the tool name, and high-risk tools never run automatically.
              </p>
              <ConnectedAccountsPanel providerType="mcp" title="MCP connections" />
              <ProviderConnectionForm providerType="mcp" title="Connect MCP server" />
              <McpToolsPanel />
              <p className="border border-border p-3 text-[11px] text-muted-foreground">
                EAAWP must be able to reach the server URL. A private on-premises server needs a network route or a customer-side connector; entering its address alone cannot expose it to a cloud deployment.
              </p>
            </div>
          )}
        </Panel>
      </div>
    </AppShell>
  );
}

function ProviderConnectionForm({ providerType, title, tokenLabel }: { providerType: "github" | "mcp"; title: string; tokenLabel?: string }) {
  const createIntegration = useCreateIntegration();
  const testIntegration = useTestIntegration();
  const [displayName, setDisplayName] = useState(providerType === "github" ? "GitHub" : "MCP server");
  const [secret, setSecret] = useState("");
  const [serverUrl, setServerUrl] = useState("");
  const [headerName, setHeaderName] = useState("Authorization");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  async function saveAndTest(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    try {
      const credentials: Record<string, unknown> = providerType === "github"
        ? { github_token: secret }
        : { server_url: serverUrl.trim(), ...(secret ? { api_key: secret } : {}), auth_header_name: headerName.trim() || "Authorization" };
      const created = await createIntegration.mutateAsync({
        provider_type: providerType,
        display_name: displayName.trim(),
        credentials,
      });
      setSecret("");
      const result = await testIntegration.mutateAsync(created.id);
      setMessage(result.success
        ? `Connected and verified${result.account_info?.["name"] ? ` as ${String(result.account_info["name"])}` : ""}.`
        : `Saved securely, but the connection test failed: ${result.error_message || "Check the address, permissions, and credentials."}`);
    } catch (error) {
      setSecret("");
      setMessage(error instanceof Error ? error.message : "Connection could not be saved or tested.");
    } finally {
      setBusy(false);
    }
  }

  const fieldClass = "mt-1 h-9 w-full border border-input bg-background px-2.5 text-[12px] outline-none focus:border-ring";
  return (
    <form onSubmit={(event) => void saveAndTest(event)} className="space-y-3 border border-border bg-surface p-4">
      <h3 className="font-mono text-[10px] tracking-[0.14em]">{title.toUpperCase()}</h3>
      <label className="block text-xs">Connection name<input required maxLength={255} value={displayName} onChange={(event) => setDisplayName(event.target.value)} className={fieldClass} /></label>
      {providerType === "mcp" && <label className="block text-xs">MCP HTTP server URL<input required type="url" value={serverUrl} onChange={(event) => setServerUrl(event.target.value)} placeholder="https://mcp.company.com" className={fieldClass} /></label>}
      <label className="block text-xs">{tokenLabel ?? "API key (optional if the server is unauthenticated)"}<input required={providerType === "github"} type="password" autoComplete="new-password" value={secret} onChange={(event) => setSecret(event.target.value)} className={fieldClass} /></label>
      {providerType === "mcp" && <label className="block text-xs">Authentication header name<input value={headerName} onChange={(event) => setHeaderName(event.target.value)} className={fieldClass} /></label>}
      <p className="text-[10px] text-muted-foreground">Credentials are sent directly to EAAWP for encrypted storage and are never shown back. The test result confirms connectivity; capabilities still need an explicit grant.</p>
      <button type="submit" disabled={busy} className="inline-flex h-9 items-center gap-2 border border-primary bg-primary px-3 font-mono text-[10px] tracking-widest text-primary-foreground disabled:opacity-50">
        {busy && <Loader2 className="size-3 animate-spin" />}{busy ? "SAVING AND TESTING…" : "SAVE AND TEST CONNECTION"}
      </button>
      {message && <p role="status" className="text-xs text-muted-foreground">{message}</p>}
    </form>
  );
}
