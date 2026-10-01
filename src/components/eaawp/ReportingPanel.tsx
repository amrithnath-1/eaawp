/**
 * ReportingPanel — Marketing Summary Report
 * Shows deterministic summary from backend. No fabricated metrics.
 */
import { useState } from "react";
import { BarChart2, Info, Loader2, RefreshCw } from "lucide-react";
import { cn } from "@/lib/utils";
import { USE_REAL_API } from "@/lib/api-client";
import { useMarketingSummary } from "@/hooks/use-api";

function StatRow({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="flex items-center justify-between border-b border-border py-1.5 last:border-0">
      <span className="text-[12px] text-muted-foreground">{label}</span>
      <span className="font-mono text-[12px] text-foreground">{value}</span>
    </div>
  );
}

export function ReportingPanel() {
  const [period, setPeriod] = useState(7);
  const { data, isLoading, refetch, isFetching } = useMarketingSummary(period);

  return (
    <div className="space-y-3">
      {!USE_REAL_API && (
        <div className="flex gap-2 border border-border bg-surface-2 p-2 text-[11px] text-muted-foreground">
          <Info className="size-3.5 shrink-0 mt-0.5" strokeWidth={1.5} />
          <span><strong>Simulated mode</strong> — reports require VITE_USE_REAL_API=true.</span>
        </div>
      )}
      <div className="flex items-center gap-2">
        {[7, 30, 90].map(d => (
          <button key={d} onClick={() => setPeriod(d)}
            className={cn("border px-2 py-0.5 font-mono text-[10px] tracking-widest",
              period === d ? "border-primary text-primary" : "border-border text-muted-foreground")}>
            {d}D
          </button>
        ))}
        <button onClick={() => void refetch()} disabled={isFetching}
          className="ml-auto border border-border px-1.5 py-0.5 text-muted-foreground hover:text-foreground disabled:opacity-40">
          <RefreshCw className={cn("size-3", isFetching && "animate-spin")} strokeWidth={1.5} />
        </button>
      </div>
      {isLoading ? (
        <div className="flex items-center gap-2 text-[12px] text-muted-foreground">
          <Loader2 className="size-4 animate-spin" />Loading report…
        </div>
      ) : data ? (
        <div className="space-y-3">
          <p className="text-[11px] text-muted-foreground">
            Generated: {new Date(data.generated_at).toLocaleString()} · {data.note}
          </p>
          <div className="border border-border px-3 py-2">
            <p className="label-xs mb-2">Campaigns</p>
            <StatRow label="Total" value={data.campaigns.total} />
            <StatRow label="Active" value={data.campaigns.active} />
            <StatRow label="Metrics recorded" value={data.metrics_recorded} />
          </div>
          <div className="border border-border px-3 py-2">
            <p className="label-xs mb-2">Objectives</p>
            <StatRow label="Total" value={data.objectives.total} />
            <StatRow label="Active" value={data.objectives.active} />
            <StatRow label="Achieved" value={data.objectives.achieved} />
          </div>
          <div className="border border-border px-3 py-2">
            <p className="label-xs mb-2">Content</p>
            <StatRow label="Total items" value={data.content.total} />
            {Object.entries(data.content.by_type).map(([k, v]) => (
              <StatRow key={k} label={k} value={v as number} />
            ))}
          </div>
          <div className="border border-border px-3 py-2">
            <p className="label-xs mb-2">Monitoring</p>
            <StatRow label="Evaluations" value={data.monitoring.evaluations} />
            <StatRow label="Triggered" value={data.monitoring.triggered} />
          </div>
        </div>
      ) : (
        <div className="border border-border bg-surface-2 p-5 text-center text-[13px] text-muted-foreground">
          <BarChart2 className="mx-auto mb-2 size-8 opacity-30" strokeWidth={1} />
          <p>No report data available.</p>
        </div>
      )}
    </div>
  );
}
