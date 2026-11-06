import { createFileRoute } from "@tanstack/react-router";
import { AppShell } from "@/components/eaawp/AppShell";
import { ProjectManagerPanel } from "@/components/eaawp/ProjectManagerPanel";

export const Route = createFileRoute("/projects")({
  component: ProjectsPage,
});

function ProjectsPage() {
  return (
    <AppShell>
      <ProjectManagerPanel />
    </AppShell>
  );
}
