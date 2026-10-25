/**
 * Shared list for the Activity, Tasks and Insights panels. Every row is a stored record (execution plan, approval,
 * saved setup request, workflow, meeting task) with its real time and status; nothing is generated for display.
 */
import type { ReactNode } from "react";
import { USE_REAL_API } from "@/lib/api-client";
import { useWorkspaceFeed, type FeedItem } from "@/hooks/use-conversations";

const STATUS_TEXT: Record<string, string> = {
  completed: "COMPLETED",
  failed: "FAILED",
  rejected: "REJECTED",
  running: "RUNNING",
  planning: "PLANNING",
  awaiting_approval: "AWAITING APPROVAL",
  waiting_setup: "WAITING FOR SETUP",
  pending: "PENDING",
  idle: "SCHEDULED",
};

function when(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : `${iso}Z`);
  const today = new Date().toDateString() === d.toDateString();
  return today
    ? d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : d.toLocaleDateString([], { day: "numeric", month: "short" });
}

function StateMessage({ children }: { children: ReactNode }) {
  return <div className="px-3 py-6 text-center text-xs text-muted-foreground">{children}</div>;
}

export function FeedList({
  kind,
  empty,
  noun,
}: {
  kind: "activity" | "tasks" | "insights";
  empty: string;
  noun: string;
}) {
  const { data, isLoading, isError, refetch } = useWorkspaceFeed(kind);
  if (!USE_REAL_API)
    return <StateMessage>Live {noun} is unavailable while demo mode is enabled.</StateMessage>;
  if (isLoading) return <StateMessage>Loading {noun}…</StateMessage>;
  if (isError) {
    return (
      <StateMessage>
        Could not load {noun}.{" "}
        <button className="underline" onClick={() => void refetch()}>
          Try again
        </button>
      </StateMessage>
    );
  }
  if (!data?.role_key) return <StateMessage>Choose an AI employee to see its {noun}.</StateMessage>;
  if (!data.items.length) return <StateMessage>{empty}</StateMessage>;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <p className="shrink-0 border-b border-border px-3 py-1.5 font-mono text-[9px] tracking-[0.1em] text-muted-foreground">
        {data.scope === "company" ? "WHOLE COMPANY · THIS AI EMPLOYEE" : "YOURS · THIS AI EMPLOYEE"}
      </p>
      <ol className="min-h-0 flex-1 overflow-y-auto">
        {data.items.map((item: FeedItem) => (
          <li
            key={`${item.kind}-${item.id}`}
            className="border-b border-border px-3 py-2 last:border-0"
          >
            <div className="flex items-baseline justify-between gap-2">
              <span className="min-w-0 truncate text-[12px] text-foreground" title={item.title}>
                {item.title}
              </span>
              <time className="shrink-0 font-mono text-[10px] text-muted-foreground">
                {when(item.at)}
              </time>
            </div>
            <p className="mt-0.5 font-mono text-[9px] tracking-[0.06em] text-muted-foreground">
              {STATUS_TEXT[item.status] ?? item.status.replaceAll("_", " ").toUpperCase()}
            </p>
            {item.detail && <p className="mt-1 text-[11px] text-muted-foreground">{item.detail}</p>}
            {item.sources && item.sources.length > 0 && (
              <p className="mt-1 font-mono text-[9px] text-muted-foreground">
                SOURCES · {item.sources.join(" · ")}
              </p>
            )}
          </li>
        ))}
      </ol>
    </div>
  );
}
