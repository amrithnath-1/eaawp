import { useState } from "react";
import { Link } from "@tanstack/react-router";
import { ActivityStream } from "./ActivityStream";
import { ActiveTasks } from "./ActiveTasks";
import { ProactiveInsights } from "./ProactiveInsights";
import { cn } from "@/lib/utils";

const TABS = ["Activity", "Tasks", "Insights"] as const;
type Tab = (typeof TABS)[number];

const FOOTER: Record<Tab, { label: string; to: string }> = {
  Activity: { label: "View full activity", to: "/recents" },
  Tasks: { label: "View all tasks", to: "/workspace" },
  Insights: { label: "View all insights", to: "/workspace" },
};

/**
 * Contextual panel. Strictly ONE tab's content is rendered at a time.
 */
export function ContextPanel({ className }: { className?: string }) {
  const [tab, setTab] = useState<Tab>("Activity");
  const footer = FOOTER[tab];

  return (
    <section className={cn("flex min-h-0 flex-col bg-surface", className)}>
      <div className="flex h-11 shrink-0 items-stretch border-b border-border">
        {TABS.map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            aria-pressed={tab === t}
            className={cn(
              "flex-1 border-b-2 px-3 text-[12px] transition-colors",
              tab === t
                ? "border-foreground text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            {t}
          </button>
        ))}
      </div>

      <div className="min-h-0 flex-1 overflow-hidden">
        {tab === "Activity" && <ActivityStream />}
        {tab === "Tasks" && <ActiveTasks />}
        {tab === "Insights" && <ProactiveInsights />}
      </div>

      <div className="shrink-0 border-t border-border px-3 py-2">
        <Link
          to={footer.to}
          className="font-mono text-[10px] tracking-[0.14em] text-muted-foreground hover:text-foreground"
        >
          {footer.label.toUpperCase()} →
        </Link>
      </div>
    </section>
  );
}
