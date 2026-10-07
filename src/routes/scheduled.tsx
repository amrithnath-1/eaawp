import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { toast } from "sonner";
import { AppShell } from "@/components/eaawp/AppShell";
import { PageHeader } from "@/components/eaawp/Panel";
import {
  useCreateWorkflow,
  useDeleteWorkflow,
  usePatchWorkflow,
  useTriggerWorkflow,
  useWorkflows,
  type WorkflowCreate,
  type WorkflowOut,
} from "@/hooks/use-api";
import { cn } from "@/lib/utils";
import { USE_REAL_API } from "@/lib/api-client";

export const Route = createFileRoute("/scheduled")({
  component: ScheduledPage,
});

type ScheduleDraft = { name: string; objective: string; cron: string };
const EMPTY_DRAFT: ScheduleDraft = { name: "", objective: "", cron: "0 9 * * 0" };

function ScheduledPage() {
  const { data: workflows = [], isLoading, refetch } = useWorkflows();
  const create = useCreateWorkflow();
  const patch = usePatchWorkflow();
  const remove = useDeleteWorkflow();
  const trigger = useTriggerWorkflow();
  const [draft, setDraft] = useState<ScheduleDraft | null>(null);
  const [editing, setEditing] = useState<WorkflowOut | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  function closeForm() {
    setDraft(null);
    setEditing(null);
  }

  function openCreate() {
    setEditing(null);
    setDraft({ ...EMPTY_DRAFT });
  }

  function openEdit(workflow: WorkflowOut) {
    setEditing(workflow);
    setDraft({
      name: workflow.name,
      objective: workflow.steps.map((step) => step.description).join("\n") || workflow.description,
      cron: workflow.schedule_cron ?? "0 9 * * 0",
    });
  }

  async function save(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!draft?.name.trim() || !draft.objective.trim()) {
      toast.error("Enter a schedule name and the work the agent should perform.");
      return;
    }
    const body: WorkflowCreate = {
      name: draft.name.trim(),
      description: draft.objective.trim(),
      trigger: "scheduled",
      schedule_cron: draft.cron.trim(),
      is_enabled: editing?.is_enabled ?? true,
      steps: [{
        step_index: 0,
        step_type: "analysis",
        description: draft.objective.trim(),
      }],
    };
    try {
      if (editing) {
        await patch.mutateAsync({ workflowId: editing.id, patch: body });
        toast.success("Schedule updated.");
      } else {
        await create.mutateAsync(body);
        toast.success("Schedule created and enabled.");
      }
      closeForm();
      await refetch();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not save schedule.");
    }
  }

  async function toggle(workflow: WorkflowOut) {
    setBusyId(workflow.id);
    try {
      await patch.mutateAsync({ workflowId: workflow.id, patch: { is_enabled: !workflow.is_enabled } });
      toast.success(workflow.is_enabled ? "Schedule disabled." : "Schedule enabled.");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not update schedule.");
    } finally {
      setBusyId(null);
    }
  }

  async function runNow(workflow: WorkflowOut) {
    setBusyId(workflow.id);
    try {
      const result = await trigger.mutateAsync(workflow.id);
      if (result.status === "failed") toast.error(result.message);
      else if (result.status === "completed") toast.success(result.message);
      else toast.info(result.message);
      await refetch();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not run schedule.");
    } finally {
      setBusyId(null);
    }
  }

  async function deleteWorkflow(workflow: WorkflowOut) {
    if (!window.confirm(`Delete schedule “${workflow.name}”?`)) return;
    setBusyId(workflow.id);
    try {
      await remove.mutateAsync(workflow.id);
      toast.success("Schedule deleted.");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not delete schedule.");
    } finally {
      setBusyId(null);
    }
  }

  const field = "h-8 w-full border border-input bg-background px-2 text-[12px] outline-none focus:border-ring";

  return (
    <AppShell>
      <div className="p-4">
        <PageHeader
          title="Scheduled"
          subtitle="Recurring responsibilities executed by the AI without human prompting. Schedules run in UTC."
          actions={USE_REAL_API ? (
            <button
              onClick={openCreate}
              className="border border-primary px-3 py-1.5 font-mono text-[10px] tracking-[0.14em] text-primary hover:bg-primary/10"
            >
              CREATE SCHEDULE
            </button>
          ) : <span className="text-[10px] text-muted-foreground">Connect the live API to manage schedules.</span>}
        />

        {USE_REAL_API && draft && (
          <form onSubmit={(event) => void save(event)} className="mt-4 space-y-3 border border-border bg-surface p-3">
            <p className="font-mono text-[10px] tracking-[0.14em] text-muted-foreground">
              {editing ? "EDIT SCHEDULE" : "NEW SCHEDULE"}
            </p>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              <label className="label-xs">Name
                <input required maxLength={255} value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })}
                  placeholder="Weekly policy review" className={cn(field, "mt-1")} />
              </label>
              <label className="label-xs">Cron schedule (UTC)
                <input required value={draft.cron} onChange={(event) => setDraft({ ...draft, cron: event.target.value })}
                  placeholder="0 9 * * 0" className={cn(field, "mt-1 font-mono")} />
              </label>
              <label className="label-xs md:col-span-2">Agent task instructions
                <textarea required maxLength={500} rows={3} value={draft.objective}
                  onChange={(event) => setDraft({ ...draft, objective: event.target.value })}
                  placeholder="Describe exactly what the agent should review or prepare. High impact actions still require approval."
                  className={cn(field, "mt-1 h-auto py-2")} />
              </label>
            </div>
            <p className="text-[10px] text-muted-foreground">Five fields: minute hour day-of-month month weekday. Supports *, */n, or one number per field; weekdays use 0 for Monday.</p>
            <div className="flex gap-2">
              <button type="submit" disabled={create.isPending || patch.isPending}
                className="border border-foreground/20 px-3 py-1 font-mono text-[11px] hover:bg-foreground/5 disabled:opacity-50">
                {create.isPending || patch.isPending ? "SAVING…" : editing ? "SAVE CHANGES" : "CREATE"}
              </button>
              <button type="button" onClick={closeForm} className="border border-border px-3 py-1 font-mono text-[11px] text-muted-foreground hover:text-foreground">CANCEL</button>
            </div>
          </form>
        )}

        <div className="mt-4 overflow-x-auto border border-border">
          <div className="grid min-w-[780px] grid-cols-[1.4fr_1fr_1fr_0.8fr_0.9fr_auto] gap-3 border-b border-border bg-surface-2 px-3 py-2">
            {["Task", "Schedule (UTC)", "Last execution", "Status", "Owner", ""].map((heading) => (
              <span key={heading} className="label-xs">{heading}</span>
            ))}
          </div>
          {isLoading ? (
            <div className="px-3 py-6 text-center text-xs text-muted-foreground">Loading schedules…</div>
          ) : workflows.filter((workflow) => workflow.trigger === "scheduled").map((workflow) => (
            <div key={workflow.id} className="grid min-w-[780px] grid-cols-[1.4fr_1fr_1fr_0.8fr_0.9fr_auto] items-center gap-3 border-b border-border px-3 py-2.5 last:border-0 hover:bg-surface">
              <div>
                <div className="text-[13px] font-medium">{workflow.name}</div>
                <div className="label-xs mt-0.5">{workflow.steps[0]?.description || workflow.description || "No task instructions"}</div>
              </div>
              <span className="font-mono text-[11px] text-muted-foreground">{workflow.schedule_cron || "Not configured"}</span>
              <span className="font-mono text-[11px] text-muted-foreground">
                {workflow.last_run_at ? new Date(workflow.last_run_at).toLocaleString() : "Never"}
              </span>
              <span className={cn("font-mono text-[10px] tracking-[0.12em]", workflow.is_enabled ? "text-success" : "text-muted-foreground")}>
                {workflow.is_enabled ? (workflow.status === "awaiting_approval" ? "NEEDS APPROVAL" : workflow.status.toUpperCase()) : "DISABLED"}
              </span>
              <span className="font-mono text-[11px] text-muted-foreground">{workflow.created_by}</span>
              <div className="flex gap-1.5">
                <button disabled={busyId === workflow.id} onClick={() => void toggle(workflow)}
                  className="border border-border px-2 py-1 font-mono text-[10px] text-muted-foreground hover:text-foreground disabled:opacity-50">
                  {workflow.is_enabled ? "DISABLE" : "ENABLE"}
                </button>
                <button disabled={busyId === workflow.id} onClick={() => openEdit(workflow)}
                  className="border border-border px-2 py-1 font-mono text-[10px] text-muted-foreground hover:text-foreground disabled:opacity-50">EDIT</button>
                <button disabled={busyId === workflow.id || !workflow.is_enabled} onClick={() => void runNow(workflow)}
                  className="border border-border px-2 py-1 font-mono text-[10px] text-muted-foreground hover:text-foreground disabled:opacity-50">RUN NOW</button>
                <button disabled={busyId === workflow.id} onClick={() => void deleteWorkflow(workflow)}
                  className="border border-destructive/30 px-2 py-1 font-mono text-[10px] text-destructive hover:bg-destructive/10 disabled:opacity-50">DELETE</button>
              </div>
            </div>
          ))}
          {USE_REAL_API && !isLoading && workflows.every((workflow) => workflow.trigger !== "scheduled") && (
            <div className="px-3 py-6 text-center text-xs text-muted-foreground">No scheduled workflows yet. Create one to add a recurring AI task.</div>
          )}
          {!USE_REAL_API && <div className="px-3 py-6 text-center text-xs text-muted-foreground">Schedules are unavailable while the live API is disconnected.</div>}
        </div>
      </div>
    </AppShell>
  );
}
