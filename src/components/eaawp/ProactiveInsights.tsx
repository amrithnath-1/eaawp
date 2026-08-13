import { useState } from "react";
import { toast } from "sonner";
import { departmentName, insightService } from "@/services";
import type { Insight } from "@/services/types";
import { cn } from "@/lib/utils";

// Monochrome severity: expressed by border weight and a small label, never colour.
const TONE: Record<Insight["severity"], string> = {
  critical: "border-l-foreground",
  warning: "border-l-border-strong",
  info: "border-l-border",
};

const SEVERITY_LABEL: Record<Insight["severity"], string> = {
  critical: "HIGH",
  warning: "MEDIUM",
  info: "LOW",
};

export function ProactiveInsights() {
  const [items, setItems] = useState<Insight[]>(() => insightService.list());

  return (
    <ul className="h-full overflow-y-auto">
      {items.map((i) => (
        <li key={i.id} className={cn("border-b border-l-2 border-border px-3 py-2.5 last:border-b-0", TONE[i.severity])}>
          <div className="flex items-baseline justify-between gap-2">
            <span className="text-[13px] font-medium text-foreground">{i.title}</span>
            {i.metric && <span className="font-mono text-[11px] text-muted-foreground">{i.metric}</span>}
          </div>
          <p className="mt-1 text-xs text-muted-foreground">{i.detail}</p>
          <div className="mt-1 font-mono text-[10px] text-muted-foreground">
            {SEVERITY_LABEL[i.severity]} · {departmentName(i.department).toUpperCase()} · DETECTED {i.detectedAt} ·
            UNPROMPTED
          </div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {["View", "Investigate", "Ask AI", "Approve"].map((a) => (
              <button
                key={a}
                onClick={() => toast.success(`${a} · ${i.title}`)}
                className="border border-border px-2 py-1 font-mono text-[10px] tracking-[0.12em] text-muted-foreground hover:border-border-strong hover:text-foreground"
              >
                {a.toUpperCase()}
              </button>
            ))}
            <button
              onClick={() => setItems((prev) => prev.filter((x) => x.id !== i.id))}
              className="border border-border px-2 py-1 font-mono text-[10px] tracking-[0.12em] text-muted-foreground hover:text-destructive"
            >
              DISMISS
            </button>
          </div>
        </li>
      ))}
      {items.length === 0 && (
        <li className="px-3 py-6 text-center font-mono text-[11px] text-muted-foreground">No open insights</li>
      )}
    </ul>
  );
}
