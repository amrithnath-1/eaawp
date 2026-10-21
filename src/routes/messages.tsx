import { createFileRoute } from "@tanstack/react-router";
import { AppShell } from "@/components/eaawp/AppShell";
import { MessagesPanel } from "@/components/eaawp/MessagesPanel";

export const Route = createFileRoute("/messages")({
  component: MessagesPage,
});

function MessagesPage() {
  return (
    <AppShell>
      <MessagesPanel />
    </AppShell>
  );
}
