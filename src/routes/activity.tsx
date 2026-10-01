import { createFileRoute } from "@tanstack/react-router";
import { AppShell } from "@/components/eaawp/AppShell";
import { PageHeader, Panel } from "@/components/eaawp/Panel";
import { UnifiedActivityPanel } from "@/components/eaawp/UnifiedActivityPanel";

export const Route = createFileRoute("/activity")({
  component: ActivityPage,
});

function ActivityPage() {
  return (
    <AppShell>
      <div className="p-4 md:p-6 max-w-4xl mx-auto space-y-4">
        <PageHeader
          title="Activity Center"
          subtitle="Unified stream of agent activity, approvals, tool executions, and audit events."
        />
        <Panel>
          <UnifiedActivityPanel />
        </Panel>
      </div>
    </AppShell>
  );
}
