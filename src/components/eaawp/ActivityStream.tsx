import { useEffect, useState } from "react";
import { activityService, departmentName } from "@/services";
import type { ActivityEvent } from "@/services/types";
import { cn } from "@/lib/utils";

// Monochrome timeline: hierarchy comes from weight, not colour.
const KIND_TONE: Record<ActivityEvent["kind"], string> = {
  detect: "text-foreground",
  analyze: "text-foreground",
  consult: "text-muted-foreground",
  result: "text-foreground font-medium",
  execute: "text-foreground",
  await: "text-muted-foreground italic",
};

function nowLabel() {
  return new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export function ActivityStream() {
  const [events, setEvents] = useState<ActivityEvent[]>(() => activityService.feed());

  useEffect(() => {
    const pool = activityService.candidates();
    let i = 0;
    const id = setInterval(() => {
      const next = pool[i % pool.length]!;
      i += 1;
      setEvents((prev) => [...prev.slice(-40), { ...next, id: `live-${Date.now()}`, time: nowLabel() }]);
    }, 9000);
    return () => clearInterval(id);
  }, []);

  return (
    <ol className="h-full overflow-y-auto">
      {events.map((e) => (
        <li
          key={e.id}
          className="stream-enter grid grid-cols-[46px_10px_1fr] items-start gap-2 border-b border-border px-3 py-2 last:border-0"
        >
          <time className="pt-0.5 font-mono text-[10px] text-muted-foreground">{e.time}</time>
          <span className="mt-1.5 block h-px w-2.5 bg-border-strong" />
          <div>
            <p className={cn("text-[13px] leading-snug", KIND_TONE[e.kind])}>{e.text}</p>
            {e.department && (
              <span className="label-xs mt-1 block">{departmentName(e.department)} endpoint</span>
            )}
          </div>
        </li>
      ))}
    </ol>
  );
}
