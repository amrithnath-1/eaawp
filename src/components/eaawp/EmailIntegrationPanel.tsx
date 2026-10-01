/**
 * EmailIntegrationPanel — SMTP Email Integration Configuration
 *
 * Follows the same visual pattern as DataConnectionsPanel.
 * Lets administrators configure, test, enable/disable the SMTP integration.
 *
 * SECURITY:
 * - Password is sent once on create/update; never fetched back.
 * - password_hint ("••••••") confirms a password is stored.
 * - No credentials appear in any UI element after save.
 *
 * MOCK MODE (VITE_USE_REAL_API=false):
 * - Shows a clearly-labelled simulated configuration.
 * - All mutations inform the user that real mode is required.
 */

import { useState } from "react";
import {
  AlertTriangle,
  Check,
  CheckCircle,
  ChevronDown,
  ChevronRight,
  Info,
  Loader2,
  Mail,
  Pause,
  Play,
  RefreshCw,
  Trash2,
  XCircle,
} from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { USE_REAL_API } from "@/lib/api-client";
import {
  useEmailIntegration,
  useCreateEmailIntegration,
  useUpdateEmailIntegration,
  useDeleteEmailIntegration,
  useTestEmailIntegration,
  useEnableEmailIntegration,
  useDisableEmailIntegration,
  type EmailIntegrationFE,
  type SMTPConfigCreate,
} from "@/hooks/use-api";

// ── Status badge ──────────────────────────────────────────────────────────────

function StatusBadge({ status, enabled }: { status: string; enabled: boolean }) {
  if (!enabled) {
    return (
      <span className="border border-border px-1.5 py-0.5 font-mono text-[9px] tracking-widest text-muted-foreground">
        DISABLED
      </span>
    );
  }
  const map: Record<string, { label: string; cls: string; Icon: React.ElementType }> = {
    connected: { label: "CONNECTED", cls: "border-success/40 text-success", Icon: CheckCircle },
    not_tested: { label: "NOT TESTED", cls: "border-border text-muted-foreground", Icon: Info },
    not_configured: { label: "NOT CONFIGURED", cls: "border-border text-muted-foreground", Icon: Info },
    failed: { label: "FAILED", cls: "border-destructive/40 text-destructive", Icon: XCircle },
  };
  const entry = map[status] ?? { label: status.toUpperCase(), cls: "border-border text-muted-foreground", Icon: Info };
  return (
    <span className={cn("flex items-center gap-1 border px-1.5 py-0.5 font-mono text-[9px] tracking-widest", entry.cls)}>
      <entry.Icon className="size-2.5" strokeWidth={2} />
      {entry.label}
    </span>
  );
}

// ── SMTP config form ──────────────────────────────────────────────────────────

const TLS_OPTIONS = [
  { value: "starttls", label: "STARTTLS (port 587, recommended)" },
  { value: "ssl_tls", label: "SSL/TLS (port 465)" },
  { value: "none", label: "None (not recommended)" },
] as const;

type TLSMode = "starttls" | "ssl_tls" | "none";

interface FormState {
  display_name: string;
  smtp_host: string;
  smtp_port: string;
  username: string;
  password: string;
  tls_mode: TLSMode;
  sender_email: string;
  sender_display_name: string;
}

const EMPTY_FORM: FormState = {
  display_name: "Company Email",
  smtp_host: "",
  smtp_port: "587",
  username: "",
  password: "",
  tls_mode: "starttls",
  sender_email: "",
  sender_display_name: "",
};

function SMTPConfigForm({
  existing,
  onClose,
}: {
  existing?: EmailIntegrationFE;
  onClose: () => void;
}) {
  const [form, setForm] = useState<FormState>({
    display_name: existing?.display_name ?? EMPTY_FORM.display_name,
    smtp_host: existing?.smtp_host ?? "",
    smtp_port: String(existing?.smtp_port ?? 587),
    username: existing?.username ?? "",
    password: "",   // never pre-fill password — hint only
    tls_mode: (existing?.tls_mode as TLSMode) ?? "starttls",
    sender_email: existing?.sender_email ?? "",
    sender_display_name: existing?.sender_display_name ?? "",
  });

  const create = useCreateEmailIntegration();
  const update = useUpdateEmailIntegration();
  const isEditing = !!existing;
  const isPending = create.isPending || update.isPending;

  function set(key: keyof FormState, val: string) {
    setForm((f) => ({ ...f, [key]: val }));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();

    if (!USE_REAL_API) {
      toast.info(
        "Configuring email requires VITE_USE_REAL_API=true and the backend running.",
        { duration: 5000 },
      );
      onClose();
      return;
    }

    if (!isEditing && !form.password) {
      toast.error("Password is required when creating an integration.");
      return;
    }

    try {
      if (isEditing) {
        await update.mutateAsync({
          ...(form.display_name !== existing!.display_name ? { display_name: form.display_name } : {}),
          ...(form.smtp_host !== existing!.smtp_host ? { smtp_host: form.smtp_host } : {}),
          ...(String(form.smtp_port) !== String(existing!.smtp_port) ? { smtp_port: parseInt(form.smtp_port) } : {}),
          ...(form.username !== existing!.username ? { username: form.username } : {}),
          ...(form.password ? { password: form.password } : {}),
          ...(form.tls_mode !== existing!.tls_mode ? { tls_mode: form.tls_mode } : {}),
          ...(form.sender_email !== existing!.sender_email ? { sender_email: form.sender_email } : {}),
          ...(form.sender_display_name !== existing!.sender_display_name ? { sender_display_name: form.sender_display_name } : {}),
        });
        toast.success("Email integration updated");
      } else {
        const payload: SMTPConfigCreate = {
          display_name: form.display_name,
          smtp_host: form.smtp_host,
          smtp_port: parseInt(form.smtp_port),
          username: form.username,
          password: form.password,
          tls_mode: form.tls_mode,
          sender_email: form.sender_email,
          sender_display_name: form.sender_display_name,
        };
        await create.mutateAsync(payload);
        toast.success("Email integration configured");
      }
      onClose();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save");
    }
  }

  return (
    <form onSubmit={(e) => void handleSubmit(e)} className="border border-border bg-surface p-4 space-y-3">
      <div className="flex items-center justify-between border-b border-border pb-2">
        <h3 className="font-mono text-[11px] tracking-widest">
          {isEditing ? "UPDATE SMTP CONFIGURATION" : "CONFIGURE SMTP INTEGRATION"}
        </h3>
      </div>

      {!USE_REAL_API && (
        <div className="flex gap-2 border border-border bg-surface-2 p-2 text-[11px] text-muted-foreground">
          <Info className="size-3.5 shrink-0 mt-0.5 text-primary" strokeWidth={1.5} />
          <span>
            <strong>Simulated mode</strong> — submitting will not configure a real SMTP server.
            Set VITE_USE_REAL_API=true for production use.
          </span>
        </div>
      )}

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        {/* Display name */}
        <div className="md:col-span-2">
          <label className="label-xs">Display name</label>
          <input
            value={form.display_name}
            onChange={(e) => set("display_name", e.target.value)}
            className="mt-1 h-8 w-full border border-input bg-background px-2 text-[13px] outline-none focus:border-ring"
          />
        </div>

        {/* SMTP host */}
        <div>
          <label className="label-xs">SMTP host *</label>
          <input
            required
            value={form.smtp_host}
            onChange={(e) => set("smtp_host", e.target.value)}
            placeholder="smtp.example.com"
            className="mt-1 h-8 w-full border border-input bg-background px-2 font-mono text-[12px] outline-none focus:border-ring"
          />
        </div>

        {/* SMTP port */}
        <div>
          <label className="label-xs">SMTP port *</label>
          <input
            required
            type="number"
            min={1}
            max={65535}
            value={form.smtp_port}
            onChange={(e) => set("smtp_port", e.target.value)}
            className="mt-1 h-8 w-full border border-input bg-background px-2 text-[13px] outline-none focus:border-ring"
          />
        </div>

        {/* TLS mode */}
        <div className="md:col-span-2">
          <label className="label-xs">TLS mode</label>
          <div className="mt-1 flex flex-wrap gap-1.5">
            {TLS_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                type="button"
                onClick={() => set("tls_mode", opt.value)}
                className={cn(
                  "border px-2 py-1 text-[11px]",
                  form.tls_mode === opt.value
                    ? "border-primary text-primary"
                    : "border-border text-muted-foreground hover:text-foreground",
                )}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>

        {/* Username */}
        <div>
          <label className="label-xs">Username *</label>
          <input
            required
            value={form.username}
            onChange={(e) => set("username", e.target.value)}
            placeholder="user@example.com"
            autoComplete="username"
            className="mt-1 h-8 w-full border border-input bg-background px-2 font-mono text-[12px] outline-none focus:border-ring"
          />
        </div>

        {/* Password */}
        <div>
          <label className="label-xs">
            Password {isEditing ? "(leave blank to keep existing)" : "*"}
          </label>
          {isEditing && existing?.password_hint && (
            <p className="mt-0.5 font-mono text-[10px] text-muted-foreground">
              Current: {existing.password_hint}
            </p>
          )}
          <input
            required={!isEditing}
            type="password"
            value={form.password}
            onChange={(e) => set("password", e.target.value)}
            placeholder={isEditing ? "Enter new password to change" : "SMTP password"}
            autoComplete="new-password"
            className="mt-1 h-8 w-full border border-input bg-background px-2 text-[13px] outline-none focus:border-ring"
          />
          <p className="mt-0.5 text-[10px] text-muted-foreground">
            Encrypted at rest — never returned after save.
          </p>
        </div>

        {/* Sender email */}
        <div>
          <label className="label-xs">Sender email *</label>
          <input
            required
            type="email"
            value={form.sender_email}
            onChange={(e) => set("sender_email", e.target.value)}
            placeholder="noreply@example.com"
            className="mt-1 h-8 w-full border border-input bg-background px-2 font-mono text-[12px] outline-none focus:border-ring"
          />
        </div>

        {/* Sender display name */}
        <div>
          <label className="label-xs">Sender display name</label>
          <input
            value={form.sender_display_name}
            onChange={(e) => set("sender_display_name", e.target.value)}
            placeholder="EAAWP Platform"
            className="mt-1 h-8 w-full border border-input bg-background px-2 text-[13px] outline-none focus:border-ring"
          />
        </div>
      </div>

      <div className="flex gap-2 border-t border-border pt-3">
        <button
          type="submit"
          disabled={isPending}
          className="flex items-center gap-1.5 border border-primary px-4 py-1.5 font-mono text-[10px] tracking-widest text-primary hover:bg-primary/10 disabled:opacity-40"
        >
          {isPending ? <Loader2 className="size-3 animate-spin" /> : <Check className="size-3" strokeWidth={2.5} />}
          {isEditing ? "SAVE CHANGES" : "SAVE INTEGRATION"}
        </button>
        <button
          type="button"
          onClick={onClose}
          className="border border-border px-3 py-1.5 font-mono text-[10px] tracking-widest text-muted-foreground hover:text-foreground"
        >
          CANCEL
        </button>
      </div>
    </form>
  );
}

// ── Main panel ────────────────────────────────────────────────────────────────

export function EmailIntegrationPanel() {
  const { data: integration, isLoading, isError, refetch, isFetching } = useEmailIntegration();
  const testConn = useTestEmailIntegration();
  const del = useDeleteEmailIntegration();
  const enable = useEnableEmailIntegration();
  const disable = useDisableEmailIntegration();

  const [showForm, setShowForm] = useState(false);
  const [showAudit, setShowAudit] = useState(false);

  function handleTest() {
    if (!USE_REAL_API) {
      toast.info("Connection test requires VITE_USE_REAL_API=true.");
      return;
    }
    testConn.mutate(undefined, {
      onSuccess: (r) => {
        if (r.success) toast.success("SMTP connection successful");
        else toast.error(`SMTP test failed: ${r.error_message ?? "Unknown error"}`);
      },
      onError: (e) => toast.error(e.message),
    });
  }

  function handleDelete() {
    if (!USE_REAL_API) { toast.info("Requires real API mode."); return; }
    if (!confirm("Remove SMTP integration? Audit logs are preserved.")) return;
    del.mutate(undefined, {
      onSuccess: () => toast.success("Integration removed"),
      onError: (e) => toast.error(e.message),
    });
  }

  function handleToggle() {
    if (!USE_REAL_API) { toast.info("Requires real API mode."); return; }
    if (!integration) return;
    if (integration.is_enabled) {
      disable.mutate(undefined, { onSuccess: () => toast.success("Integration disabled") });
    } else {
      enable.mutate(undefined, { onSuccess: () => toast.success("Integration enabled") });
    }
  }

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 p-3 text-[13px] text-muted-foreground">
        <Loader2 className="size-4 animate-spin" />
        Loading email configuration…
      </div>
    );
  }

  if (isError && USE_REAL_API) {
    return (
      <div className="flex items-center gap-2 p-3 text-[13px] text-destructive">
        <AlertTriangle className="size-4 shrink-0" strokeWidth={1.5} />
        Failed to load email integration. Check backend connection.
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {/* Mock mode banner */}
      {!USE_REAL_API && (
        <div className="flex gap-2 border border-border bg-surface-2 p-2 text-[11px] text-muted-foreground">
          <Info className="size-3.5 shrink-0 mt-0.5 text-muted-foreground" strokeWidth={1.5} />
          <span>
            <strong>Simulated mode</strong> — real email sending requires VITE_USE_REAL_API=true.
            In mock mode, email actions are simulated and no external emails are sent.
          </span>
        </div>
      )}

      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-[12px] text-muted-foreground">
          <Mail className="size-3.5" strokeWidth={1.5} />
          {integration ? "SMTP configured" : "No SMTP integration"}
        </div>
        <div className="flex items-center gap-1.5">
          <button
            onClick={() => void refetch()}
            disabled={isFetching}
            className="border border-border px-1.5 py-1 text-muted-foreground hover:text-foreground disabled:opacity-40"
          >
            <RefreshCw className={cn("size-3", isFetching && "animate-spin")} strokeWidth={1.5} />
          </button>
          <button
            onClick={() => setShowForm(true)}
            className="border border-primary px-2 py-1 font-mono text-[10px] tracking-widest text-primary hover:bg-primary/10"
          >
            {integration ? "EDIT" : "CONFIGURE"}
          </button>
        </div>
      </div>

      {/* Form */}
      {showForm && (
        <SMTPConfigForm
          {...(integration !== null && integration !== undefined ? { existing: integration } : {})}
          onClose={() => setShowForm(false)}
        />
      )}

      {/* Integration status card */}
      {integration && !showForm && (
        <div className="border border-border">
          <div className="flex items-center justify-between px-3 py-2.5">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="text-[13px] font-medium">{integration.display_name}</span>
                <StatusBadge status={integration.status} enabled={integration.is_enabled} />
              </div>
              <p className="mt-0.5 font-mono text-[11px] text-muted-foreground">
                {integration.smtp_host}:{integration.smtp_port} · {integration.tls_mode.toUpperCase()}
              </p>
              <p className="font-mono text-[11px] text-muted-foreground">
                From: {integration.sender_email}
                {integration.sender_display_name ? ` (${integration.sender_display_name})` : ""}
              </p>
              <p className="font-mono text-[11px] text-muted-foreground">
                User: {integration.username} · Password: {integration.password_hint}
              </p>
              {integration.last_tested_at && (
                <p className="text-[10px] text-muted-foreground">
                  Last tested: {new Date(integration.last_tested_at).toLocaleString()}
                  {integration.error_message && (
                    <span className="ml-1 text-destructive">· {integration.error_message.slice(0, 80)}</span>
                  )}
                </p>
              )}
            </div>

            <div className="flex shrink-0 items-center gap-1">
              {/* Test */}
              <button
                onClick={handleTest}
                disabled={testConn.isPending}
                title="Test SMTP connection"
                className="border border-border px-2 py-1 font-mono text-[10px] tracking-widest text-muted-foreground hover:text-primary hover:border-primary disabled:opacity-40"
              >
                {testConn.isPending ? <Loader2 className="size-3 animate-spin" /> : "TEST"}
              </button>

              {/* Enable/Disable */}
              <button
                onClick={handleToggle}
                disabled={enable.isPending || disable.isPending}
                title={integration.is_enabled ? "Disable" : "Enable"}
                className={cn(
                  "border px-1.5 py-1 disabled:opacity-40",
                  integration.is_enabled
                    ? "border-primary text-primary hover:bg-primary/10"
                    : "border-border text-muted-foreground hover:text-foreground",
                )}
              >
                {integration.is_enabled
                  ? <Pause className="size-3" strokeWidth={2} />
                  : <Play className="size-3" strokeWidth={2} />}
              </button>

              {/* Delete */}
              <button
                onClick={handleDelete}
                disabled={del.isPending}
                title="Remove integration"
                className="border border-border px-1.5 py-1 text-muted-foreground hover:border-destructive hover:text-destructive disabled:opacity-40"
              >
                <Trash2 className="size-3" strokeWidth={1.5} />
              </button>
            </div>
          </div>

          {/* Audit toggle */}
          <div className="border-t border-border px-3 py-1.5">
            <button
              onClick={() => setShowAudit((s) => !s)}
              className="flex items-center gap-1 font-mono text-[10px] tracking-widest text-muted-foreground hover:text-foreground"
            >
              {showAudit ? <ChevronDown className="size-3" /> : <ChevronRight className="size-3" />}
              EMAIL SEND AUDIT
            </button>
          </div>
          {showAudit && <EmailAuditSection />}
        </div>
      )}

      {/* Empty state */}
      {!integration && !showForm && (
        <div className="border border-border bg-surface-2 p-5 text-center text-[13px] text-muted-foreground">
          <Mail className="mx-auto mb-2 size-8 opacity-30" strokeWidth={1} />
          <p className="font-medium">No SMTP integration configured</p>
          <p className="mt-1 text-[11px]">
            Configure SMTP to allow the Digital Marketing Manager to send emails
            after human approval.
          </p>
        </div>
      )}

      <p className="text-[10px] text-muted-foreground">
        All email sends require explicit human approval. Credentials are encrypted
        at rest and never returned to the frontend or LLM.
      </p>
    </div>
  );
}

// ── Audit sub-section ─────────────────────────────────────────────────────────

function EmailAuditSection() {
  const { data: audit, isLoading } = useEmailAuditLog();

  if (!USE_REAL_API) {
    return (
      <div className="border-t border-border px-3 py-2 text-[11px] text-muted-foreground italic">
        Email audit log requires VITE_USE_REAL_API=true.
      </div>
    );
  }

  if (isLoading) {
    return <div className="border-t border-border p-3"><Loader2 className="size-4 animate-spin text-muted-foreground" /></div>;
  }

  if (!audit?.length) {
    return (
      <div className="border-t border-border px-3 py-2 text-[11px] text-muted-foreground">
        No email send attempts recorded yet.
      </div>
    );
  }

  return (
    <div className="border-t border-border">
      <table className="w-full text-[11px]">
        <thead>
          <tr className="border-b border-border bg-surface-2">
            <th className="px-2 py-1 text-left font-mono text-[10px] text-muted-foreground">Time</th>
            <th className="px-2 py-1 text-left font-mono text-[10px] text-muted-foreground">Recipients</th>
            <th className="px-2 py-1 text-left font-mono text-[10px] text-muted-foreground">Domains</th>
            <th className="px-2 py-1 text-left font-mono text-[10px] text-muted-foreground">Result</th>
          </tr>
        </thead>
        <tbody>
          {audit.slice(0, 20).map((row) => (
            <tr key={row.id} className="border-b border-border last:border-0">
              <td className="px-2 py-1 text-muted-foreground">
                {new Date(row.attempted_at).toLocaleString()}
              </td>
              <td className="px-2 py-1 text-muted-foreground">{row.recipient_count}</td>
              <td className="px-2 py-1 font-mono text-[10px] text-muted-foreground">
                {row.recipient_domains || "—"}
              </td>
              <td className="px-2 py-1">
                {row.success ? (
                  <span className="text-success">✓ Sent</span>
                ) : (
                  <span className="text-destructive" title={row.error_message ?? ""}>✗ Failed</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// Need to import useEmailAuditLog — defined below in hooks, so import here:
import { useEmailAuditLog } from "@/hooks/use-api";
