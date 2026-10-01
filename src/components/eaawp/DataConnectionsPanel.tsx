/**
 * DataConnectionsPanel
 *
 * Lets a Company Administrator create, test, discover, and permission-configure
 * external data source connections for EAAWP.
 *
 * Security notes enforced in this component:
 * - Passwords are sent to the backend exactly once (on create).
 * - Passwords are NEVER stored in React state after submission.
 * - Connection status is always fetched from the real backend — never inferred.
 * - "Connected" is only shown when the backend test actually succeeded.
 * - Credentials are never displayed after creation.
 */
import { useState } from "react";
import { toast } from "sonner";
import {
  Plus,
  RefreshCw,
  Trash2,
  CheckCircle,
  XCircle,
  Clock,
  Database,
  ChevronDown,
  ChevronRight,
  ShieldCheck,
  ShieldOff,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { USE_REAL_API } from "@/lib/api-client";
import {
  useDataConnections,
  useCreateConnection,
  useDeleteConnection,
  useTestConnection,
  useDiscoverSchema,
  useSchemaEntities,
  useSetEntityPermission,
  useBulkEntityPermission,
  type DataConnectionFE,
  type DataConnectionCreate,
  type SchemaEntityFE,
  type ConnectionStatus,
} from "@/hooks/use-api";
import { SemanticMappingPanel } from "./SemanticMappingPanel";

// ── Status badge ──────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: ConnectionStatus }) {
  const cfg = {
    not_tested: { icon: Clock, cls: "text-muted-foreground border-muted-foreground/40", label: "NOT TESTED" },
    testing:    { icon: RefreshCw, cls: "text-warning border-warning/40 animate-pulse", label: "TESTING" },
    connected:  { icon: CheckCircle, cls: "text-success border-success/40", label: "CONNECTED" },
    failed:     { icon: XCircle, cls: "text-destructive border-destructive/40", label: "FAILED" },
  }[status];
  const Icon = cfg.icon;
  return (
    <span className={cn("inline-flex items-center gap-1 border px-1.5 py-0.5 font-mono text-[10px] tracking-[0.08em]", cfg.cls)}>
      <Icon className="size-2.5" /> {cfg.label}
    </span>
  );
}

// ── Add connection form ───────────────────────────────────────────────────────

const DEFAULT_PORTS: Record<string, number> = { postgresql: 5432, mysql: 3306 };

function AddConnectionForm({ onDone }: { onDone: () => void }) {
  const createMutation = useCreateConnection();
  const [form, setForm] = useState<DataConnectionCreate>({
    display_name: "",
    db_type: "postgresql",
    host: "",
    port: 5432,
    database_name: "",
    username: "",
    password: "",
    ssl_required: true,
    created_by: "admin",
  });
  const [passwordEntered, setPasswordEntered] = useState(false);

  function handleDbTypeChange(t: string) {
    setForm((f) => ({ ...f, db_type: t, port: DEFAULT_PORTS[t] ?? f.port }));
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.display_name || !form.host || !form.database_name || !form.username || !form.password) {
      toast.error("All fields are required.");
      return;
    }
    createMutation.mutate(form, {
      onSuccess: () => {
        toast.success("Connection created — run Test to verify credentials.");
        onDone();
      },
      onError: (err) => toast.error(err.message),
    });
  }

  const field = "h-8 w-full border border-input bg-background px-2 text-[13px] outline-none focus:border-ring";

  return (
    <form onSubmit={(e) => void submit(e)} className="space-y-3 border border-border bg-surface p-3">
      <p className="font-mono text-[10px] tracking-[0.14em] text-muted-foreground">NEW DATA CONNECTION</p>

      <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
        <div>
          <label className="label-xs">Display name</label>
          <input value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })}
            placeholder="e.g. Marketing DB" className={cn(field, "mt-1")} />
        </div>
        <div>
          <label className="label-xs">Database type</label>
          <select value={form.db_type} onChange={(e) => handleDbTypeChange(e.target.value)}
            className={cn(field, "mt-1 appearance-none")}>
            <option value="postgresql">PostgreSQL</option>
            <option value="mysql">MySQL / MariaDB</option>
          </select>
        </div>
        <div>
          <label className="label-xs">Host</label>
          <input value={form.host} onChange={(e) => setForm({ ...form, host: e.target.value })}
            placeholder="db.example.com" className={cn(field, "mt-1")} />
        </div>
        <div>
          <label className="label-xs">Port</label>
          <input type="number" value={form.port} onChange={(e) => setForm({ ...form, port: Number(e.target.value) })}
            className={cn(field, "mt-1")} />
        </div>
        <div>
          <label className="label-xs">Database name</label>
          <input value={form.database_name} onChange={(e) => setForm({ ...form, database_name: e.target.value })}
            placeholder="mydb" className={cn(field, "mt-1")} />
        </div>
        <div>
          <label className="label-xs">Username</label>
          <input value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })}
            placeholder="readonly_user" className={cn(field, "mt-1")} autoComplete="off" />
        </div>
        <div className="md:col-span-2">
          <label className="label-xs">Password <span className="text-muted-foreground">(sent once, stored encrypted)</span></label>
          <input type="password" value={form.password}
            onChange={(e) => { setForm({ ...form, password: e.target.value }); setPasswordEntered(e.target.value.length > 0); }}
            placeholder="••••••••" className={cn(field, "mt-1")} autoComplete="new-password" />
          {passwordEntered && (
            <p className="mt-1 text-[10px] text-success">
              ✓ Password will be encrypted at rest — never returned in API responses.
            </p>
          )}
        </div>
      </div>

      <div className="flex items-center gap-2">
        <input type="checkbox" id="ssl" checked={form.ssl_required}
          onChange={(e) => setForm({ ...form, ssl_required: e.target.checked })}
          className="size-3.5" />
        <label htmlFor="ssl" className="text-[13px] text-muted-foreground">Require SSL/TLS</label>
      </div>

      <div className="flex gap-2">
        <button type="submit" disabled={createMutation.isPending}
          className="flex items-center gap-1.5 border border-primary px-3 py-1.5 font-mono text-[10px] tracking-[0.12em] text-primary hover:bg-primary/10 disabled:opacity-40">
          {createMutation.isPending ? <><RefreshCw className="size-3 animate-spin" /> SAVING…</> : "SAVE CONNECTION"}
        </button>
        <button type="button" onClick={onDone}
          className="border border-border px-3 py-1.5 font-mono text-[10px] text-muted-foreground hover:text-foreground">
          CANCEL
        </button>
      </div>
    </form>
  );
}

// ── Entity permission row ─────────────────────────────────────────────────────

function EntityRow({
  entity,
  connId,
}: {
  entity: SchemaEntityFE;
  connId: string;
}) {
  const setPermission = useSetEntityPermission();
  const [open, setOpen] = useState(false);

  function toggle() {
    setPermission.mutate(
      { entityId: entity.id, connId, is_allowed: !entity.is_allowed },
      { onError: (err) => toast.error(err.message) },
    );
  }

  return (
    <div className="border-b border-border last:border-0">
      <div className="flex items-center gap-2 px-3 py-2 hover:bg-surface">
        <button onClick={() => setOpen((o) => !o)} className="text-muted-foreground">
          {open ? <ChevronDown className="size-3" /> : <ChevronRight className="size-3" />}
        </button>
        <Database className="size-3 shrink-0 text-muted-foreground" />
        <span className="flex-1 font-mono text-[12px]">
          {entity.schema_name !== "public" && entity.schema_name !== entity.entity_name
            ? `${entity.schema_name}.`
            : ""}
          {entity.entity_name}
        </span>
        <span className="font-mono text-[10px] text-muted-foreground">{entity.entity_type}</span>
        {entity.row_count_estimate != null && (
          <span className="font-mono text-[10px] text-muted-foreground">
            ~{entity.row_count_estimate.toLocaleString()} rows
          </span>
        )}
        <button
          onClick={toggle}
          disabled={setPermission.isPending}
          title={entity.is_allowed ? "Click to deny access" : "Click to allow access"}
          className={cn(
            "flex items-center gap-1 border px-2 py-0.5 font-mono text-[10px] tracking-[0.08em]",
            entity.is_allowed
              ? "border-success/50 text-success hover:border-destructive hover:text-destructive"
              : "border-border text-muted-foreground hover:border-success hover:text-success",
          )}
        >
          {entity.is_allowed ? <><ShieldCheck className="size-3" /> ALLOWED</> : <><ShieldOff className="size-3" /> DENIED</>}
        </button>
      </div>
      {open && entity.columns.length > 0 && (
        <div className="border-t border-border bg-surface-2 px-8 py-2">
          <div className="grid grid-cols-[2fr_1fr_auto_auto] gap-x-3 gap-y-0.5">
            <span className="label-xs">Column</span>
            <span className="label-xs">Type</span>
            <span className="label-xs">Nullable</span>
            <span className="label-xs">PK</span>
            {entity.columns.map((c) => (
              <>
                <span key={`${c.name}-n`} className="truncate font-mono text-[11px]">{c.name}</span>
                <span key={`${c.name}-t`} className="font-mono text-[11px] text-muted-foreground">{c.data_type}</span>
                <span key={`${c.name}-nl`} className={cn("font-mono text-[10px]", c.is_nullable ? "text-muted-foreground" : "text-foreground")}>
                  {c.is_nullable ? "yes" : "no"}
                </span>
                <span key={`${c.name}-pk`} className={cn("font-mono text-[10px]", c.is_primary_key ? "text-primary" : "text-muted-foreground")}>
                  {c.is_primary_key ? "PK" : "—"}
                </span>
              </>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Connection card ───────────────────────────────────────────────────────────

function ConnectionCard({ conn }: { conn: DataConnectionFE }) {
  const [expanded, setExpanded] = useState(false);
  const testMutation = useTestConnection();
  const discoverMutation = useDiscoverSchema();
  const deleteMutation = useDeleteConnection();
  const bulkPermission = useBulkEntityPermission();
  const { data: entities, isLoading: entitiesLoading } = useSchemaEntities(expanded ? conn.id : null);

  function runTest() {
    testMutation.mutate(conn.id, {
      onSuccess: (res) => {
        if (res.success) toast.success(`Connected — ${res.server_version ?? "server OK"}`);
        else toast.error(`Connection failed: ${res.error_message ?? "unknown error"}`);
      },
      onError: (err) => toast.error(err.message),
    });
  }

  function runDiscover() {
    discoverMutation.mutate(conn.id, {
      onSuccess: (entities) => {
        toast.success(`Discovered ${entities.length} entities.`);
        setExpanded(true);
      },
      onError: (err) => toast.error(err.message),
    });
  }

  function handleDelete() {
    deleteMutation.mutate(conn.id, {
      onSuccess: () => toast.success("Connection deleted."),
      onError: (err) => toast.error(err.message),
    });
  }

  function allowAll() {
    if (!entities) return;
    const ids = entities.map((e) => e.id);
    bulkPermission.mutate(
      { connId: conn.id, entity_ids: ids, is_allowed: true },
      { onSuccess: (r) => toast.success(`Allowed ${r.updated} entities.`) },
    );
  }

  function denyAll() {
    if (!entities) return;
    const ids = entities.map((e) => e.id);
    bulkPermission.mutate(
      { connId: conn.id, entity_ids: ids, is_allowed: false },
      { onSuccess: (r) => toast.success(`Denied ${r.updated} entities.`) },
    );
  }

  return (
    <div className="border border-border">
      {/* Header */}
      <div className="flex items-center gap-3 px-3 py-2.5">
        <Database className="size-4 shrink-0 text-muted-foreground" />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-[13px] font-medium">{conn.display_name}</span>
            <span className="font-mono text-[10px] text-muted-foreground">{conn.db_type}</span>
          </div>
          <p className="font-mono text-[10px] text-muted-foreground">
            {conn.host}:{conn.port} / {conn.database_name} · {conn.username}
          </p>
        </div>
        <StatusBadge status={conn.status} />
        <div className="flex items-center gap-1.5">
          <button
            onClick={runTest}
            disabled={testMutation.isPending}
            className="border border-border px-2 py-1 font-mono text-[10px] text-muted-foreground hover:border-primary hover:text-primary disabled:opacity-40"
          >
            {testMutation.isPending ? <RefreshCw className="size-3 animate-spin" /> : "TEST"}
          </button>
          <button
            onClick={runDiscover}
            disabled={discoverMutation.isPending || conn.status !== "connected"}
            title={conn.status !== "connected" ? "Test connection first" : "Discover schema"}
            className="border border-border px-2 py-1 font-mono text-[10px] text-muted-foreground hover:border-primary hover:text-primary disabled:opacity-40"
          >
            {discoverMutation.isPending ? <RefreshCw className="size-3 animate-spin" /> : "DISCOVER"}
          </button>
          {conn.entity_count > 0 && (
            <button
              onClick={() => setExpanded((e) => !e)}
              className="border border-border px-2 py-1 font-mono text-[10px] text-muted-foreground hover:text-foreground"
            >
              {expanded ? "HIDE" : `${conn.entity_count} ENTITIES`}
              <span className="ml-1 text-success">{conn.allowed_entity_count > 0 ? `(${conn.allowed_entity_count} allowed)` : ""}</span>
            </button>
          )}
          <button
            onClick={handleDelete}
            disabled={deleteMutation.isPending}
            className="text-muted-foreground hover:text-destructive disabled:opacity-30"
          >
            <Trash2 className="size-3.5" strokeWidth={1.5} />
          </button>
        </div>
      </div>

      {/* Error message */}
      {conn.status === "failed" && conn.error_message && (
        <div className="border-t border-destructive/20 bg-destructive/5 px-3 py-2 text-[12px] text-destructive">
          {conn.error_message}
        </div>
      )}

      {/* Entities panel */}
      {expanded && (
        <div className="border-t border-border">
          <div className="flex items-center justify-between px-3 py-1.5 bg-surface-2">
            <span className="label-xs">Schema entities — set AI access permissions</span>
            <div className="flex gap-1.5">
              <button
                onClick={allowAll}
                disabled={bulkPermission.isPending || !entities?.length}
                className="border border-success/50 px-2 py-0.5 font-mono text-[10px] text-success hover:bg-success/10 disabled:opacity-30"
              >
                ALLOW ALL
              </button>
              <button
                onClick={denyAll}
                disabled={bulkPermission.isPending || !entities?.length}
                className="border border-border px-2 py-0.5 font-mono text-[10px] text-muted-foreground hover:text-destructive disabled:opacity-30"
              >
                DENY ALL
              </button>
            </div>
          </div>
          {entitiesLoading && (
            <div className="flex items-center gap-2 px-3 py-3 text-[12px] text-muted-foreground">
              <RefreshCw className="size-3 animate-spin" /> Loading entities…
            </div>
          )}
          {!entitiesLoading && (!entities || entities.length === 0) && (
            <p className="px-3 py-3 text-[12px] text-muted-foreground">
              No entities discovered yet. Click DISCOVER to enumerate the schema.
            </p>
          )}
          {entities && entities.length > 0 && entities.map((e) => (
            <EntityRow key={e.id} entity={e} connId={conn.id} />
          ))}
        </div>
      )}
    </div>
  );
}

// ── Main panel ────────────────────────────────────────────────────────────────

export function DataConnectionsPanel() {
  const { data: connections, isLoading } = useDataConnections();
  const [adding, setAdding] = useState(false);

  if (!USE_REAL_API) {
    return (
      <div className="border border-dashed border-border p-4 text-center">
        <p className="text-[12px] text-muted-foreground">
          Company data connections require real API mode.
          Set <code className="font-mono text-[11px]">VITE_USE_REAL_API=true</code> to manage external database connections.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-[13px] font-semibold">Data Connections</p>
          <p className="label-xs text-muted-foreground mt-0.5">
            Connect authorized external databases. Credentials are encrypted at rest and never exposed to the AI.
          </p>
        </div>
        {!adding && (
          <button
            onClick={() => setAdding(true)}
            className="flex items-center gap-1.5 border border-primary px-3 py-1.5 font-mono text-[10px] tracking-[0.12em] text-primary hover:bg-primary/10"
          >
            <Plus className="size-3" /> ADD CONNECTION
          </button>
        )}
      </div>

      {adding && <AddConnectionForm onDone={() => setAdding(false)} />}

      {isLoading && (
        <div className="flex items-center gap-2 text-[12px] text-muted-foreground">
          <RefreshCw className="size-3 animate-spin" /> Loading connections…
        </div>
      )}

      {!isLoading && (!connections || connections.length === 0) && !adding && (
        <div className="border border-dashed border-border p-6 text-center">
          <Database className="mx-auto size-6 text-muted-foreground" />
          <p className="mt-2 text-[13px] text-muted-foreground">No data connections yet.</p>
          <p className="mt-1 text-[11px] text-muted-foreground">
            Add a PostgreSQL or MySQL connection to let the Digital Marketing Manager access authorised company data.
          </p>
        </div>
      )}

      {connections && connections.map((conn) => (
        <ConnectionCard key={conn.id} conn={conn} />
      ))}

      <p className="text-[10px] text-muted-foreground">
        Only entities marked ALLOWED are accessible to the AI. Database credentials are never sent to the LLM or returned in API responses.
      </p>

      {/* ── Semantic Data Mappings ── */}
      <div className="mt-6 border-t border-border pt-6">
        <SemanticMappingPanel />
      </div>
    </div>
  );
}
