import { createFileRoute } from "@tanstack/react-router";
import { useRef, useState } from "react";
import { toast } from "sonner";
import { Upload, RefreshCw, Trash2 } from "lucide-react";
import { AppShell } from "@/components/eaawp/AppShell";
import { KeyValue, PageHeader, Panel } from "@/components/eaawp/Panel";
import { knowledgeService } from "@/services";
import type { LibraryItem } from "@/services/types";
import { cn } from "@/lib/utils";
import {
  useKnowledgeDocuments,
  useKnowledgeStatusReal,
  useUploadDocument,
  useDeleteDocument,
  type KnowledgeDocument,
  type DocumentStatus,
} from "@/hooks/use-api";
import { USE_REAL_API } from "@/lib/api-client";

export const Route = createFileRoute("/library")({
  component: LibraryPage,
});

const CATEGORIES = ["All", "Documents", "Reports", "Policies", "SOPs", "Manuals", "Communications", "Datasets", "Reference"] as const;

// ── Status badge ──────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: DocumentStatus }) {
  const map: Record<DocumentStatus, string> = {
    uploading: "border-muted-foreground/40 text-muted-foreground",
    processing: "border-warning/40 text-warning",
    indexed: "border-success/40 text-success",
    failed: "border-destructive/40 text-destructive",
  };
  return (
    <span className={cn("border px-1.5 py-0.5 font-mono text-[10px] tracking-[0.08em]", map[status])}>
      {status.toUpperCase()}
    </span>
  );
}

// ── Role scope pill ───────────────────────────────────────────────────────────

const SCOPE_COLOURS: Record<string, string> = {
  "Global / Shared": "border-accent/40 bg-accent/10 text-accent",
  "Sales Agent Only": "border-primary/40 bg-primary/10 text-primary",
  "Finance Agent Only": "border-warning/40 bg-warning/10 text-warning",
  "Customer Service Agent Only": "border-info/40 bg-info/10 text-info",
  "HR Agent Only": "border-success/40 bg-success/10 text-success",
  "Operations Agent Only": "border-muted-foreground/40 bg-muted/40 text-muted-foreground",
  "Marketing Agent Only": "border-primary/40 bg-primary/10 text-primary",
  "Clerk Agent Only": "border-warning/40 bg-warning/10 text-warning",
  "Clinic Agent Only": "border-success/40 bg-success/10 text-success",
  "Data Analyst Only": "border-info/40 bg-info/10 text-info",
};

function ScopePill({ scope }: { scope: string }) {
  return (
    <span className={cn("inline-block border px-1.5 py-0.5 font-mono text-[10px] tracking-[0.08em]", SCOPE_COLOURS[scope] ?? "border-border text-muted-foreground")}>
      {scope}
    </span>
  );
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString([], { day: "2-digit", month: "short" });
  } catch {
    return iso;
  }
}

// ── Real document row ─────────────────────────────────────────────────────────

function RealDocumentRow({
  doc,
  onDelete,
  deleting,
}: {
  doc: KnowledgeDocument;
  onDelete: (id: string) => void;
  deleting: boolean;
}) {
  const isIndexed = doc.status === "indexed";
  return (
    <div className="grid grid-cols-[2fr_1fr_0.7fr_0.7fr_1.4fr_1fr_auto] items-center gap-2 border-b border-border px-3 py-2 last:border-0 hover:bg-surface">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className={cn("size-1.5 shrink-0", isIndexed ? "bg-success" : doc.status === "processing" || doc.status === "uploading" ? "bg-warning animate-pulse" : "bg-destructive")} />
          <span className="truncate text-[13px]">{doc.name}</span>
        </div>
        {doc.status === "failed" && doc.error_message && (
          <p className="mt-0.5 pl-3.5 text-[11px] leading-snug text-destructive" title={doc.error_message}>
            {doc.error_message}
          </p>
        )}
      </div>
      <span className="font-mono text-[10px] text-muted-foreground">{doc.doc_type.toUpperCase()}</span>
      <span className="font-mono text-[11px] text-muted-foreground">{formatBytes(doc.size_bytes)}</span>
      <span className="font-mono text-[11px] text-muted-foreground">{formatDate(doc.uploaded_at)}</span>
      <ScopePill scope={doc.role_scope} />
      <StatusBadge status={doc.status} />
      <button
        onClick={() => onDelete(doc.id)}
        disabled={deleting}
        aria-label="Delete document"
        className="text-muted-foreground hover:text-destructive disabled:opacity-30"
      >
        <Trash2 className="size-3.5" strokeWidth={1.5} />
      </button>
    </div>
  );
}

// ── Upload panel ──────────────────────────────────────────────────────────────

function UploadPanel() {
  const uploadMutation = useUploadDocument();
  const fileRef = useRef<HTMLInputElement>(null);
  const [roleScope, setRoleScope] = useState("Global / Shared");
  const [accessLevel, setAccessLevel] = useState("All staff");

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;

    const formData = new FormData();
    formData.append("file", file);
    formData.append("role_scope", roleScope);
    formData.append("access_level", accessLevel);
    formData.append("uploaded_by", "admin");

    uploadMutation.mutate(formData, {
      onSuccess: () => toast.success(`${file.name} uploaded — processing…`),
      onError: (err) => toast.error(err.message),
    });

    // Reset input
    if (fileRef.current) fileRef.current.value = "";
  }

  return (
    <div className="space-y-2">
      <div className="flex gap-2">
        <div className="flex-1">
          <label className="label-xs">Role scope</label>
          <select
            value={roleScope}
            onChange={(e) => setRoleScope(e.target.value)}
            className="mt-1 h-8 w-full border border-input bg-background px-2 font-mono text-[10px] text-muted-foreground outline-none focus:border-ring"
          >
            {Object.keys(SCOPE_COLOURS).map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </div>
        <div className="flex-1">
          <label className="label-xs">Access level</label>
          <select
            value={accessLevel}
            onChange={(e) => setAccessLevel(e.target.value)}
            className="mt-1 h-8 w-full border border-input bg-background px-2 font-mono text-[10px] text-muted-foreground outline-none focus:border-ring"
          >
            {["All staff", "Managers", "Admins", "AI only"].map((a) => (
              <option key={a} value={a}>{a}</option>
            ))}
          </select>
        </div>
      </div>
      <input
        ref={fileRef}
        type="file"
        accept=".pdf,.docx,.txt,.csv,.xlsx"
        className="hidden"
        onChange={handleFileChange}
        disabled={uploadMutation.isPending}
      />
      <button
        onClick={() => fileRef.current?.click()}
        disabled={uploadMutation.isPending}
        className="flex w-full items-center justify-center gap-2 border border-primary px-3 py-2 font-mono text-[10px] tracking-[0.14em] text-primary hover:bg-primary/10 disabled:opacity-40"
      >
        {uploadMutation.isPending
          ? <><RefreshCw className="size-3 animate-spin" /> UPLOADING…</>
          : <><Upload className="size-3" /> UPLOAD DOCUMENT</>
        }
      </button>
      <p className="text-[10px] text-muted-foreground">Supported: PDF, DOCX, TXT, CSV, XLSX · Max 50 MB</p>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

function LibraryPage() {
  // Real API data
  const { data: realDocs, isLoading: docsLoading } = useKnowledgeDocuments();
  const { data: realStatus } = useKnowledgeStatusReal();
  const deleteMutation = useDeleteDocument();

  // Mock data (used when real API is off)
  const [mockItems, setMockItems] = useState<LibraryItem[]>(() => knowledgeService.items());
  const mockStatus = knowledgeService.status();

  const [cat, setCat] = useState<(typeof CATEGORIES)[number]>("All");
  const [q, setQ] = useState("");

  const ROLE_SCOPES = ["All", ...Object.keys(SCOPE_COLOURS)] as const;
  const [roleScope, setRoleScope] = useState<string>("All");

  function handleDelete(docId: string) {
    deleteMutation.mutate(docId, {
      onSuccess: () => toast.success("Document deleted"),
      onError: (err) => toast.error(err.message),
    });
  }

  const filteredMock = mockItems.filter(
    (i) =>
      (cat === "All" || i.category === cat) &&
      (roleScope === "All" || i.roleScope === roleScope) &&
      i.name.toLowerCase().includes(q.toLowerCase()),
  );

  const filteredReal = (realDocs ?? []).filter(
    (d) =>
      (roleScope === "All" || d.role_scope === roleScope) &&
      d.name.toLowerCase().includes(q.toLowerCase()),
  );

  return (
    <AppShell>
      <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_300px]">
        <div className="p-4">
          <PageHeader
            title="Library"
            subtitle="Everything here becomes retrievable knowledge for the AI, subject to access rules."
          />

          {/* Filters */}
          <div className="mt-3 flex flex-wrap items-center gap-1.5">
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search knowledge…"
              className="h-8 w-48 border border-input bg-surface px-2 text-xs outline-none focus:border-ring"
            />
            <div className="relative">
              <select
                value={roleScope}
                onChange={(e) => setRoleScope(e.target.value)}
                className="h-8 appearance-none border border-input bg-surface pl-2 pr-6 font-mono text-[10px] tracking-[0.1em] text-muted-foreground outline-none focus:border-ring"
              >
                {ROLE_SCOPES.map((s) => (
                  <option key={s} value={s}>{s === "All" ? "ALL ROLES" : s.toUpperCase()}</option>
                ))}
              </select>
              <span className="pointer-events-none absolute right-1.5 top-1/2 -translate-y-1/2 font-mono text-[8px] text-muted-foreground">▼</span>
            </div>
            {!USE_REAL_API && CATEGORIES.map((c) => (
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
            {USE_REAL_API && (
              <span className="font-mono text-[9px] tracking-[0.1em] text-success">● REAL API</span>
            )}
          </div>

          {/* Document table */}
          <div className="mt-4 border border-border">
            <div className="grid grid-cols-[2fr_1fr_0.7fr_0.7fr_1.4fr_1fr_auto] gap-2 border-b border-border bg-surface-2 px-3 py-2">
              {["Name", "Type", "Size", "Uploaded", "Role Scope", "Status / Access", ""].map((h) => (
                <span key={h} className="label-xs">{h}</span>
              ))}
            </div>

            {USE_REAL_API ? (
              <>
                {docsLoading && (
                  <div className="flex items-center gap-2 px-3 py-4 text-[12px] text-muted-foreground">
                    <RefreshCw className="size-3 animate-spin" /> Loading documents…
                  </div>
                )}
                {!docsLoading && filteredReal.length === 0 && (
                  <div className="px-3 py-8 text-center font-mono text-[11px] text-muted-foreground">
                    No documents yet — upload one to get started
                  </div>
                )}
                {filteredReal.map((doc) => (
                  <RealDocumentRow
                    key={doc.id}
                    doc={doc}
                    onDelete={handleDelete}
                    deleting={deleteMutation.isPending}
                  />
                ))}
              </>
            ) : (
              <>
                {filteredMock.map((i) => (
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
                        onClick={() => setMockItems((prev) => prev.filter((x) => x.id !== i.id))}
                        className="border border-border px-2 py-0.5 font-mono text-[10px] text-muted-foreground hover:text-destructive"
                      >
                        DELETE
                      </button>
                    </div>
                  </div>
                ))}
                {filteredMock.length === 0 && (
                  <div className="px-3 py-8 text-center font-mono text-[11px] text-muted-foreground">No matching knowledge</div>
                )}
              </>
            )}
          </div>
        </div>

        {/* Sidebar */}
        <div className="border-t border-border p-4 lg:border-l lg:border-t-0">
          {/* Upload (real API only) */}
          {USE_REAL_API && (
            <Panel title="Upload document" dense className="mb-4">
              <div className="px-3 py-2">
                <UploadPanel />
              </div>
            </Panel>
          )}

          {/* Status */}
          <Panel title="Knowledge status" dense>
            <div className="px-3 py-2">
              {USE_REAL_API && realStatus ? (
                <>
                  <KeyValue k="Documents indexed" v={realStatus.documents_indexed} />
                  <KeyValue k="Total documents" v={realStatus.documents_total} />
                  <KeyValue k="Processing" v={realStatus.documents_processing} />
                  <KeyValue k="Failed" v={realStatus.documents_failed} />
                  <KeyValue k="Last indexed" v={realStatus.last_indexed_at ? formatDate(realStatus.last_indexed_at) : "—"} />
                </>
              ) : (
                <>
                  <KeyValue k="Documents indexed" v={mockStatus.documentsIndexed.toLocaleString()} />
                  <KeyValue k="Knowledge sources" v={mockStatus.knowledgeSources} />
                  <KeyValue k="Last synchronized" v={mockStatus.lastSync} />
                  <KeyValue k="Knowledge updates" v={mockStatus.pendingUpdates} />
                </>
              )}
            </div>
          </Panel>

          {/* Scope legend */}
          <Panel title="Role scope legend" dense className="mt-4">
            <ul className="space-y-1.5 px-3 py-2">
              {Object.keys(SCOPE_COLOURS).map((s) => (
                <li key={s}>
                  <ScopePill scope={s} />
                </li>
              ))}
            </ul>
          </Panel>
        </div>
      </div>
    </AppShell>
  );
}
