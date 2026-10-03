import { useInsights } from "@/hooks/use-api";
import { USE_REAL_API } from "@/lib/api-client";
import { cn } from "@/lib/utils";

type ApiInsight = {
  id: string;
  severity: "critical" | "warning" | "info" | string;
  title: string;
  detail: string;
  department?: string;
  metric?: string | null;
  detected_at?: string;
};

const TONE: Record<string, string> = {
  critical: "border-l-foreground",
  warning: "border-l-border-strong",
  info: "border-l-border",
};

export function ProactiveInsights() {
  const { data, isLoading, isError } = useInsights();
  if (!USE_REAL_API) return <StateMessage>Live insights are unavailable while demo mode is enabled.</StateMessage>;
  if (isLoading) return <StateMessage>Loading company insights…</StateMessage>;
  if (isError) return <StateMessage>Could not load company insights. Check the connection and retry.</StateMessage>;
  const items = (data ?? []) as unknown as ApiInsight[];
  if (items.length === 0) return <StateMessage>No company insights have been generated yet.</StateMessage>;

  return (
    <ul className="h-full overflow-y-auto">
      {items.map((item) => (
        <li key={item.id} className={cn("border-b border-l-2 border-border px-3 py-2.5 last:border-b-0", TONE[item.severity] ?? TONE["info"])}>
          <div className="flex items-baseline justify-between gap-2">
            <span className="text-[13px] font-medium text-foreground">{item.title}</span>
            {item.metric && <span className="font-mono text-[11px] text-muted-foreground">{item.metric}</span>}
          </div>
          <p className="mt-1 text-xs text-muted-foreground">{item.detail}</p>
          <div className="mt-1 font-mono text-[10px] text-muted-foreground">
            {item.severity.toUpperCase()} · {(item.department || "COMPANY").toUpperCase()}
            {item.detected_at ? ` · ${new Date(item.detected_at).toLocaleString()}` : ""}
          </div>
        </li>
      ))}
    </ul>
  );
}

function StateMessage({ children }: { children: string }) {
  return <div className="px-3 py-6 text-center text-xs text-muted-foreground">{children}</div>;
}
