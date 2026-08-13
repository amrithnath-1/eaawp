import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { AppShell } from "@/components/eaawp/AppShell";
import { KeyValue, PageHeader, Panel } from "@/components/eaawp/Panel";
import { knowledgeService } from "@/services";
import type { LibraryItem } from "@/services/types";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/library")({
  head: () => ({
    meta: [
      { title: "Company knowledge library — EAAWP" },
      { name: "description", content: "Documents, policies, SOPs and datasets that form the company AI employee's knowledge base." },
      { property: "og:title", content: "Company knowledge library — EAAWP" },
      { property: "og:description", content: "Manage the knowledge sources available to your AI employee." },
    ],
  }),
  component: LibraryPage,
});

const CATEGORIES = ["All", "Documents", "Reports", "Policies", "SOPs", "Manuals", "Communications", "Datasets", "Reference"] as const;

function LibraryPage() {
  const [items, setItems] = useState<LibraryItem[]>(() => knowledgeService.items());
  const [cat, setCat] = useState<(typeof CATEGORIES)[number]>("All");
  const [q, setQ] = useState("");
  const status = knowledgeService.status();

  const filtered = useMemo(
    () =>
      items.filter(
        (i) => (cat === "All" || i.category === cat) && i.name.toLowerCase().includes(q.toLowerCase()),
      ),
    [items, cat, q],
  );

  return (
    <AppShell>
      <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_300px]">
        <div className="p-4">
          <PageHeader
            title="Library"
            subtitle="Everything here becomes retrievable knowledge for the AI, subject to access rules."
            actions={
              <button
                onClick={() => toast.success("Upload queued for indexing")}
                className="border border-primary px-3 py-1.5 font-mono text-[10px] tracking-[0.14em] text-primary hover:bg-primary/10"
              >
                UPLOAD
              </button>
            }
          />

          <div className="mt-3 flex flex-wrap items-center gap-1.5">
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search knowledge…"
              className="h-8 w-56 border border-input bg-surface px-2 text-xs outline-none focus:border-ring"
            />
            {CATEGORIES.map((c) => (
              <button
                key={c}
                onClick={() => setCat(c)}
                className={cn(
                  "border px-2 py-1 font-mono text-[10px] tracking-[0.1em]",
                  cat === c ? "border-primary text-primary" : "border-border text-muted-foreground hover:text-foreground",
                )}
              >
                {c.toUpperCase()}
              </button>
            ))}
          </div>

          <div className="mt-4 border border-border">
            <div className="grid grid-cols-[2fr_1fr_0.7fr_0.7fr_1fr_auto] gap-3 border-b border-border bg-surface-2 px-3 py-2">
              {["Name", "Category", "Size", "Updated", "Access", ""].map((h) => (
                <span key={h} className="label-xs">{h}</span>
              ))}
            </div>
            {filtered.map((i) => (
              <div key={i.id} className="grid grid-cols-[2fr_1fr_0.7fr_0.7fr_1fr_auto] items-center gap-3 border-b border-border px-3 py-2 last:border-0 hover:bg-surface">
                <div className="flex items-center gap-2">
                  <span className={cn("size-1.5", i.indexed ? "bg-primary" : "bg-muted-foreground")} />
                  <span className="truncate text-[13px]">{i.name}</span>
                </div>
                <span className="font-mono text-[10px] text-muted-foreground">{i.category.toUpperCase()}</span>
                <span className="font-mono text-[11px] text-muted-foreground">{i.size}</span>
                <span className="font-mono text-[11px] text-muted-foreground">{i.updated}</span>
                <span className="font-mono text-[10px] text-muted-foreground">{i.access}</span>
                <div className="flex gap-1.5">
                  <button onClick={() => toast(`Preview ${i.name}`)} className="border border-border px-2 py-0.5 font-mono text-[10px] text-muted-foreground hover:text-foreground">
                    PREVIEW
                  </button>
                  <button
                    onClick={() => setItems((prev) => prev.filter((x) => x.id !== i.id))}
                    className="border border-border px-2 py-0.5 font-mono text-[10px] text-muted-foreground hover:text-destructive"
                  >
                    DELETE
                  </button>
                </div>
              </div>
            ))}
            {filtered.length === 0 && (
              <div className="px-3 py-8 text-center font-mono text-[11px] text-muted-foreground">No matching knowledge</div>
            )}
          </div>
        </div>

        <div className="border-t border-border p-4 lg:border-l lg:border-t-0">
          <Panel title="Knowledge status" dense>
            <div className="px-3 py-2">
              <KeyValue k="Documents indexed" v={status.documentsIndexed.toLocaleString()} />
              <KeyValue k="Knowledge sources" v={status.knowledgeSources} />
              <KeyValue k="Last synchronized" v={status.lastSync} />
              <KeyValue k="Knowledge updates" v={status.pendingUpdates} />
            </div>
          </Panel>
          <Panel title="Last response sources" dense className="mt-4">
            <ul className="px-3 py-2">
              {["Company Sales Policy.pdf", "Q2 Revenue Report.xlsx", "Customer Service SOP.pdf"].map((s) => (
                <li key={s} className="flex items-center gap-2 border-b border-border py-1.5 font-mono text-[11px] last:border-0">
                  <span className="size-1 bg-primary" /> {s}
                </li>
              ))}
            </ul>
          </Panel>
        </div>
      </div>
    </AppShell>
  );
}
