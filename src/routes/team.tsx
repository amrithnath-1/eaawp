import { createFileRoute } from "@tanstack/react-router";
import { AppShell } from "@/components/eaawp/AppShell";
import { TeamPanel } from "@/components/eaawp/TeamPanel";

export const Route = createFileRoute("/team")({
  component: TeamPage,
});

function TeamPage() {
  return (
    <AppShell>
      <TeamPanel />
    </AppShell>
  );
}
