import { createFileRoute } from "@tanstack/react-router";
import { AppShell } from "@/components/eaawp/AppShell";
import { PageHeader, Panel } from "@/components/eaawp/Panel";
import { EmployeeBuilderPanel } from "@/components/eaawp/EmployeeBuilderPanel";

export const Route = createFileRoute("/employees")({
  component: EmployeesPage,
});

function EmployeesPage() {
  return (
    <AppShell>
      <div className="p-4 md:p-6 max-w-3xl mx-auto space-y-4">
        <PageHeader
          title="AI Employee Builder"
          subtitle="Create new AI employees using natural language. Describe the role and the system generates a blueprint for your approval."
        />
        <Panel>
          <EmployeeBuilderPanel />
        </Panel>
      </div>
    </AppShell>
  );
}
