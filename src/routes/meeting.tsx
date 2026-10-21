import { createFileRoute } from "@tanstack/react-router";
import { AppShell } from "@/components/eaawp/AppShell";
import { MeetingRoomPanel } from "@/components/eaawp/MeetingRoomPanel";

export const Route = createFileRoute("/meeting")({
  component: MeetingRoom,
});

function MeetingRoom() {
  return (
    <AppShell>
      <MeetingRoomPanel />
    </AppShell>
  );
}
