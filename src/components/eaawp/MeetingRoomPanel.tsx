/**
 * MeetingRoomPanel - persistent multi-agent sessions.
 *
 * Everything shown here comes from the backend: the coordinator's delegation of subtasks to
 * AI roles, each agent's real result, hand-offs between agents, approvals and the summary.
 * Nothing is scripted in the browser.
 */
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Loader2, Plus, SendHorizonal, Square, Play, ArrowRight, Users } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  useMeetings, useMeeting, useCreateMeeting, usePostMeetingMessage, useCancelMeeting, useResumeMeeting,
  type MeetingTaskFE, type MeetingMessageFE,
} from "@/hooks/use-api";

const STATUS: Record<string, { label: string; cls: string }> = {
  planning: { label: "PLANNING", cls: "text-muted-foreground border-muted-foreground/40" },
  queued: { label: "QUEUED", cls: "text-muted-foreground border-muted-foreground/40" },
  pending: { label: "WAITING", cls: "text-muted-foreground border-muted-foreground/40" },
  running: { label: "WORKING", cls: "text-warning border-warning/40" },
  awaiting_approval: { label: "NEEDS APPROVAL", cls: "text-warning border-warning/40" },
  waiting_setup: { label: "NEEDS SETUP", cls: "text-warning border-warning/40" },
  completed: { label: "DONE", cls: "text-success border-success/40" },
  partial: { label: "PARTLY DONE", cls: "text-warning border-warning/40" },
  failed: { label: "FAILED", cls: "text-destructive border-destructive/40" },
  skipped: { label: "SKIPPED", cls: "text-muted-foreground border-muted-foreground/40" },
  cancelled: { label: "CANCELLED", cls: "text-muted-foreground border-muted-foreground/40" },
};

function Badge({ status }: { status: string }) {
  const c = STATUS[status] ?? STATUS["queued"]!;
  return <span className={cn("shrink-0 border px-1.5 py-0.5 font-mono text-[9px] tracking-[0.06em]", c.cls)}>{c.label}</span>;
}

function TaskCard({ t, byKey }: { t: MeetingTaskFE; byKey: Record<string, MeetingTaskFE> }) {
  return (
    <li className="border border-border bg-surface px-3 py-2">
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-[10px] tracking-[0.08em] text-primary">{t.role_name.toUpperCase()}</span>
        <Badge status={t.status} />
      </div>
      <p className="mt-1 text-[13px] font-medium leading-snug">{t.title}</p>
      {t.depends_on.length > 0 && (
        <p className="mt-0.5 text-[11px] text-muted-foreground">
          Uses results from: {t.depends_on.map((k) => byKey[k]?.role_name ?? k).join(", ")}
        </p>
      )}
    </li>
  );
}

function MessageRow({ m }: { m: MeetingMessageFE }) {
  const who =
    m.kind === "delegation" ? `Coordinator → ${m.recipient_name}`
    : m.sender_kind === "user" ? "You"
    : m.sender_name || m.sender_kind;
  return (
    <li className={cn("border-l-2 pl-2.5 pb-3 last:pb-0",
      m.sender_kind === "user" ? "border-accent" : m.sender_kind === "agent" ? "border-primary" : "border-border")}>
      <div className="font-mono text-[10px] text-muted-foreground">
        {who} · {new Date(m.created_at).toLocaleTimeString()}
      </div>
      <p className={cn("whitespace-pre-wrap text-[13px] leading-snug",
        m.kind === "summary" && "font-medium", m.kind === "status" && "text-muted-foreground")}>{m.content}</p>
    </li>
  );
}

function MeetingView({ id }: { id: string }) {
  const q = useMeeting(id);
  const post = usePostMeetingMessage(id);
  const cancel = useCancelMeeting(id);
  const resume = useResumeMeeting(id);
  const [text, setText] = useState("");
  const endRef = useRef<HTMLLIElement>(null);
  const count = q.data?.messages.length ?? 0;
  const qc = useQueryClient();
  const status = q.data?.status;
  // keep the sidebar badge in step with the open meeting
  useEffect(() => { void qc.invalidateQueries({ queryKey: ["meetings"] }); }, [status, qc]);
  useEffect(() => { endRef.current?.scrollIntoView({ block: "nearest" }); }, [count]);

  if (q.isLoading) return <p className="p-4 font-mono text-[11px] text-muted-foreground">Loading meeting…</p>;
  if (q.isError || !q.data) return <p className="p-4 text-[12px] text-destructive">This meeting could not be loaded.</p>;
  const m = q.data;
  const byKey = Object.fromEntries(m.tasks.map((t) => [t.key, t]));
  const live = ["planning", "queued", "running"].includes(m.status);
  const paused = m.status === "awaiting_approval" || m.status === "waiting_setup";
  const done = ["completed", "partial", "failed", "cancelled"].includes(m.status);

  const act = (fn: () => Promise<unknown>, ok: string) =>
    fn().then(() => toast.success(ok)).catch((e: Error) => toast.error(e.message || "That did not work"));

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-sm font-semibold">{m.title}</h2>
          <p className="text-[11px] text-muted-foreground">{m.completed_count} of {m.task_count} tasks done</p>
        </div>
        <Badge status={m.status} />
        {live && <Loader2 className="size-3.5 animate-spin text-muted-foreground" aria-label="Agents are working" />}
        {paused && (
          <button onClick={() => act(() => resume.mutateAsync(), "Meeting resumed")} disabled={resume.isPending}
            className="flex items-center gap-1 border border-border px-2 py-1 font-mono text-[10px] hover:border-foreground disabled:opacity-40">
            <Play className="size-3" /> RESUME
          </button>
        )}
        {!done && (
          <button onClick={() => act(() => cancel.mutateAsync(), "Meeting cancelled")} disabled={cancel.isPending}
            className="flex items-center gap-1 border border-border px-2 py-1 font-mono text-[10px] text-destructive hover:border-destructive disabled:opacity-40">
            <Square className="size-3" /> CANCEL
          </button>
        )}
      </div>

      {paused && (
        <div className="border-b border-warning/40 bg-warning/5 px-4 py-2 text-[12px]">
          {m.status === "awaiting_approval"
            ? <>An agent proposed an action that needs an administrator's approval. <Link to="/approvals" className="underline">Open approvals</Link>, then press Resume.</>
            : <>An agent needs an integration to be set up before it can continue. <Link to="/integrations" className="underline">Open integrations</Link>, then press Resume.</>}
        </div>
      )}

      <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[320px_minmax(0,1fr)]">
        <div className="min-h-0 overflow-y-auto border-b border-border p-3 lg:border-b-0 lg:border-r">
          <p className="label-xs mb-2">DELEGATED TASKS</p>
          <ul className="space-y-2">{m.tasks.map((t) => <TaskCard key={t.id} t={t} byKey={byKey} />)}</ul>
        </div>
        <div className="flex min-h-0 flex-col">
          <ul className="min-h-[240px] flex-1 overflow-y-auto px-4 py-3">
            {m.messages.map((x) => <MessageRow key={x.id} m={x} />)}
            <li ref={endRef} />
          </ul>
          <form
            className="m-3 flex items-center gap-2 border border-border bg-surface px-3 py-2"
            onSubmit={(e) => {
              e.preventDefault();
              const v = text.trim();
              if (!v) return;
              void act(() => post.mutateAsync(v), "Sent to the coordinator").then(() => setText(""));
            }}
          >
            <input value={text} onChange={(e) => setText(e.target.value)} disabled={m.status === "cancelled" || paused || post.isPending}
              placeholder={m.status === "cancelled" ? "This meeting was cancelled" : paused ? "Resolve the pending item first" : "Ask a follow-up or give the team more work…"}
              className="flex-1 bg-transparent text-[13px] outline-none placeholder:text-muted-foreground" />
            <button type="submit" aria-label="Send message" disabled={!text.trim() || post.isPending || m.status === "cancelled" || paused}
              className="grid size-7 shrink-0 place-items-center border border-border text-muted-foreground disabled:opacity-40">
              {post.isPending ? <Loader2 className="size-3.5 animate-spin" /> : <SendHorizonal className="size-3.5" strokeWidth={1.5} />}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}

export function MeetingRoomPanel() {
  const list = useMeetings();
  const create = useCreateMeeting();
  const [selected, setSelected] = useState<string | null>(null);
  const [objective, setObjective] = useState("");
  const meetings = list.data ?? [];

  useEffect(() => {
    if (!selected && meetings.length > 0) setSelected(meetings[0]!.id);
  }, [meetings, selected]);

  function start() {
    const v = objective.trim();
    if (v.length < 3 || create.isPending) return;
    create.mutate({ objective: v }, {
      onSuccess: (d) => { setSelected(d.id); setObjective(""); },
      onError: (e) => toast.error(e.message || "The meeting could not be started"),
    });
  }

  return (
    <div className="grid min-h-[calc(100vh-3.5rem)] grid-cols-1 lg:grid-cols-[280px_minmax(0,1fr)]">
      <aside className="border-b border-border lg:border-b-0 lg:border-r">
        <div className="space-y-2 border-b border-border p-3">
          <p className="label-xs">NEW MEETING</p>
          <textarea value={objective} onChange={(e) => setObjective(e.target.value)} rows={3} maxLength={2000}
            placeholder="What should your AI team work on together?"
            className="w-full resize-none border border-border bg-surface px-2 py-1.5 text-[13px] outline-none placeholder:text-muted-foreground focus:border-foreground" />
          <button onClick={start} disabled={objective.trim().length < 3 || create.isPending}
            className="flex w-full items-center justify-center gap-1.5 border border-foreground bg-foreground px-2 py-1.5 font-mono text-[10px] tracking-[0.1em] text-background disabled:opacity-40">
            {create.isPending ? <Loader2 className="size-3 animate-spin" /> : <Plus className="size-3" />} START MEETING
          </button>
        </div>
        <ul className="max-h-[40vh] overflow-y-auto lg:max-h-none">
          {meetings.map((m) => (
            <li key={m.id}>
              <button onClick={() => setSelected(m.id)}
                className={cn("flex w-full flex-col gap-1 border-b border-border px-3 py-2 text-left hover:bg-surface",
                  selected === m.id && "bg-surface")}>
                <span className="flex items-center justify-between gap-2">
                  <span className="truncate text-[13px]">{m.title}</span>
                  <Badge status={m.status} />
                </span>
                <span className="font-mono text-[10px] text-muted-foreground">
                  {m.completed_count}/{m.task_count} tasks · {new Date(m.created_at).toLocaleDateString()}
                </span>
              </button>
            </li>
          ))}
          {meetings.length === 0 && (
            <li className="px-3 py-6 text-center font-mono text-[11px] text-muted-foreground">
              {list.isError ? "Meetings could not be loaded." : list.isLoading ? "Loading…" : "No meetings yet. Start one above."}
            </li>
          )}
        </ul>
      </aside>
      <section className="flex min-h-0 flex-col">
        {selected ? <MeetingView id={selected} key={selected} /> : (
          <div className="m-auto max-w-sm p-8 text-center">
            <Users className="mx-auto mb-3 size-6 text-muted-foreground" strokeWidth={1.5} />
            <p className="text-[13px] text-muted-foreground">
              Describe a goal. A coordinator splits it into tasks, assigns them to your AI employees, passes results between them
              and reports what actually happened. <ArrowRight className="inline size-3" />
            </p>
          </div>
        )}
      </section>
    </div>
  );
}
