/**
 * ContentPanel — Marketing Content Intelligence
 * Generate briefs, ideas, drafts; view status and RAG sources.
 * Mock mode clearly labelled. No external publishing.
 */
import { useState } from "react";
import { BookOpen, Check, FileText, Info, Lightbulb, Loader2, Plus, RefreshCw, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { USE_REAL_API } from "@/lib/api-client";
import {
  useContentItems, useGenerateBrief, useGenerateDraft, useGenerateIdeas,
  type ContentItemFE, type ContentType,
} from "@/hooks/use-api";

const TYPE_ICON: Record<ContentType, React.ElementType> = {
  brief: BookOpen, idea: Lightbulb, draft: FileText,
  variant: Sparkles, analysis: Check,
};

const STATUS_COLOUR: Record<string, string> = {
  draft: "text-muted-foreground", review: "text-warning",
  approved: "text-success", rejected: "text-destructive", archived: "opacity-40",
};

function ContentCard({ item }: { item: ContentItemFE }) {
  const [expanded, setExpanded] = useState(false);
  const Icon = TYPE_ICON[item.content_type as ContentType] ?? FileText;
  return (
    <div className="border border-border">
      <button onClick={() => setExpanded(e => !e)} className="w-full text-left p-3 hover:bg-surface-2">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0 flex-1 flex items-start gap-2">
            <Icon className="size-3.5 shrink-0 mt-0.5 text-muted-foreground" strokeWidth={1.5} />
            <div className="min-w-0">
              <p className="text-[12px] font-medium truncate">{item.title}</p>
              <div className="flex items-center gap-2 mt-0.5 text-[10px]">
                <span className="font-mono border border-border px-1 text-muted-foreground">{item.content_type.toUpperCase()}</span>
                <span className={cn("font-mono", STATUS_COLOUR[item.status] ?? "text-muted-foreground")}>{item.status.toUpperCase()}</span>
                {item.channel && <span className="text-muted-foreground">{item.channel}</span>}
              </div>
            </div>
          </div>
          <span className="shrink-0 font-mono text-[9px] text-muted-foreground">{new Date(item.created_at).toLocaleDateString()}</span>
        </div>
      </button>
      {expanded && (
        <div className="border-t border-border bg-surface-2 px-3 py-3 space-y-2">
          {item.body && (
            <div>
              <p className="label-xs mb-1">Content</p>
              <p className="text-[12px] text-muted-foreground whitespace-pre-wrap">{item.body.slice(0, 600)}{item.body.length > 600 ? "…" : ""}</p>
            </div>
          )}
          {item.rag_sources.length > 0 && (
            <div>
              <p className="label-xs mb-1">Sources (RAG)</p>
              {item.rag_sources.map((s, i) => (
                <p key={i} className="font-mono text-[10px] text-primary">● {s}</p>
              ))}
            </div>
          )}
          {typeof item.analysis["analysis"] === "string" && item.analysis["analysis"] && (
            <div>
              <p className="label-xs mb-1">Analysis</p>
              <p className="text-[11px] text-muted-foreground">{String(item.analysis["analysis"]).slice(0, 400)}</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function GenerateForm({ onClose }: { onClose: () => void }) {
  const [mode, setMode] = useState<"brief" | "ideas" | "draft">("brief");
  const [objective, setObjective] = useState("");
  const [channel, setChannel] = useState("email");
  const [tone, setTone] = useState("professional");

  const brief = useGenerateBrief();
  const draft = useGenerateDraft();
  const ideas = useGenerateIdeas();
  const isPending = brief.isPending || draft.isPending || ideas.isPending;

  async function handle(e: React.FormEvent) {
    e.preventDefault();
    if (!USE_REAL_API) {
      toast.info("Content generation requires VITE_USE_REAL_API=true.");
      onClose();
      return;
    }
    try {
      const body = { objective, channel, tone };
      if (mode === "brief") await brief.mutateAsync(body);
      else if (mode === "ideas") await ideas.mutateAsync(body);
      else await draft.mutateAsync(body);
      toast.success(`${mode} generated`);
      onClose();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Generation failed");
    }
  }

  return (
    <form onSubmit={(e) => void handle(e)} className="border border-border bg-surface p-4 space-y-3">
      <div className="flex items-center justify-between border-b border-border pb-2">
        <h3 className="font-mono text-[11px] tracking-widest">GENERATE CONTENT</h3>
      </div>
      {!USE_REAL_API && (
        <div className="flex gap-2 border border-border bg-surface-2 p-2 text-[11px] text-muted-foreground">
          <Info className="size-3.5 shrink-0 mt-0.5 text-primary" strokeWidth={1.5} />
          <span><strong>Simulated mode</strong> — set VITE_USE_REAL_API=true for real AI generation.</span>
        </div>
      )}
      <div className="flex gap-1.5">
        {(["brief", "ideas", "draft"] as const).map(m => (
          <button key={m} type="button" onClick={() => setMode(m)}
            className={cn("border px-2 py-1 font-mono text-[10px] tracking-widest",
              mode === m ? "border-primary text-primary" : "border-border text-muted-foreground")}>
            {m.toUpperCase()}
          </button>
        ))}
      </div>
      <div>
        <label className="label-xs">Objective *</label>
        <input required value={objective} onChange={e => setObjective(e.target.value)}
          placeholder="e.g. Increase Q4 lead generation by 20%"
          className="mt-1 h-8 w-full border border-input bg-background px-2 text-[13px] outline-none focus:border-ring" />
      </div>
      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="label-xs">Channel</label>
          <select value={channel} onChange={e => setChannel(e.target.value)}
            className="mt-1 h-8 w-full border border-input bg-background px-2 text-[12px] outline-none">
            {["email", "social_linkedin", "social_twitter", "blog", "ad", "landing_page"].map(c => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="label-xs">Tone</label>
          <select value={tone} onChange={e => setTone(e.target.value)}
            className="mt-1 h-8 w-full border border-input bg-background px-2 text-[12px] outline-none">
            {["professional", "casual", "formal", "friendly", "urgent"].map(t => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
        </div>
      </div>
      <div className="flex gap-2 border-t border-border pt-3">
        <button type="submit" disabled={isPending}
          className="flex items-center gap-1.5 border border-primary px-4 py-1.5 font-mono text-[10px] tracking-widest text-primary hover:bg-primary/10 disabled:opacity-40">
          {isPending ? <Loader2 className="size-3 animate-spin" /> : <Sparkles className="size-3" strokeWidth={2} />}
          GENERATE
        </button>
        <button type="button" onClick={onClose}
          className="border border-border px-3 py-1.5 font-mono text-[10px] tracking-widest text-muted-foreground hover:text-foreground">
          CANCEL
        </button>
      </div>
    </form>
  );
}

export function ContentPanel() {
  const [typeFilter, setTypeFilter] = useState<string | undefined>(undefined);
  const [showForm, setShowForm] = useState(false);
  const { data: items, isLoading, refetch, isFetching } = useContentItems(typeFilter);

  return (
    <div className="space-y-3">
      {!USE_REAL_API && (
        <div className="flex gap-2 border border-border bg-surface-2 p-2 text-[11px] text-muted-foreground">
          <Info className="size-3.5 shrink-0 mt-0.5" strokeWidth={1.5} />
          <span><strong>Simulated mode</strong> — content generation requires VITE_USE_REAL_API=true.</span>
        </div>
      )}
      <div className="flex flex-wrap items-center gap-1.5">
        {([undefined, "brief", "idea", "draft", "variant", "analysis"] as const).map(t => (
          <button key={t ?? "all"} onClick={() => setTypeFilter(t)}
            className={cn("border px-2 py-0.5 font-mono text-[10px] tracking-widest",
              typeFilter === t ? "border-primary text-primary" : "border-border text-muted-foreground hover:text-foreground")}>
            {(t ?? "ALL").toUpperCase()}
          </button>
        ))}
        <div className="ml-auto flex gap-1.5">
          <button onClick={() => void refetch()} disabled={isFetching}
            className="border border-border px-1.5 py-1 text-muted-foreground hover:text-foreground disabled:opacity-40">
            <RefreshCw className={cn("size-3", isFetching && "animate-spin")} strokeWidth={1.5} />
          </button>
          <button onClick={() => setShowForm(true)}
            className="flex items-center gap-1 border border-primary px-2 py-1 font-mono text-[10px] tracking-widest text-primary hover:bg-primary/10">
            <Plus className="size-3" strokeWidth={2.5} /> GENERATE
          </button>
        </div>
      </div>
      {showForm && <GenerateForm onClose={() => setShowForm(false)} />}
      {isLoading ? (
        <div className="flex items-center gap-2 text-[12px] text-muted-foreground"><Loader2 className="size-4 animate-spin" />Loading content…</div>
      ) : (items ?? []).length === 0 && !showForm ? (
        <div className="border border-border bg-surface-2 p-5 text-center text-[13px] text-muted-foreground">
          <FileText className="mx-auto mb-2 size-8 opacity-30" strokeWidth={1} />
          <p className="font-medium">No content items</p>
          <p className="mt-1 text-[11px]">Generate a brief, ideas, or draft to start building marketing content.</p>
        </div>
      ) : (
        <div className="space-y-1">{(items ?? []).map(item => <ContentCard key={item.id} item={item} />)}</div>
      )}
      <p className="text-[10px] text-muted-foreground">
        Content is generated using your company knowledge base (RAG). No content is published externally.
        Future publishing requires HIGH-risk approval through the governance framework.
      </p>
    </div>
  );
}
