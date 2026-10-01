import { createFileRoute } from "@tanstack/react-router";
import { AppShell } from "@/components/eaawp/AppShell";
import { PageHeader, Panel } from "@/components/eaawp/Panel";
import { ApprovalCenterPanel } from "@/components/eaawp/ApprovalCenterPanel";

export const Route = createFileRoute("/approvals")({
  component: ApprovalsPage,
});

function ApprovalsPage() {
  return (
    <AppShell>
      <div className="p-4 md:p-6 max-w-3xl mx-auto space-y-4">
        <PageHeader
          title="Approval Center"
          subtitle="Review and approve or reject high-risk actions requested by AI employees."
        />
        <Panel>
          <ApprovalCenterPanel />
        </Panel>
      </div>
    </AppShell>
  );
}
