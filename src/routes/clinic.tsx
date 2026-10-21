import { createFileRoute } from "@tanstack/react-router";
import { AppShell } from "@/components/eaawp/AppShell";
import { ClinicPanel } from "@/components/eaawp/ClinicPanel";

export const Route = createFileRoute("/clinic")({
  component: ClinicPage,
});

function ClinicPage() {
  return (
    <AppShell>
      <ClinicPanel />
    </AppShell>
  );
}
