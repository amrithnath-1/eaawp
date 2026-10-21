/**
 * MarketplacePanel - see every AI employee module, and (administrators) switch them on or off for the company.
 * Switching a module off blocks its use; nothing is deleted, and switching it back on restores access.
 */
import { toast } from "sonner";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { useSession } from "@/state/session";
import { useModules, useSetModule, type ModuleFE } from "@/hooks/use-api";

function ModuleCard({ m, canEdit }: { m: ModuleFE; canEdit: boolean }) {
  const set = useSetModule();
  const soon = m.status === "coming_soon";
  const toggle = () => {
    if (m.active && !window.confirm(`Turn off ${m.name}? People in your company will no longer be able to use it. Nothing is deleted.`)) return;
    set.mutate({ key: m.key, active: !m.active }, {
      onSuccess: () => toast.success(`${m.name} ${m.active ? "turned off" : "turned on"}`),
      onError: (e) => toast.error(e.message),
    });
  };
  return (
    <li data-testid={`module-${m.key}`} className="flex min-w-0 flex-col gap-2 border border-border bg-surface p-4">
      <div className="flex items-start justify-between gap-2">
        <h3 className="text-[14px] font-medium">{m.name}</h3>
        <span className={cn("shrink-0 border px-1.5 py-0.5 font-mono text-[10px] tracking-[0.08em]",
          soon ? "border-border text-muted-foreground" : m.active ? "border-success/40 bg-success/10 text-success" : "border-warning/40 bg-warning/10 text-warning")}>
          {soon ? "COMING SOON" : m.active ? "ACTIVE" : "OFF"}
        </span>
      </div>
      <p className="text-[12px] text-muted-foreground">{m.description}</p>
      <div className="mt-auto flex items-center justify-between gap-2 pt-1">
        <span className="font-mono text-[10px] tracking-[0.1em] text-muted-foreground">{m.category.toUpperCase()}</span>
        {soon ? null : canEdit ? (
          <button type="button" onClick={toggle} disabled={set.isPending} aria-label={`${m.active ? "Turn off" : "Turn on"} ${m.name}`}
            className={cn("inline-flex items-center gap-1 border px-3 py-1 text-[12px] disabled:opacity-50", m.active ? "border-border hover:bg-accent" : "border-primary text-primary hover:bg-primary/10")}>
            {set.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : null}{m.active ? "Turn off" : "Turn on"}
          </button>
        ) : <span className="text-[11px] text-muted-foreground">Ask an administrator</span>}
      </div>
    </li>
  );
}

export function MarketplacePanel() {
  const { user } = useSession();
  const canEdit = user?.role === "Company Admin" || user?.role === "AI Administrator";
  const q = useModules();
  if (q.isLoading) return <p role="status" className="text-[13px] text-muted-foreground">Loading modules…</p>;
  if (q.isError) return <p role="alert" className="text-[13px] text-destructive">Could not load the marketplace. {(q.error as Error).message}</p>;
  const all = q.data ?? [];
  const live = all.filter((m) => m.status === "available");
  const soon = all.filter((m) => m.status === "coming_soon");
  return (
    <div className="space-y-8">
      <section aria-label="Available modules">
        <h2 className="mb-3 font-mono text-xs tracking-[0.2em] text-muted-foreground">AVAILABLE ({live.filter((m) => m.active).length} ON)</h2>
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{live.map((m) => <ModuleCard key={m.key} m={m} canEdit={canEdit} />)}</ul>
      </section>
      <section aria-label="Coming soon">
        <h2 className="mb-3 font-mono text-xs tracking-[0.2em] text-muted-foreground">COMING SOON</h2>
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{soon.map((m) => <ModuleCard key={m.key} m={m} canEdit={false} />)}</ul>
      </section>
    </div>
  );
}
