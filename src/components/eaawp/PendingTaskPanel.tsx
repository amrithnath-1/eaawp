/**
 * PendingTaskPanel
 *
 * Requests the AI employee could not run yet because an integration is not set
 * up. The server keeps the ORIGINAL request; this panel shows what is missing
 * (live, from the server) and offers the next step for the person who can take
 * it: admins configure / connect / approve access, anyone can run the request
 * once it is ready.
 *
 * Nothing here stores or displays a credential; the configuration form is the
 * existing AdminProviderConfigPanel.
 */
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ExternalLink, Loader2 } from "lucide-react";
import { AdminProviderConfigPanel } from "@/components/eaawp/AdminProviderConfigPanel";
import {
  useAuthorizePendingTask, useCancelPendingTask, useGaAuthorize, useGscAuthorize, usePendingTasks,
  useResumePendingTask, useSelectPendingTaskProperty, type AgentExecutionResponse, type PendingTaskFE,
} from "@/hooks/use-api";
import { apiErrorMessage } from "@/lib/api-client";

const PROVIDER_NAMES: Record<string, string> = {
  google_analytics: "Google Analytics",
  google_search_console: "Google Search Console",
};

function TaskRow({ task, onResult }: { task: PendingTaskFE; onResult: (prompt: string, r: AgentExecutionResponse) => void }) {
  const qc = useQueryClient();
  const authorize = useAuthorizePendingTask();
  const resume = useResumePendingTask();
  const cancel = useCancelPendingTask();
  const gaAuth = useGaAuthorize();
  const gscAuth = useGscAuthorize();
  const selectProperty = useSelectPendingTaskProperty();
  const [chosen, setChosen] = useState("");
  const [configured, setConfigured] = useState(false);
  const provider = String(task.action_data["provider_type"] ?? "");
  const providerName = PROVIDER_NAMES[provider] ?? provider;
  const busy = authorize.isPending || resume.isPending || cancel.isPending || gaAuth.isPending || gscAuth.isPending || selectProperty.isPending;
  const btn = "border px-2 py-1 font-mono text-[10px] tracking-[0.12em] disabled:opacity-40";

  function run() {
    resume.mutate(task.id, {
      onSuccess: (r) => onResult(task.prompt, r),
      onError: (e) => toast.error(apiErrorMessage(e)),
    });
  }

  return (
    <li className="border border-border bg-surface p-3 text-left">
      <p className="font-mono text-[10px] tracking-[0.12em] text-muted-foreground">
        SAVED REQUEST · {task.ready ? "READY TO RUN" : "WAITING FOR SETUP"}
      </p>
      <p className="mt-1 text-[12px]">“{task.prompt}”</p>
      <p className="mt-1 text-[12px] text-muted-foreground">{task.message}</p>

      {task.next_action === "CONFIGURATION_REQUIRED" && (
        <div className="mt-2">
          <AdminProviderConfigPanel
            providerType={provider}
            providerDisplayName={providerName}
            onConfigured={() => {
              setConfigured(true);
              void qc.invalidateQueries({ queryKey: ["pending-tasks"] });
            }}
          />
          {configured && <p className="mt-1 text-[11px] text-success">✓ Saved. Next: authorise with Google.</p>}
        </div>
      )}

      <div className="mt-2 flex flex-wrap gap-1.5">
        {task.next_action === "REDIRECT_TO_OAUTH" && (provider === "google_analytics" || provider === "google_search_console") && (
          <button
            disabled={busy}
            className={`${btn} border-border hover:bg-foreground/5`}
            onClick={() => (provider === "google_search_console" ? gscAuth : gaAuth).mutate(undefined, {
              onSuccess: (r) => { window.location.href = r.authorization_url; },
              onError: (e) => toast.error(apiErrorMessage(e)),
            })}
          >
            <ExternalLink className="mr-1 inline size-3" />CONNECT WITH GOOGLE
          </button>
        )}
        {task.next_action === "SELECT_PROPERTY" && (
          <div className="flex flex-wrap items-center gap-1.5">
            <select
              aria-label="Property to report on"
              value={chosen}
              onChange={(e) => setChosen(e.target.value)}
              className="h-7 border border-input bg-background px-2 text-[11px]"
            >
              <option value="">Choose a property…</option>
              {((task.action_data["properties"] as { id: string; label: string; detail?: string }[] | undefined) ?? []).map((p) => (
                <option key={p.id} value={p.id}>{p.label}{p.detail ? ` (${p.detail})` : ""}</option>
              ))}
            </select>
            <button
              disabled={busy || !chosen}
              className={`${btn} border-primary/60 text-primary hover:bg-primary/10`}
              onClick={() => selectProperty.mutate({ id: task.id, propertyId: chosen }, {
                onSuccess: () => toast.success("Property selected."),
                onError: (e) => toast.error(apiErrorMessage(e)),
              })}
            >
              USE THIS PROPERTY
            </button>
          </div>
        )}
        {task.next_action === "GRANT_REQUIRED" && (
          <button
            disabled={busy}
            className={`${btn} border-primary/60 text-primary hover:bg-primary/10`}
            onClick={() => authorize.mutate(task.id, {
              onSuccess: () => toast.success("Read-only access approved for this AI employee."),
              onError: (e) => toast.error(apiErrorMessage(e)),
            })}
          >
            APPROVE READ-ONLY ACCESS
          </button>
        )}
        <button
          disabled={busy}
          className={`${btn} ${task.ready ? "border-success/60 text-success hover:bg-success/10" : "border-border text-muted-foreground hover:text-foreground"}`}
          onClick={run}
        >
          {resume.isPending ? <Loader2 className="inline size-3 animate-spin" /> : task.ready ? "RUN MY REQUEST" : "CHECK AGAIN"}
        </button>
        <button
          disabled={busy}
          className={`${btn} border-border text-muted-foreground hover:text-foreground`}
          onClick={() => cancel.mutate(task.id)}
        >
          CANCEL
        </button>
      </div>
    </li>
  );
}

export function PendingTaskPanel({ onResult }: { onResult: (prompt: string, r: AgentExecutionResponse) => void }) {
  const { data } = usePendingTasks();
  if (!data || data.length === 0) return null;
  return (
    <ul className="mx-auto mb-3 flex max-w-[760px] flex-col gap-2 px-4 pt-3" aria-label="Requests waiting for setup">
      {data.map((t) => <TaskRow key={t.id} task={t} onResult={onResult} />)}
    </ul>
  );
}
