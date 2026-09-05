import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { AppShell } from "@/components/eaawp/AppShell";
import { KeyValue, PageHeader, Panel } from "@/components/eaawp/Panel";
import { knowledgeService } from "@/services";
import type { LibraryItem } from "@/services/types";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/library")({
  component: LibraryPage,
});

const CATEGORIES = ["All", "Documents", "Reports", "Policies", "SOPs", "Manuals", "Communications", "Datasets", "Reference"] as const;

type RoleScope = LibraryItem["roleScope"] | "All";

const ROLE_SCOPES: RoleScope[] = [
  "All",
  "Global / Shared",
  "Sales Agent Only",
  "Finance Agent Only",
  "Customer Service Agent Only",
  "HR Agent Only",
  "Operations Agent Only",
];

const SCOPE_COLOURS: Record<LibraryItem["roleScope"], string> = {
  "Global / Shared":                 "border-accent/40 bg-accent/10 text-accent",
  "Sales Agent Only":                "border-primary/40 bg-primary/10 text-primary",
  "Finance Agent Only":              "border-warning/40 bg-warning/10 text-warning",
  "Customer Service Agent Only":     "border-info/40 bg-info/10 text-info",
  "HR Agent Only":                   "border-success/40 bg-success/10 text-success",
  "Operations Agent Only":           "border-muted-foreground/40 bg-muted/40 text-muted-foreground",
};

function ScopePill({ scope }: { scope: LibraryItem["roleScope"] }) {
  return (
    <span className={cn("inline-block border px-1.5 py-0.5 font-mono text-[10px] tracking-[0.08em]", SCOPE_COLOURS[scope])}>
      {scope}
    </span>
  );
}

function LibraryPage() {
  const [items, setItems] = useState<LibraryItem[]>(() => knowledgeService.items());
  const [cat, setCat] = useState<(typeof CATEGORIES)[number]>("All");
  const [roleScope, setRoleScope] = useState<RoleScope>("All");
  const [q, setQ] = useState("");
  const status = knowledgeService.status();

  const filtered = useMemo(
    () =>
      items.filter(
        (i) =>
          (cat === "All" || i.category === cat) &&
          (roleScope === "All" || i.roleScope === roleScope) &&
          i.name.toLowerCase().includes(q.toLowerCase()),
      ),
    [items, cat, roleScope, q],
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

          {/* Filters row */}
          <div className="mt-3 flex flex-wrap items-center gap-1.5">
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search knowledge…"
              className="h-8 w-48 border border-input bg-surface px-2 text-xs outline-none focus:border-ring"
            />

            {/* ── Feature 2: Role Scope filter dropdown ── */}
            <div className="relative">
              <select
                value={roleScope}
                onChange={(e) => setRoleScope(e.target.value as RoleScope)}
                className="h-8 appearance-none border border-input bg-surface pl-2 pr-6 font-mono text-[10px] tracking-[0.1em] text-muted-foreground outline-none focus:border-ring"
              >
                {ROLE_SCOPES.map((s) => (
                  <option key={s} value={s}>{s === "All" ? "ALL ROLES" : s.toUpperCase()}</option>
                ))}
              </select>
              <span className="pointer-events-none absolute right-1.5 top-1/2 -translate-y-1/2 font-mono text-[8px] text-muted-foreground">▼</span>
            </div>

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

          {/* Table */}
          <div className="mt-4 border border-border">
            <div className="grid grid-cols-[2fr_1fr_0.7fr_0.7fr_1.4fr_1fr_auto] gap-2 border-b border-border bg-surface-2 px-3 py-2">
              {["Name", "Category", "Size", "Updated", "Role Scope", "Access", ""].map((h) => (
                <span key={h} className="label-xs">{h}</span>
              ))}
            </div>
            {filtered.map((i) => (
              <div
                key={i.id}
                className="grid grid-cols-[2fr_1fr_0.7fr_0.7fr_1.4fr_1fr_auto] items-center gap-2 border-b border-border px-3 py-2 last:border-0 hover:bg-surface"
              >
                <div className="flex items-center gap-2">
                  <span className={cn("size-1.5 shrink-0", i.indexed ? "bg-primary" : "bg-muted-foreground")} />
                  <span className="truncate text-[13px]">{i.name}</span>
                </div>
                <span className="font-mono text-[10px] text-muted-foreground">{i.category.toUpperCase()}</span>
                <span className="font-mono text-[11px] text-muted-foreground">{i.size}</span>
                <span className="font-mono text-[11px] text-muted-foreground">{i.updated}</span>
                {/* ── Feature 2: Role Scope pill ── */}
                <ScopePill scope={i.roleScope} />
                <span className="font-mono text-[10px] text-muted-foreground">{i.access}</span>
                <div className="flex gap-1.5">
                  <button
                    onClick={() => toast(`Preview ${i.name}`)}
                    className="border border-border px-2 py-0.5 font-mono text-[10px] text-muted-foreground hover:text-foreground"
                  >
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

          {/* Scope legend */}
          <Panel title="Role scope legend" dense className="mt-4">
            <ul className="px-3 py-2 space-y-1.5">
              {(Object.keys(SCOPE_COLOURS) as LibraryItem["roleScope"][]).map((s) => (
                <li key={s} className="flex items-center gap-2">
                  <ScopePill scope={s} />
                </li>
              ))}
            </ul>
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
