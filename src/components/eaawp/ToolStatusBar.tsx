/**
 * The selected AI employee's real capability summary for the chat header, with a details dialog.
 * Every number comes from GET /api/v1/workspace/tools (the same rules the execution path applies).
 */
import { Link } from "@tanstack/react-router";
import { Info, Loader2 } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { useWorkspaceTools, type ToolEntry, type ToolState } from "@/hooks/use-conversations";
import { cn } from "@/lib/utils";

const TONE: Record<ToolState, string> = {
  available: "border-success/50 text-success",
  requires_approval: "border-warning/60 text-warning",
  disabled: "border-border text-muted-foreground",
  not_implemented: "border-border text-muted-foreground",
  integration_not_connected: "border-destructive/50 text-destructive",
  integration_disabled: "border-border text-muted-foreground",
  blocked_high_risk: "border-destructive/50 text-destructive",
  capability_missing: "border-destructive/50 text-destructive",
};

function ToolRow({ t }: { t: ToolEntry }) {
  return (
    <li className="flex flex-col gap-1 border-b border-border py-2 last:border-0 sm:flex-row sm:items-start sm:justify-between">
      <div className="min-w-0">
        <p className="text-[12px] text-foreground">
          {t.name}
          <span className="ml-1.5 font-mono text-[9px] tracking-[0.08em] text-muted-foreground">
            {t.kind === "action" ? "ACTION" : "READ"}
            {t.integration ? ` · ${t.integration.name.toUpperCase()}` : ""}
          </span>
        </p>
        {t.description && <p className="text-[11px] text-muted-foreground">{t.description}</p>}
      </div>
      <span
        className={cn(
          "shrink-0 self-start border px-1.5 py-0.5 font-mono text-[9px] tracking-[0.06em]",
          TONE[t.status],
        )}
      >
        {t.status_label}
      </span>
    </li>
  );
}

export function ToolStatusBar({ roleKey }: { roleKey: string | undefined }) {
  const { data, isLoading, isError } = useWorkspaceTools(roleKey);
  if (!roleKey) return null;
  if (isLoading) {
    return (
      <span className="inline-flex items-center gap-1 font-mono text-[9px] text-muted-foreground">
        <Loader2 className="size-3 animate-spin" /> CHECKING TOOLS…
      </span>
    );
  }
  if (isError || !data) {
    return (
      <span className="font-mono text-[9px] text-muted-foreground">· TOOL STATUS UNAVAILABLE</span>
    );
  }
  const c = data.counts;
  const ops = data.operations;
  const builtIn = data.tools.filter((t) => t.source === "built_in");
  const integration = data.tools.filter((t) => t.source === "integration");
  const platform = data.tools.filter((t) => t.source === "platform");

  return (
    <Dialog>
      <DialogTrigger asChild>
        <button
          data-testid="cabin-ai-context"
          className="inline-flex flex-wrap items-center gap-x-1.5 font-mono text-[9px] tracking-[0.08em] text-muted-foreground hover:text-foreground"
          aria-label="Show this AI employee's tools and approvals"
        >
          <span>· {c.available ?? 0} READY</span>
          <span>· {c.requires_approval ?? 0} NEED APPROVAL TO RUN</span>
          {(c.blocked ?? 0) > 0 && <span>· {c.blocked} UNAVAILABLE</span>}
          <span className={cn((data.approvals.pending ?? 0) > 0 && "text-warning")}>
            · {data.approvals.pending ?? 0} PENDING APPROVAL
            {(data.approvals.pending ?? 0) === 1 ? "" : "S"}
          </span>
          <Info className="size-3" />
        </button>
      </DialogTrigger>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{data.role_name} — tools and approvals</DialogTitle>
          <DialogDescription>
            Live status from the server. “Ready” tools run when the AI employee needs them; tools
            that need approval only run after an administrator approves that specific action.
          </DialogDescription>
        </DialogHeader>

        <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {[
            ["Ready", c.available ?? 0],
            ["Need approval", c.requires_approval ?? 0],
            ["Unavailable", c.blocked ?? 0],
            ["Pending approvals", data.approvals.pending ?? 0],
          ].map(([k, v]) => (
            <div key={k} className="border border-border p-2">
              <dt className="font-mono text-[9px] tracking-[0.1em] text-muted-foreground">
                {String(k).toUpperCase()}
              </dt>
              <dd className="text-lg font-medium">{v}</dd>
            </div>
          ))}
        </dl>

        <section aria-label="Recent operations" className="border border-border p-2">
          <p className="font-mono text-[9px] tracking-[0.1em] text-muted-foreground">
            OPERATIONS · LAST {ops.window_days ?? 30} DAYS ·{" "}
            {ops.scope === "company" ? "WHOLE COMPANY" : "YOURS"}
          </p>
          <p className="mt-1 text-[12px]">
            {ops.running ?? 0} running · {ops.awaiting_approval ?? 0} awaiting approval ·{" "}
            {ops.completed ?? 0} completed · {ops.failed ?? 0} failed · {ops.cancelled ?? 0}{" "}
            cancelled or rejected
          </p>
        </section>

        <section aria-label="Built-in tools">
          <p className="font-mono text-[10px] tracking-[0.12em] text-muted-foreground">
            BUILT-IN TOOLS ({builtIn.length})
          </p>
          <ul>
            {builtIn.map((t) => (
              <ToolRow key={`b-${t.key}`} t={t} />
            ))}
          </ul>
        </section>

        {platform.length > 0 && (
          <section aria-label="Administration">
            <p className="font-mono text-[10px] tracking-[0.12em] text-muted-foreground">
              ADMINISTRATION — YOU CAN ASK ANY AI EMPLOYEE TO CHANGE EAAWP ({platform.length})
            </p>
            <ul>
              {platform.map((t) => (
                <ToolRow key={`p-${t.key}`} t={t} />
              ))}
            </ul>
          </section>
        )}

        <section aria-label="Integration tools">
          <p className="font-mono text-[10px] tracking-[0.12em] text-muted-foreground">
            INTEGRATION TOOLS ({integration.length})
          </p>
          {integration.length ? (
            <ul>
              {integration.map((t) => (
                <ToolRow key={`i-${t.integration?.id}-${t.key}`} t={t} />
              ))}
            </ul>
          ) : (
            <p className="py-2 text-[12px] text-muted-foreground">
              No connected service has been granted to this AI employee yet.
              {data.approvals.can_decide && (
                <>
                  {" "}
                  Grant access in{" "}
                  <Link to="/integrations" className="underline">
                    Integrations
                  </Link>
                  .
                </>
              )}
            </p>
          )}
        </section>

        <div className="flex flex-wrap gap-2 text-[12px]">
          <Link to="/approvals" className="border border-border px-2 py-1 hover:bg-foreground/5">
            Open Approvals
          </Link>
          {data.approvals.can_decide && (
            <Link
              to="/integrations"
              className="border border-border px-2 py-1 hover:bg-foreground/5"
            >
              Manage integrations
            </Link>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
