import { createFileRoute } from "@tanstack/react-router";
import { AppShell } from "@/components/eaawp/AppShell";
import { DataConnectionsPanel } from "@/components/eaawp/DataConnectionsPanel";
import { EmailIntegrationPanel } from "@/components/eaawp/EmailIntegrationPanel";
import { useSession } from "@/state/session";

export const Route = createFileRoute("/connections")({
  component: ConnectionsPage,
});

function ConnectionsPage() {
  const { user } = useSession();
  const isAdmin = user?.role === "Company Admin" || user?.role === "AI Administrator";
  return (
    <AppShell>
      <div className="mx-auto max-w-5xl space-y-10 p-4 sm:p-6">
        <header>
          <h1 className="text-lg font-semibold">Company connections</h1>
          <p className="text-[12px] text-muted-foreground">Connect your databases and your email sender. Credentials are encrypted and never shown again.</p>
        </header>
        {!isAdmin ? <p role="alert" className="text-[13px] text-muted-foreground">Only company administrators can manage connections.</p> : (
          <>
            <section aria-label="Databases"><DataConnectionsPanel /></section>
            <section aria-label="Email" className="border-t border-border pt-8">
              <h2 className="mb-1 font-mono text-xs tracking-[0.2em] text-muted-foreground">EMAIL (SMTP)</h2>
              <EmailIntegrationPanel />
            </section>
          </>
        )}
      </div>
    </AppShell>
  );
}
