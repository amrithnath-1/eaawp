/**
 * CampaignsPanel — Marketing Campaign Workspace
 *
 * Shows the DMM's internal campaign records.
 * Follows the existing DataConnectionsPanel / MonitoringPanel visual pattern.
 * Mock mode shows clearly-labelled simulated data.
 */

import { useState } from "react";
import {
  BarChart2, Calendar, ChevronDown, ChevronRight,
  DollarSign, Info, Loader2, Plus, RefreshCw, Target,
} from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { USE_REAL_API } from "@/lib/api-client";
import {
  useCampaigns, useCreateCampaign,
  type CampaignFE, type CampaignCreateBody, type CampaignStatus,
} from "@/hooks/use-api";
import { CampaignPerformanceView } from "@/components/eaawp/CampaignPerformanceView";
import { FunnelView } from "@/components/eaawp/FunnelView";

// ── Status badge ──────────────────────────────────────────────────────────────

const STATUS_STYLES: Record<CampaignStatus, string> = {
  draft:     "border-border text-muted-foreground",
  planned:   "border-primary/40 text-primary",
  active:    "border-success/40 text-success",
  paused:    "border-warning/40 text-warning",
  completed: "border-border text-muted-foreground",
  cancelled: "border-destructive/30 text-destructive opacity-60",
};

function StatusBadge({ status }: { status: CampaignStatus }) {
  return (
    <span className={cn("border px-1.5 py-0.5 font-mono text-[9px] tracking-widest", STATUS_STYLES[status] ?? "border-border text-muted-foreground")}>
      {status.toUpperCase()}
    </span>
  );
}

// ── Campaign row ──────────────────────────────────────────────────────────────

function CampaignRow({ campaign }: { campaign: CampaignFE }) {
  const [expanded, setExpanded] = useState(false);
  const [showPerf, setShowPerf] = useState(false);
  const [showFunnel, setShowFunnel] = useState(false);
  const isSimulated = campaign.id.startsWith("mock-");

  return (
    <div className={cn("border-b border-border last:border-0", campaign.status === "cancelled" && "opacity-50")}>
      <div className="flex items-center gap-3 px-3 py-2.5">
        <button onClick={() => setExpanded((e) => !e)} className="text-muted-foreground hover:text-foreground">
          {expanded ? <ChevronDown className="size-3.5" strokeWidth={2} /> : <ChevronRight className="size-3.5" strokeWidth={2} />}
        </button>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-[13px] font-medium truncate">{campaign.name}</span>
            <StatusBadge status={campaign.status} />
            {isSimulated && (
              <span className="shrink-0 border border-border px-1 font-mono text-[8px] text-muted-foreground tracking-widest">SIMULATED</span>
            )}
          </div>
          <div className="mt-0.5 flex items-center gap-3 text-[10px] text-muted-foreground">
            {campaign.channel && <span>{campaign.channel}</span>}
            {campaign.budget > 0 && (
              <span className="flex items-center gap-0.5">
                <DollarSign className="size-3" strokeWidth={1.5} />
                {campaign.budget.toLocaleString()}
              </span>
            )}
            {campaign.start_date && (
              <span className="flex items-center gap-0.5">
                <Calendar className="size-3" strokeWidth={1.5} />
                {campaign.start_date}{campaign.end_date ? ` → ${campaign.end_date}` : ""}
              </span>
            )}
          </div>
        </div>
        <div className="shrink-0 text-[10px] text-muted-foreground">
          {campaign.kpis.length > 0 && (
            <span className="flex items-center gap-1">
              <Target className="size-3" strokeWidth={1.5} />
              {campaign.kpis.length} KPI{campaign.kpis.length !== 1 ? "s" : ""}
            </span>
          )}
        </div>
        <button
          onClick={(e) => { e.stopPropagation(); setShowPerf((s) => !s); }}
          className={cn(
            "shrink-0 border px-1.5 py-0.5 font-mono text-[9px] tracking-widest",
            showPerf ? "border-primary text-primary" : "border-border text-muted-foreground hover:text-foreground",
          )}>
          KPIs
        </button>
        <button
          onClick={(e) => { e.stopPropagation(); setShowFunnel((s) => !s); }}
          className={cn(
            "shrink-0 border px-1.5 py-0.5 font-mono text-[9px] tracking-widest",
            showFunnel ? "border-primary text-primary" : "border-border text-muted-foreground hover:text-foreground",
          )}>
          FUNNEL
        </button>
      </div>

      {expanded && (
        <div className="border-t border-border bg-surface-2 px-4 py-3 text-[12px] space-y-2">
          {campaign.objective && (
            <div>
              <p className="label-xs mb-0.5">Objective</p>
              <p className="text-muted-foreground">{campaign.objective}</p>
            </div>
          )}
          {campaign.target_audience && (
            <div>
              <p className="label-xs mb-0.5">Target audience</p>
              <p className="text-muted-foreground">{campaign.target_audience}</p>
            </div>
          )}
          {campaign.kpis.length > 0 && (
            <div>
              <p className="label-xs mb-1">KPIs</p>
              <div className="flex flex-wrap gap-2">
                {campaign.kpis.map((k) => (
                  <span key={k.name} className="border border-border px-2 py-0.5 font-mono text-[10px]">
                    {k.name}: {k.target}{k.unit}
                  </span>
                ))}
              </div>
            </div>
          )}
          <p className="text-[10px] text-muted-foreground">
            Created by: {campaign.created_by} · {new Date(campaign.created_at).toLocaleDateString()}
          </p>
        </div>
      )}

      {/* Performance view */}
      {showPerf && (
        <div className="border-t border-border bg-surface-2 px-4 py-3">
          <p className="label-xs mb-2">Performance Intelligence</p>
          <CampaignPerformanceView campaignId={campaign.id} campaignName={campaign.name} />
        </div>
      )}

      {/* Funnel view */}
      {showFunnel && (
        <div className="border-t border-border bg-surface-2 px-4 py-3">
          <p className="label-xs mb-2">Funnel &amp; Business Outcomes</p>
          <FunnelView campaignId={campaign.id} campaignName={campaign.name} />
        </div>
      )}
    </div>
  );
}

// ── Create form ───────────────────────────────────────────────────────────────

function CreateCampaignForm({ onClose }: { onClose: () => void }) {
  const [form, setForm] = useState<CampaignCreateBody>({
    name: "", objective: "", channel: "", budget: 0, target_audience: "",
    start_date: "", end_date: "",
  });
  const create = useCreateCampaign();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!USE_REAL_API) {
      toast.info("Creating campaigns requires VITE_USE_REAL_API=true. This is simulated mode.");
      onClose();
      return;
    }
    try {
      await create.mutateAsync(form);
      toast.success(`Campaign "${form.name}" created (awaiting approval)`);
      onClose();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to create campaign");
    }
  }

  return (
    <form onSubmit={(e) => void handleSubmit(e)} className="border border-border bg-surface p-4 space-y-3">
      <div className="flex items-center justify-between border-b border-border pb-2">
        <h3 className="font-mono text-[11px] tracking-widest">CREATE CAMPAIGN</h3>
      </div>
      {!USE_REAL_API && (
        <div className="flex gap-2 border border-border bg-surface-2 p-2 text-[11px] text-muted-foreground">
          <Info className="size-3.5 shrink-0 mt-0.5 text-primary" strokeWidth={1.5} />
          <span><strong>Simulated mode</strong> — set VITE_USE_REAL_API=true to create real campaigns.</span>
        </div>
      )}
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <div className="md:col-span-2">
          <label className="label-xs">Campaign name *</label>
          <input required value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
            placeholder="e.g. Q4 Email Campaign" className="mt-1 h-8 w-full border border-input bg-background px-2 text-[13px] outline-none focus:border-ring" />
        </div>
        <div className="md:col-span-2">
          <label className="label-xs">Objective</label>
          <input value={form.objective ?? ""} onChange={(e) => setForm((f) => ({ ...f, objective: e.target.value }))}
            placeholder="e.g. Increase conversions by 20%" className="mt-1 h-8 w-full border border-input bg-background px-2 text-[13px] outline-none focus:border-ring" />
        </div>
        <div>
          <label className="label-xs">Channel</label>
          <input value={form.channel ?? ""} onChange={(e) => setForm((f) => ({ ...f, channel: e.target.value }))}
            placeholder="e.g. email, social, paid" className="mt-1 h-8 w-full border border-input bg-background px-2 text-[13px] outline-none focus:border-ring" />
        </div>
        <div>
          <label className="label-xs">Budget</label>
          <input type="number" min={0} value={form.budget ?? 0}
            onChange={(e) => setForm((f) => ({ ...f, budget: parseFloat(e.target.value) || 0 }))}
            className="mt-1 h-8 w-full border border-input bg-background px-2 text-[13px] outline-none focus:border-ring" />
        </div>
        <div>
          <label className="label-xs">Start date</label>
          <input type="date" value={form.start_date ?? ""} onChange={(e) => setForm((f) => ({ ...f, start_date: e.target.value }))}
            className="mt-1 h-8 w-full border border-input bg-background px-2 text-[13px] outline-none focus:border-ring" />
        </div>
        <div>
          <label className="label-xs">End date</label>
          <input type="date" value={form.end_date ?? ""} onChange={(e) => setForm((f) => ({ ...f, end_date: e.target.value }))}
            className="mt-1 h-8 w-full border border-input bg-background px-2 text-[13px] outline-none focus:border-ring" />
        </div>
        <div className="md:col-span-2">
          <label className="label-xs">Target audience</label>
          <input value={form.target_audience ?? ""} onChange={(e) => setForm((f) => ({ ...f, target_audience: e.target.value }))}
            placeholder="e.g. Existing customers aged 25-45" className="mt-1 h-8 w-full border border-input bg-background px-2 text-[13px] outline-none focus:border-ring" />
        </div>
      </div>
      <div className="flex gap-2 border-t border-border pt-3">
        <button type="submit" disabled={create.isPending}
          className="flex items-center gap-1.5 border border-primary px-4 py-1.5 font-mono text-[10px] tracking-widest text-primary hover:bg-primary/10 disabled:opacity-40">
          {create.isPending ? <Loader2 className="size-3 animate-spin" /> : <Plus className="size-3" strokeWidth={2.5} />}
          CREATE (REQUIRES APPROVAL)
        </button>
        <button type="button" onClick={onClose}
          className="border border-border px-3 py-1.5 font-mono text-[10px] tracking-widest text-muted-foreground hover:text-foreground">
          CANCEL
        </button>
      </div>
    </form>
  );
}

// ── Main panel ────────────────────────────────────────────────────────────────

export function CampaignsPanel() {
  const [statusFilter, setStatusFilter] = useState<string | undefined>(undefined);
  const [showCreate, setShowCreate] = useState(false);
  const { data: campaigns, isLoading, isError, refetch, isFetching } = useCampaigns(statusFilter);

  const STATUSES: Array<{ value: string | undefined; label: string }> = [
    { value: undefined, label: "All" },
    { value: "active", label: "Active" },
    { value: "planned", label: "Planned" },
    { value: "draft", label: "Draft" },
    { value: "paused", label: "Paused" },
    { value: "completed", label: "Completed" },
  ];

  if (isLoading) return (
    <div className="flex items-center gap-2 p-4 text-[13px] text-muted-foreground">
      <Loader2 className="size-4 animate-spin" /> Loading campaigns…
    </div>
  );

  if (isError && USE_REAL_API) return (
    <div className="flex items-center gap-2 p-3 text-[13px] text-destructive">
      <Info className="size-4 shrink-0" strokeWidth={1.5} /> Failed to load campaigns.
    </div>
  );

  const list = campaigns ?? [];

  return (
    <div className="space-y-3">
      {!USE_REAL_API && (
        <div className="flex gap-2 border border-border bg-surface-2 p-2 text-[11px] text-muted-foreground">
          <Info className="size-3.5 shrink-0 mt-0.5" strokeWidth={1.5} />
          <span><strong>Simulated mode</strong> — real campaign management requires VITE_USE_REAL_API=true.</span>
        </div>
      )}

      {/* Filters + actions */}
      <div className="flex flex-wrap items-center gap-1.5">
        {STATUSES.map((s) => (
          <button key={s.label} onClick={() => setStatusFilter(s.value)}
            className={cn("border px-2 py-0.5 font-mono text-[10px] tracking-widest",
              statusFilter === s.value ? "border-primary text-primary" : "border-border text-muted-foreground hover:text-foreground")}>
            {s.label.toUpperCase()}
          </button>
        ))}
        <div className="ml-auto flex gap-1.5">
          <button onClick={() => void refetch()} disabled={isFetching}
            className="border border-border px-1.5 py-1 text-muted-foreground hover:text-foreground disabled:opacity-40">
            <RefreshCw className={cn("size-3", isFetching && "animate-spin")} strokeWidth={1.5} />
          </button>
          <button onClick={() => setShowCreate(true)}
            className="flex items-center gap-1 border border-primary px-2 py-1 font-mono text-[10px] tracking-widest text-primary hover:bg-primary/10">
            <Plus className="size-3" strokeWidth={2.5} /> NEW
          </button>
        </div>
      </div>

      {showCreate && <CreateCampaignForm onClose={() => setShowCreate(false)} />}

      {list.length === 0 && !showCreate ? (
        <div className="border border-border bg-surface-2 p-5 text-center text-[13px] text-muted-foreground">
          <BarChart2 className="mx-auto mb-2 size-8 opacity-30" strokeWidth={1} />
          <p className="font-medium">No campaigns found</p>
          <p className="mt-1 text-[11px]">Create a campaign to start tracking marketing activity.</p>
        </div>
      ) : (
        <div className="border border-border">
          {list.map((c) => <CampaignRow key={c.id} campaign={c} />)}
        </div>
      )}

      <p className="text-[10px] text-muted-foreground">
        Campaign records are internal to EAAWP — separate from external company data.
        Campaign creation and budget updates require human approval via the governance framework.
      </p>
    </div>
  );
}
