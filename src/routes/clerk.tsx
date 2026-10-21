import { createFileRoute } from "@tanstack/react-router";
import { AppShell } from "@/components/eaawp/AppShell";
import { ClerkPanel } from "@/components/eaawp/ClerkPanel";

export const Route = createFileRoute("/clerk")({
  component: ClerkPage,
});

function ClerkPage() {
  return (
    <AppShell>
      <ClerkPanel />
    </AppShell>
  );
}
