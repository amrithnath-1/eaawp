/**
 * StrategyPanel — Marketing Strategy & Decision Intelligence
 * Shows objectives, priorities, problems, opportunities, and recommendations.
 * All scores are deterministic. Mock mode clearly labelled.
 */
import { useState } from "react";
import { AlertTriangle, ArrowUp, BarChart2, CheckCircle, Info, Loader2, Target, TrendingDown } from "lucide-react";
import { cn } from "@/lib/utils";
import { USE_REAL_API } from "@/lib/api-client";
import { useMarketingObjectives, useStrategicAnalysis, type MarketingPriorityFE, type MarketingObjectiveFE } from "@/hooks/use-api";

function SeverityBadge({ severity }: { severity: string }) {
  const map: Record<string, string> = {
    critical: "border-destructive/60 text-destructive",
    high: "border-warning/60 text-warning",
    medium: "border-border text-muted-foreground",
    low: "border-border text-muted-foreground opacity-60",
  };
  return (
    <span className={cn("border px-1.5 py-0.5 font-mono text-[9px] tracking-widest", map[severity] ?? "border-border text-muted-foreground")}>
      {severity.toUpperCase()}
    </span>
  );
}

function PriorityCard({ priority }: { priority: MarketingPriorityFE }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div className="border border-border">
      <button onClick={() => setExpanded(e => !e)} className="w-full text-left p-3 hover:bg-surface-2">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 flex-wrap">
              <SeverityBadge severity={priority.severity} />
              <span className="text-[12px] font-medium truncate">{priority.title}</span>
            </div>
            <p className="mt-0.5 text-[11px] text-muted-foreground truncate">{priority.description}</p>
          </div>
          <span className="shrink-0 font-mono text-[11px] text-muted-foreground">{priority.priority_score.toFixed(0)}</span>
        </div>
      </button>
      {expanded && (
        <div className="border-t border-border bg-surface-2 px-3 py-2 space-y-2 text-[12px]">
          {priority.evidence.length > 0 && (
            <div><p className="label-xs mb-1">Evidence</p>
              {priority.evidence.map((e, i) => <p key={i} className="text-muted-foreground">• {e}</p>)}
            </div>
          )}
          <div className="flex gap-4 text-[10px] text-muted-foreground">
            <span>Confidence: {(priority.confidence * 100).toFixed(0)}%</span>
            <span>Data: {priority.data_completeness.toFixed(0)}%</span>
            <span>Approval: {priority.required_approval}</span>
          </div>
          <div><p className="label-xs mb-0.5">Recommended next step</p>
            <p className="text-muted-foreground">{priority.recommended_next_step}</p>
          </div>
        </div>
      )}
    </div>
  );
}

function ObjectiveRow({ obj }: { obj: MarketingObjectiveFE }) {
  const progress = obj.target_value && obj.current_value ? (obj.current_value / obj.target_value * 100) : null;
  return (
    <div className="flex items-center justify-between border-b border-border py-2 last:border-0">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="text-[12px] font-medium truncate">{obj.name}</span>
          <span className="font-mono text-[9px] border border-border px-1 text-muted-foreground">{obj.status.toUpperCase()}</span>
        </div>
        <p className="text-[10px] text-muted-foreground">{obj.objective_type} · {obj.target_metric}</p>
      </div>
      <div className="shrink-0 text-right">
        {progress !== null ? (
          <div className="w-16">
            <p className="font-mono text-[10px] text-muted-foreground">{progress.toFixed(0)}%</p>
            <div className="h-1 bg-muted mt-0.5">
              <div className="h-full bg-foreground" style={{ width: `${Math.min(progress, 100)}%` }} />
            </div>
          </div>
        ) : <span className="text-[10px] text-muted-foreground">No data</span>}
      </div>
    </div>
  );
}

export function StrategyPanel() {
  const [tab, setTab] = useState<"priorities" | "objectives">("priorities");
  const { data: objectives, isLoading: objLoading } = useMarketingObjectives("active");
  const { data: analysis, isLoading: anaLoading, isError } = useStrategicAnalysis();

  const isLoading = objLoading || anaLoading;

  return (
    <div className="space-y-3">
      {!USE_REAL_API && (
        <div className="flex gap-2 border border-border bg-surface-2 p-2 text-[11px] text-muted-foreground">
          <Info className="size-3.5 shrink-0 mt-0.5" strokeWidth={1.5} />
          <span><strong>Simulated mode</strong> — strategy analysis requires VITE_USE_REAL_API=true and recorded campaign/funnel data.</span>
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-1.5">
        {(["priorities", "objectives"] as const).map(t => (
          <button key={t} onClick={() => setTab(t)}
            className={cn("border px-3 py-1 font-mono text-[10px] tracking-widest",
              tab === t ? "border-primary text-primary" : "border-border text-muted-foreground hover:text-foreground")}>
            {t.toUpperCase()}
          </button>
        ))}
      </div>

      {isLoading && <div className="flex items-center gap-2 text-[12px] text-muted-foreground"><Loader2 className="size-4 animate-spin" />Loading…</div>}

      {tab === "priorities" && !isLoading && (
        <div className="space-y-3">
          {analysis ? (
            <>
              <p className="text-[12px] text-muted-foreground">{analysis.current_situation}</p>
              {analysis.top_problems.length > 0 && (
                <div>
                  <p className="label-xs mb-2 flex items-center gap-1"><TrendingDown className="size-3" strokeWidth={1.5} />Problems</p>
                  <div className="space-y-1">{analysis.top_problems.map((p, i) => <PriorityCard key={i} priority={p} />)}</div>
                </div>
              )}
              {analysis.top_opportunities.length > 0 && (
                <div>
                  <p className="label-xs mb-2 flex items-center gap-1"><ArrowUp className="size-3" strokeWidth={1.5} />Opportunities</p>
                  <div className="space-y-1">{analysis.top_opportunities.map((p, i) => <PriorityCard key={i} priority={p} />)}</div>
                </div>
              )}
              {analysis.recommended_actions.length > 0 && (
                <div className="border border-border p-3 space-y-1">
                  <p className="label-xs mb-1">Recommended Actions (governance required)</p>
                  {analysis.recommended_actions.map((a, i) => <p key={i} className="text-[11px] text-muted-foreground">→ {a}</p>)}
                </div>
              )}
              {analysis.uncertainties.length > 0 && (
                <div className="space-y-0.5">
                  {analysis.uncertainties.map((u, i) => (
                    <p key={i} className="flex items-start gap-1 text-[10px] text-muted-foreground">
                      <AlertTriangle className="size-3 shrink-0 mt-0.5" strokeWidth={1.5} />{u}
                    </p>
                  ))}
                </div>
              )}
            </>
          ) : (
            <div className="border border-border bg-surface-2 p-5 text-center text-[13px] text-muted-foreground">
              <BarChart2 className="mx-auto mb-2 size-8 opacity-30" strokeWidth={1} />
              <p className="font-medium">No strategy data available</p>
              <p className="mt-1 text-[11px]">Record campaign metrics and configure funnel mappings to enable strategy analysis.</p>
            </div>
          )}
        </div>
      )}

      {tab === "objectives" && !isLoading && (
        <div>
          {(objectives ?? []).length === 0 ? (
            <div className="border border-border bg-surface-2 p-5 text-center text-[13px] text-muted-foreground">
              <Target className="mx-auto mb-2 size-8 opacity-30" strokeWidth={1} />
              <p className="font-medium">No active objectives</p>
              <p className="mt-1 text-[11px]">Create marketing objectives through the DMM to track strategic goals.</p>
            </div>
          ) : (
            <div className="border border-border px-3">
              {(objectives ?? []).map(o => <ObjectiveRow key={o.id} obj={o} />)}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
