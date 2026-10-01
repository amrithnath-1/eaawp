/**
 * FunnelView — Lead & Customer Funnel Intelligence
 *
 * Shows funnel stages, conversion rates, drop-offs, and efficiency metrics.
 * All values are deterministic — never LLM-fabricated.
 * Only shows stages where data is available.
 * Monochrome visual language matching existing panels.
 */

import { Info, Loader2, ArrowRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { USE_REAL_API } from "@/lib/api-client";
import { useCampaignFunnel, type FunnelMetricsFE, type FunnelStageFE } from "@/hooks/use-api";

// ── Funnel stage bar ──────────────────────────────────────────────────────────

function StageBar({ stage, maxValue }: { stage: FunnelStageFE; maxValue: number }) {
  const pct = maxValue > 0 && stage.value !== null ? (stage.value / maxValue) * 100 : 0;
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-[11px]">
        <span className="font-mono text-muted-foreground uppercase tracking-widest">
          {stage.name.replace(/_/g, " ")}
        </span>
        {stage.value !== null ? (
          <span className="font-medium">{stage.value.toLocaleString()}</span>
        ) : (
          <span className="text-muted-foreground text-[10px]">
            N/A {stage.missing_reason ? `(${stage.missing_reason})` : ""}
          </span>
        )}
      </div>
      <div className="h-2 w-full bg-muted">
        {stage.value !== null && (
          <div className="h-full bg-foreground transition-all" style={{ width: `${pct}%` }} />
        )}
      </div>
    </div>
  );
}

// ── Conversion rate badge ─────────────────────────────────────────────────────

function ConversionBadge({ rate_pct, from_stage, to_stage }: {
  rate_pct: number | null;
  from_stage: string;
  to_stage: string;
}) {
  return (
    <div className="flex items-center gap-1 text-[10px] text-muted-foreground">
      <span>{from_stage.replace(/_/g, " ")}</span>
      <ArrowRight className="size-3" strokeWidth={1.5} />
      <span>{to_stage.replace(/_/g, " ")}</span>
      <span className={cn(
        "ml-1 font-medium",
        rate_pct !== null ? "text-foreground" : "text-muted-foreground",
      )}>
        {rate_pct !== null ? `${rate_pct.toFixed(2)}%` : "N/A"}
      </span>
    </div>
  );
}

// ── Metric tile ───────────────────────────────────────────────────────────────

function MetricTile({ label, value, unit = "" }: { label: string; value: number | null; unit?: string }) {
  return (
    <div className="border border-border bg-surface p-2">
      <p className="font-mono text-[9px] tracking-widest text-muted-foreground">{label}</p>
      {value !== null ? (
        <p className="mt-1 text-[15px] font-medium">
          {value.toFixed(2)}<span className="ml-0.5 text-[11px] text-muted-foreground">{unit}</span>
        </p>
      ) : (
        <p className="mt-1 text-[12px] text-muted-foreground">N/A</p>
      )}
    </div>
  );
}

// ── Completeness bar ──────────────────────────────────────────────────────────

function CompletenessBar({ pct }: { pct: number }) {
  const color = pct >= 80 ? "bg-success" : pct >= 40 ? "bg-warning" : "bg-destructive";
  return (
    <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
      <span className="shrink-0">Funnel data {pct.toFixed(0)}% complete</span>
      <div className="h-1.5 flex-1 bg-muted">
        <div className={cn("h-full transition-all", color)} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

interface Props {
  campaignId: string;
  campaignName: string;
}

export function FunnelView({ campaignId, campaignName }: Props) {
  const { data: funnel, isLoading, isError } = useCampaignFunnel(campaignId);

  if (!USE_REAL_API) {
    return (
      <div className="flex gap-2 border border-border bg-surface-2 p-3 text-[11px] text-muted-foreground">
        <Info className="size-3.5 shrink-0 mt-0.5" strokeWidth={1.5} />
        <span>
          <strong>Simulated mode</strong> — funnel analysis requires VITE_USE_REAL_API=true
          and semantic mappings configured for funnel concepts (lead_count, customer_count, etc.).
        </span>
      </div>
    );
  }

  if (isLoading) return (
    <div className="flex items-center gap-2 text-[12px] text-muted-foreground">
      <Loader2 className="size-4 animate-spin" /> Loading funnel data…
    </div>
  );

  if (isError) return (
    <div className="text-[12px] text-muted-foreground italic">
      Funnel data unavailable — configure semantic mappings for funnel concepts.
    </div>
  );

  if (!funnel) return null;

  const availableStages = funnel.stages.filter((s) => s.value !== null);
  const maxValue = Math.max(...availableStages.map((s) => s.value ?? 0), 1);
  const availableRates = funnel.conversion_rates.filter((c) => c.rate_pct !== null);

  return (
    <div className="space-y-4">
      <CompletenessBar pct={funnel.data_completeness_pct} />

      {funnel.analysis_note && (
        <p className="flex items-start gap-1 text-[11px] text-warning">
          <Info className="size-3 shrink-0 mt-0.5" strokeWidth={1.5} />
          {funnel.analysis_note}
        </p>
      )}

      {/* Funnel stages */}
      {availableStages.length > 0 ? (
        <div className="space-y-2">
          <p className="font-mono text-[10px] tracking-widest text-muted-foreground">FUNNEL STAGES</p>
          {funnel.stages.map((s) => (
            <StageBar key={s.name} stage={s} maxValue={maxValue} />
          ))}
        </div>
      ) : (
        <p className="text-[12px] text-muted-foreground">
          No funnel stage data available. Configure semantic mappings for lead_count, customer_count, etc.
        </p>
      )}

      {/* Conversion rates */}
      {availableRates.length > 0 && (
        <div>
          <p className="mb-2 font-mono text-[10px] tracking-widest text-muted-foreground">CONVERSION RATES</p>
          <div className="space-y-1">
            {funnel.conversion_rates.map((cr) => (
              <ConversionBadge key={`${cr.from_stage}-${cr.to_stage}`}
                rate_pct={cr.rate_pct} from_stage={cr.from_stage} to_stage={cr.to_stage} />
            ))}
          </div>
        </div>
      )}

      {/* Efficiency metrics */}
      <div className="grid grid-cols-2 gap-1.5 md:grid-cols-3">
        <MetricTile label="CPL" value={funnel.cost_per_lead} unit="£" />
        <MetricTile label="CAC" value={funnel.cost_per_customer} unit="£" />
        <MetricTile label="ROAS" value={funnel.roas} unit="x" />
        <MetricTile label="Rev/Lead" value={funnel.revenue_per_lead} unit="£" />
        <MetricTile label="Rev/Customer" value={funnel.revenue_per_customer} unit="£" />
      </div>

      {/* Findings */}
      {funnel.findings.length > 0 && (
        <div className="border border-border p-3 space-y-1">
          <p className="font-mono text-[10px] tracking-widest text-muted-foreground mb-1">FINDINGS</p>
          {funnel.findings.map((f, i) => (
            <p key={i} className="text-[12px] text-muted-foreground">• {f}</p>
          ))}
        </div>
      )}

      {/* Recommendations */}
      {funnel.recommendations.length > 0 && (
        <div className="border border-border p-3 space-y-1">
          <p className="font-mono text-[10px] tracking-widest text-muted-foreground mb-1">
            RECOMMENDATIONS (requires approval to act)
          </p>
          {funnel.recommendations.map((r, i) => (
            <p key={i} className="text-[12px] text-muted-foreground">→ {r}</p>
          ))}
        </div>
      )}

      {funnel.sources.length > 0 && (
        <p className="text-[10px] text-muted-foreground">
          Sources: {funnel.sources.join(" · ")}
        </p>
      )}
    </div>
  );
}
