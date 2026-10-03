import { useActivityFeed } from "@/hooks/use-api";
import { USE_REAL_API } from "@/lib/api-client";
import type { ReactNode } from "react";

type ApiActivity = {
  id: string;
  kind: string;
  text: string;
  department?: string | null;
  created_at?: string;
};

export function ActivityStream() {
  const { data, isLoading, isError } = useActivityFeed();
  if (!USE_REAL_API) return <StateMessage>Live activity is unavailable while demo mode is enabled.</StateMessage>;
  if (isLoading) return <StateMessage>Loading company activity…</StateMessage>;
  if (isError) return <StateMessage>Could not load company activity. Check the connection and retry.</StateMessage>;
  const events = (data ?? []) as unknown as ApiActivity[];
  if (events.length === 0) return <StateMessage>No company activity has been recorded yet.</StateMessage>;

  return (
    <ol className="h-full overflow-y-auto">
      {events.map((event) => (
        <li key={event.id} className="grid grid-cols-[46px_10px_1fr] items-start gap-2 border-b border-border px-3 py-2 last:border-0">
          <time className="pt-0.5 font-mono text-[10px] text-muted-foreground">
            {event.created_at ? new Date(event.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "—"}
          </time>
          <span className="mt-1.5 block h-px w-2.5 bg-border-strong" />
          <div>
            <p className="text-[13px] leading-snug">{event.text}</p>
            {event.department && <span className="label-xs mt-1 block">{event.department} · {event.kind}</span>}
          </div>
        </li>
      ))}
    </ol>
  );
}

function StateMessage({ children }: { children: ReactNode }) {
  return <div className="px-3 py-6 text-center text-xs text-muted-foreground">{children}</div>;
}
