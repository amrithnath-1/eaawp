/**
 * SemanticMappingPanel
 *
 * Lets a Company Administrator create semantic concept → entity field
 * mappings. These allow the Digital Marketing Manager to request data
 * using schema-independent concepts (e.g. "campaign_name") which the
 * backend resolves to the actual column in the company's database.
 *
 * Security: no credentials are shown; only entity/field metadata.
 */
import { useState } from "react";
import { toast } from "sonner";
import { Plus, Trash2, RefreshCw, Tag } from "lucide-react";
import { cn } from "@/lib/utils";
import { USE_REAL_API } from "@/lib/api-client";
import {
  useSemanticMappings,
  useCreateSemanticMapping,
  useDeleteSemanticMapping,
  useDataConnections,
  useSchemaEntities,
  type SemanticMappingFE,
  type SemanticMappingCreate,
} from "@/hooks/use-api";

// ── Add mapping form ──────────────────────────────────────────────────────────

function AddMappingForm({ onDone }: { onDone: () => void }) {
  const { data: connections } = useDataConnections();
  const createMutation = useCreateSemanticMapping();

  const [form, setForm] = useState<SemanticMappingCreate>({
    semantic_concept: "",
    connection_id: "",
    entity_id: "",
    field_name: "",
    display_label: "",
    created_by: "admin",
  });

  const { data: entities } = useSchemaEntities(form.connection_id || null);

  // Get columns for the selected entity
  const selectedEntity = entities?.find((e) => e.id === form.entity_id);
  const availableColumns = selectedEntity?.columns ?? [];

  const connectedConns = (connections ?? []).filter((c) => c.status === "connected");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.semantic_concept || !form.connection_id || !form.entity_id || !form.field_name) {
      toast.error("All fields are required.");
      return;
    }
    // Validate identifier characters
    const safeId = /^[A-Za-z_][A-Za-z0-9_.]*$/;
    if (!safeId.test(form.semantic_concept)) {
      toast.error("Semantic concept must only contain letters, digits and underscores.");
      return;
    }
    createMutation.mutate(form, {
      onSuccess: () => {
        toast.success("Mapping created.");
        onDone();
      },
      onError: (err) => toast.error(err.message),
    });
  }

  const field = "h-8 w-full border border-input bg-background px-2 text-[13px] outline-none focus:border-ring appearance-none";

  return (
    <form onSubmit={(e) => void submit(e)} className="space-y-3 border border-border bg-surface p-3">
      <p className="font-mono text-[10px] tracking-[0.14em] text-muted-foreground">NEW SEMANTIC MAPPING</p>

      <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
        <div className="md:col-span-2">
          <label className="label-xs">Semantic concept <span className="text-muted-foreground">(what the AI calls it)</span></label>
          <input
            value={form.semantic_concept}
            onChange={(e) => setForm({ ...form, semantic_concept: e.target.value })}
            placeholder="e.g. campaign_name, ad_spend, conversion_rate"
            className={cn(field, "mt-1")}
          />
          <p className="mt-0.5 text-[10px] text-muted-foreground">
            Use snake_case. This is the schema-agnostic name the agent uses.
          </p>
        </div>

        <div>
          <label className="label-xs">Data connection</label>
          <select
            value={form.connection_id}
            onChange={(e) => setForm({ ...form, connection_id: e.target.value, entity_id: "", field_name: "" })}
            className={cn(field, "mt-1")}
          >
            <option value="">Select connection…</option>
            {connectedConns.map((c) => (
              <option key={c.id} value={c.id}>{c.display_name} ({c.db_type})</option>
            ))}
          </select>
          {connectedConns.length === 0 && (
            <p className="mt-0.5 text-[10px] text-warning">No connected data sources. Test a connection first.</p>
          )}
        </div>

        <div>
          <label className="label-xs">Entity (table / view)</label>
          <select
            value={form.entity_id}
            onChange={(e) => setForm({ ...form, entity_id: e.target.value, field_name: "" })}
            disabled={!form.connection_id}
            className={cn(field, "mt-1", !form.connection_id && "opacity-40")}
          >
            <option value="">Select entity…</option>
            {(entities ?? [])
              .filter((e) => e.is_allowed)
              .map((e) => (
                <option key={e.id} value={e.id}>
                  {e.schema_name !== "public" ? `${e.schema_name}.` : ""}{e.entity_name}
                </option>
              ))}
          </select>
          {form.connection_id && entities && entities.filter((e) => e.is_allowed).length === 0 && (
            <p className="mt-0.5 text-[10px] text-warning">No allowed entities. Mark entities as ALLOWED in Data Connections first.</p>
          )}
        </div>

        <div className="md:col-span-2">
          <label className="label-xs">Field (column) <span className="text-muted-foreground">(what it's called in this company's DB)</span></label>
          <select
            value={form.field_name}
            onChange={(e) => setForm({ ...form, field_name: e.target.value })}
            disabled={!form.entity_id}
            className={cn(field, "mt-1", !form.entity_id && "opacity-40")}
          >
            <option value="">Select column…</option>
            {availableColumns.map((c) => (
              <option key={c.name} value={c.name}>
                {c.name} ({c.data_type}){c.is_primary_key ? " [PK]" : ""}
              </option>
            ))}
          </select>
        </div>

        <div className="md:col-span-2">
          <label className="label-xs">Display label <span className="text-muted-foreground">(optional, human-readable)</span></label>
          <input
            value={form.display_label}
            onChange={(e) => setForm({ ...form, display_label: e.target.value })}
            placeholder="e.g. Campaign Name"
            className={cn(field, "mt-1")}
          />
        </div>
      </div>

      <div className="flex gap-2">
        <button
          type="submit"
          disabled={createMutation.isPending}
          className="flex items-center gap-1.5 border border-primary px-3 py-1.5 font-mono text-[10px] tracking-[0.12em] text-primary hover:bg-primary/10 disabled:opacity-40"
        >
          {createMutation.isPending ? <><RefreshCw className="size-3 animate-spin" /> SAVING…</> : "SAVE MAPPING"}
        </button>
        <button
          type="button"
          onClick={onDone}
          className="border border-border px-3 py-1.5 font-mono text-[10px] text-muted-foreground hover:text-foreground"
        >
          CANCEL
        </button>
      </div>
    </form>
  );
}

// ── Mapping row ───────────────────────────────────────────────────────────────

function MappingRow({
  mapping,
  connName,
  entityName,
}: {
  mapping: SemanticMappingFE;
  connName: string;
  entityName: string;
}) {
  const deleteMutation = useDeleteSemanticMapping();

  return (
    <div className="grid grid-cols-[1fr_1.2fr_1fr_auto] items-center gap-3 border-b border-border px-3 py-2 last:border-0 hover:bg-surface">
      <div className="flex items-center gap-1.5">
        <Tag className="size-3 shrink-0 text-primary" />
        <span className="font-mono text-[12px] text-primary">{mapping.semantic_concept}</span>
      </div>
      <div className="min-w-0">
        <p className="truncate font-mono text-[11px] text-muted-foreground">{connName}</p>
        <p className="truncate font-mono text-[11px]">{entityName}</p>
      </div>
      <div>
        <span className="font-mono text-[12px]">{mapping.field_name}</span>
        {mapping.display_label && (
          <span className="ml-1 text-[11px] text-muted-foreground">({mapping.display_label})</span>
        )}
      </div>
      <button
        onClick={() =>
          deleteMutation.mutate(mapping.id, {
            onSuccess: () => toast.success("Mapping deleted."),
            onError: (err) => toast.error(err.message),
          })
        }
        disabled={deleteMutation.isPending}
        className="text-muted-foreground hover:text-destructive disabled:opacity-30"
      >
        <Trash2 className="size-3.5" strokeWidth={1.5} />
      </button>
    </div>
  );
}

// ── Main panel ────────────────────────────────────────────────────────────────

export function SemanticMappingPanel() {
  const { data: mappings, isLoading } = useSemanticMappings();
  const { data: connections } = useDataConnections();
  const [adding, setAdding] = useState(false);

  if (!USE_REAL_API) {
    return (
      <div className="border border-dashed border-border p-3 text-center">
        <p className="text-[12px] text-muted-foreground">
          Semantic mappings require real API mode (<code className="font-mono text-[11px]">VITE_USE_REAL_API=true</code>).
        </p>
      </div>
    );
  }

  // Build lookup maps for display names
  const connNameMap: Record<string, string> = {};
  for (const c of connections ?? []) connNameMap[c.id] = c.display_name;

  // Group mappings by semantic concept
  const byConceptMap = new Map<string, SemanticMappingFE[]>();
  for (const m of mappings ?? []) {
    const arr = byConceptMap.get(m.semantic_concept) ?? [];
    arr.push(m);
    byConceptMap.set(m.semantic_concept, arr);
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-[13px] font-semibold">Semantic Data Mappings</p>
          <p className="label-xs mt-0.5 text-muted-foreground">
            Map schema-agnostic concepts to actual fields in this company's database.
            The AI uses concept names — not raw column names.
          </p>
        </div>
        {!adding && (
          <button
            onClick={() => setAdding(true)}
            className="flex items-center gap-1.5 border border-primary px-3 py-1.5 font-mono text-[10px] tracking-[0.12em] text-primary hover:bg-primary/10"
          >
            <Plus className="size-3" /> ADD MAPPING
          </button>
        )}
      </div>

      {adding && <AddMappingForm onDone={() => setAdding(false)} />}

      {/* Usage example */}
      <div className="border border-border bg-surface-2 px-3 py-2">
        <p className="text-[11px] text-muted-foreground">
          <span className="text-foreground">Example:</span> Map <code className="font-mono text-primary">campaign_name</code> → your company's <code className="font-mono">marketing_activity.name</code> column. The agent queries <code className="font-mono text-primary">campaign_name</code> and the platform translates it automatically.
        </p>
      </div>

      {isLoading && (
        <div className="flex items-center gap-2 text-[12px] text-muted-foreground">
          <RefreshCw className="size-3 animate-spin" /> Loading mappings…
        </div>
      )}

      {!isLoading && byConceptMap.size === 0 && !adding && (
        <div className="border border-dashed border-border p-4 text-center">
          <Tag className="mx-auto size-5 text-muted-foreground" />
          <p className="mt-2 text-[12px] text-muted-foreground">No semantic mappings yet.</p>
          <p className="mt-1 text-[11px] text-muted-foreground">
            Add mappings to let the DMM query company data using business concepts.
          </p>
        </div>
      )}

      {byConceptMap.size > 0 && (
        <div className="border border-border">
          <div className="grid grid-cols-[1fr_1.2fr_1fr_auto] gap-3 border-b border-border bg-surface-2 px-3 py-1.5">
            <span className="label-xs">Semantic concept</span>
            <span className="label-xs">Connection / Entity</span>
            <span className="label-xs">Field → mapped column</span>
            <span className="label-xs" />
          </div>
          {Array.from(byConceptMap.entries()).map(([concept, conceptMappings]) => (
            <div key={concept}>
              {conceptMappings.map((m) => (
                <MappingRow
                  key={m.id}
                  mapping={m}
                  connName={connNameMap[m.connection_id] ?? m.connection_id.slice(0, 8)}
                  entityName={m.entity_id.slice(0, 8)}
                />
              ))}
            </div>
          ))}
        </div>
      )}

      <p className="text-[10px] text-muted-foreground">
        Concepts are schema-agnostic — different companies can map the same concept to different tables and columns.
        Database credentials are never exposed through this interface.
      </p>
    </div>
  );
}
