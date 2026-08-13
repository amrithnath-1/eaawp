import { createFileRoute } from "@tanstack/react-router";
import { AppShell } from "@/components/eaawp/AppShell";
import { PageHeader } from "@/components/eaawp/Panel";
import { recentService } from "@/services";

export const Route = createFileRoute("/recents")({
  head: () => ({
    meta: [
      { title: "Recents — EAAWP" },
      { name: "description", content: "Recently accessed AI tasks, reports, documents and department interactions in the workspace." },
      { property: "og:title", content: "Recents — EAAWP" },
      { property: "og:description", content: "Your recent workspace items." },
    ],
  }),
  component: RecentsPage,
});

function RecentsPage() {
  const items = recentService.list();
  return (
    <AppShell>
      <div className="p-4">
        <PageHeader title="Recents" subtitle="Last touched by you in this environment." />
        <ul className="mt-4 border border-border">
          {items.map((i) => (
            <li key={i.id} className="grid grid-cols-[1fr_110px_110px] items-center gap-3 border-b border-border px-3 py-2 last:border-0 hover:bg-surface">
              <span className="truncate text-[13px]">{i.label}</span>
              <span className="font-mono text-[10px] tracking-[0.12em] text-muted-foreground">{i.type.toUpperCase()}</span>
              <span className="font-mono text-[11px] text-muted-foreground">{i.at}</span>
            </li>
          ))}
        </ul>
      </div>
    </AppShell>
  );
}
