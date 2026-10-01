/**
 * CampaignPerformanceView — Marketing Performance Intelligence
 *
 * Shows deterministic KPI analysis for a selected campaign.
 * All numbers originate from the KPI engine — never LLM-fabricated.
 * Follows existing monochrome visual language.
 */

import { useState } from "react";
import {
  AlertTriangle, ArrowDown, ArrowUp, BarChart2,
  Info, Loader2, Minus, RefreshCw,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { USE_REAL_API } from "@/lib/api-client";
import {
  useCampaignPerformance,
  type PerformanceInsightFE,
  type KPIValueFE,
  type PeriodComparisonFE,
} from "@/hooks/use-api";

// ── Trend icon ────────────────────────────────────────────────────────────────

function TrendIcon({ trend, significant }: { trend: string; significant: boolean }) {
  const cls = significant ? "text-foreground" : "text-muted-foreground";
  if (trend === "up") return <ArrowUp className={cn("size-3", cls)} strokeWidth={2} />;
  if (trend === "down") return <ArrowDown className={cn("size-3 text-destructive", significant ? "" : "opacity-50")} strokeWidth={2} />;
  return <Minus className="size-3 text-muted-foreground" strokeWidth={2} />;
}

// ── KPI card ──────────────────────────────────────────────────────────────────

function KPICard({ name, kpi, comparison }: {
  name: string;
  kpi: KPIValueFE;
  comparison?: PeriodComparisonFE;
}) {
  const hasValue = kpi.value !== null;
  return (
    <div className="border border-border bg-surface p-3 flex flex-col gap-1">
      <p className="font-mono text-[9px] tracking-widest text-muted-foreground uppercase">{name}</p>
      {hasValue ? (
        <p className="text-[18px] font-medium tracking-tight">
          {kpi.value!.toFixed(kpi.unit === "%" || kpi.unit === "x" ? 2 : 2)}
          <span className="ml-0.5 text-[12px] text-muted-foreground">{kpi.unit}</span>
        </p>
      ) : (
        <p className="text-[13px] text-muted-foreground">
          N/A
          {kpi.missing_inputs.length > 0 && (
            <span className="ml-1 text-[10px]">({kpi.missing_inputs.join(", ")})</span>
          )}
        </p>
      )}
      {comparison && comparison.pct_change !== null && (
        <div className="flex items-center gap-1 text-[10px] text-muted-foreground">
          <TrendIcon trend={comparison.trend} significant={comparison.is_significant} />
          <span className={cn(comparison.pct_change > 0 ? "text-success" : "text-destructive")}>
            {comparison.pct_change > 0 ? "+" : ""}{comparison.pct_change.toFixed(1)}%
          </span>
          {comparison.is_anomaly && <AlertTriangle className="size-3 text-warning" strokeWidth={1.5} />}
        </div>
      )}
      {kpi.is_calculated && (
        <p className="text-[9px] text-muted-foreground/60">{kpi.formula}</p>
      )}
    </div>
  );
}

// ── Completeness bar ──────────────────────────────────────────────────────────

function CompletenessBar({ pct }: { pct: number }) {
  const color = pct >= 80 ? "bg-success" : pct >= 50 ? "bg-warning" : "bg-destructive";
  return (
    <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
      <span className="shrink-0">Data {pct.toFixed(0)}% complete</span>
      <div className="h-1.5 flex-1 bg-muted">
        <div className={cn("h-full transition-all", color)} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

const KPI_ORDER = ["impressions", "clicks", "ctr", "conversions", "conversion_rate",
                   "spend", "cpc", "cpm", "cpa", "revenue", "roas"];

interface Props {
  campaignId: string;
  campaignName: string;
}

export function CampaignPerformanceView({ campaignId, campaignName }: Props) {
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [applied, setApplied] = useState<{ from: string; to: string }>({ from: "", to: "" });

  const { data: insight, isLoading, isError, refetch, isFetching } = useCampaignPerformance(
    campaignId, applied.from || undefined, applied.to || undefined
  );

  if (!USE_REAL_API) {
    return (
      <div className="flex gap-2 border border-border bg-surface-2 p-3 text-[11px] text-muted-foreground">
        <Info className="size-3.5 shrink-0 mt-0.5" strokeWidth={1.5} />
        <span>
          <strong>Simulated mode</strong> — real performance analysis requires VITE_USE_REAL_API=true
          and recorded campaign metrics.
        </span>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {/* Date range filter */}
      <div className="flex flex-wrap items-end gap-2 text-[12px]">
        <div>
          <label className="label-xs">From</label>
          <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)}
            className="mt-0.5 h-7 border border-input bg-background px-2 text-[12px] outline-none focus:border-ring" />
        </div>
        <div>
          <label className="label-xs">To</label>
          <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)}
            className="mt-0.5 h-7 border border-input bg-background px-2 text-[12px] outline-none focus:border-ring" />
        </div>
        <button
          onClick={() => setApplied({ from: dateFrom, to: dateTo })}
          className="h-7 border border-primary px-3 font-mono text-[10px] tracking-widest text-primary hover:bg-primary/10">
          ANALYSE
        </button>
        <button onClick={() => void refetch()} disabled={isFetching}
          className="h-7 border border-border px-2 text-muted-foreground hover:text-foreground disabled:opacity-40">
          <RefreshCw className={cn("size-3", isFetching && "animate-spin")} strokeWidth={1.5} />
        </button>
      </div>

      {isLoading && (
        <div className="flex items-center gap-2 text-[12px] text-muted-foreground">
          <Loader2 className="size-4 animate-spin" /> Analysing…
        </div>
      )}

      {isError && (
        <div className="flex items-center gap-2 text-[12px] text-destructive">
          <AlertTriangle className="size-4 shrink-0" strokeWidth={1.5} /> Analysis failed. Check backend.
        </div>
      )}

      {insight && (
        <div className="space-y-3">
          {/* Completeness + sources */}
          <CompletenessBar pct={insight.data_completeness_pct} />
          {insight.sources.length > 0 && (
            <p className="text-[10px] text-muted-foreground">
              Sources: {insight.sources.join(" · ")}
            </p>
          )}
          {insight.analysis_note && (
            <p className="flex items-start gap-1 text-[11px] text-warning">
              <Info className="size-3.5 shrink-0 mt-0.5" strokeWidth={1.5} />
              {insight.analysis_note}
            </p>
          )}

          {/* KPI grid */}
          <div className="grid grid-cols-2 gap-1.5 md:grid-cols-3 xl:grid-cols-4">
            {KPI_ORDER.map((name) => {
              const kpi = insight.kpis[name];
              if (!kpi) return null;
              const comp = insight.comparisons.find((c) => c.kpi_name === name);
              return <KPICard key={name} name={name} kpi={kpi} {...(comp ? { comparison: comp } : {})} />;
            })}
          </div>

          {/* Anomalies */}
          {insight.anomalies.length > 0 && (
            <div className="border border-warning/30 bg-warning/5 p-3">
              <p className="mb-1 font-mono text-[10px] tracking-widest text-warning">ANOMALIES</p>
              {insight.anomalies.map((a, i) => (
                <p key={i} className="text-[12px] text-muted-foreground">⚠ {a}</p>
              ))}
            </div>
          )}

          {/* Recommendations */}
          {insight.recommendations.length > 0 && (
            <div className="border border-border p-3 space-y-1">
              <p className="font-mono text-[10px] tracking-widest text-muted-foreground mb-2">
                RECOMMENDATIONS (evidence-based · requires approval to act)
              </p>
              {insight.recommendations.map((r, i) => (
                <p key={i} className="text-[12px] text-muted-foreground">→ {r}</p>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
