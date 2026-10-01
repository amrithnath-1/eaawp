import { createFileRoute } from "@tanstack/react-router";
import { AppShell } from "@/components/eaawp/AppShell";
import { PageHeader, Panel } from "@/components/eaawp/Panel";
import { WorkflowManagerPanel } from "@/components/eaawp/WorkflowManagerPanel";

export const Route = createFileRoute("/workflows")({
  component: WorkflowsPage,
});

function WorkflowsPage() {
  return (
    <AppShell>
      <div className="p-4 md:p-6 max-w-3xl mx-auto space-y-4">
        <PageHeader
          title="Workflow Manager"
          subtitle="Create and manage recurring or triggered workflows for your AI employees."
        />
        <Panel>
          <WorkflowManagerPanel />
        </Panel>
      </div>
    </AppShell>
  );
}
