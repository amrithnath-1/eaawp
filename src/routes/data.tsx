import { createFileRoute } from "@tanstack/react-router";
import { AppShell } from "@/components/eaawp/AppShell";
import { DataAnalystPanel } from "@/components/eaawp/DataAnalystPanel";

export const Route = createFileRoute("/data")({
  component: DataPage,
});

function DataPage() {
  return (
    <AppShell>
      <DataAnalystPanel />
    </AppShell>
  );
}
