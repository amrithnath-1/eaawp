/**
 * ProjectManagerPanel - the Project Manager AI employee (ported from Vyuham: team coordination & task allocation).
 *
 * Administrators: projects from documents to approved plans, allocation with approvals, the team roster with
 * evidence-backed scores, budgets, rooms and the audit ledger. A project's named managers: that project.
 * Everyone else: their own tasks and requests. Every number on this page is computed by the server's deterministic
 * engine; AI-made drafts are labelled and only count after a person approves them.
 */
import { useMemo, useRef, useState, type ReactNode } from "react";
import { toast } from "sonner";
import {
  AlertTriangle, CheckCircle2, Download, FileText, Loader2, Play, Plus, RefreshCw, Send, ShieldCheck, Upload, UserPlus, X, XCircle,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { KeyValue, Meter, Panel } from "@/components/eaawp/Panel";
import {
  pmDownload, pmError, usePm, usePmAction, usePmUpload,
  type PmApproval, type PmAuditEntry, type PmCandidate, type PmChangeRequest, type PmDocument, type PmEmployeeScore, type PmMe,
  type PmProgress, type PmProjectDetail, type PmSummary, type PmTask,
} from "@/hooks/use-pm";

// ── small building blocks ─────────────────────────────────────────────────────
const btn = "inline-flex items-center gap-1.5 border border-border px-2.5 py-1 text-[12px] hover:bg-accent disabled:opacity-50";
const btnPrimary = "inline-flex items-center gap-1.5 border border-primary bg-primary px-2.5 py-1 text-[12px] text-primary-foreground disabled:opacity-50";
const input = "w-full border border-border bg-background px-2 py-1.5 text-[13px]";

function Stat({ label, value, tone, hint }: { label: string; value: ReactNode; tone?: "warn" | undefined; hint?: string }) {
  return (
    <div className="border border-border bg-surface px-3 py-2" title={hint}>
      <div className="label-xs">{label}</div>
      <div className={cn("mt-1 font-mono text-xl", tone === "warn" ? "text-warning" : "text-foreground")}>{value}</div>
    </div>
  );
}

function Tag({ children, tone }: { children: ReactNode; tone?: "ok" | "warn" | "bad" | "muted" }) {
  const cls = tone === "ok" ? "text-success border-success/40" : tone === "warn" ? "text-warning border-warning/40"
    : tone === "bad" ? "text-destructive border-destructive/40" : "text-muted-foreground border-muted-foreground/40";
  return <span className={cn("shrink-0 border px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-[0.06em]", cls)}>{children}</span>;
}

function Empty({ children }: { children: ReactNode }) {
  return <p className="border border-dashed border-border p-3 text-[12px] text-muted-foreground">{children}</p>;
}

function Loading({ q }: { q: { isLoading: boolean; error: unknown } }) {
  if (q.isLoading) return <p className="flex items-center gap-2 p-3 text-[12px] text-muted-foreground"><Loader2 className="size-3 animate-spin" /> Loading…</p>;
  if (q.error) return <p className="p-3 text-[12px] text-destructive">{pmError(q.error)}</p>;
  return null;
}

const STATUS_LABEL: Record<string, string> = {
  READY_FOR_ALLOCATION: "Waiting for allocation", PENDING_HITL_APPROVAL: "Waiting for approval", ASSIGNED: "Assigned",
  IN_PROGRESS: "In progress", DELIVERABLE_IN_REVIEW: "In review", COMPLETED_AND_AUDITED: "Done", BLOCKED_BY_DEPENDENCY: "Waiting on another task",
  REWORK_REQUESTED: "Rework requested", UNASSIGNABLE: "No eligible person",
};
const statusTone = (s: string) => (s === "COMPLETED_AND_AUDITED" ? "ok" : s === "PENDING_HITL_APPROVAL" || s === "REWORK_REQUESTED" || s === "UNASSIGNABLE" ? "warn" : "muted") as "ok" | "warn" | "muted";
const healthTone = (h: string) => (h === "On track" || h === "Complete" ? "ok" : h === "At risk" ? "warn" : h === "Off track" ? "bad" : "muted") as "ok" | "warn" | "bad" | "muted";
const money = (minor: number | null | undefined, cur?: string | null) => (minor == null ? "—" : `${cur ?? ""} ${(minor / 100).toLocaleString(undefined, { maximumFractionDigits: 2 })}`.trim());

function ProgressBar({ p }: { p: PmProgress }) {
  return (
    <div className="space-y-1">
      <div className="flex h-1.5 w-full overflow-hidden bg-muted" aria-label={`Verified ${p.completion_pct}%`}>
        <div className="bg-foreground" style={{ width: `${p.bands_pct.verified}%` }} />
        <div className="bg-border-strong" style={{ width: `${p.bands_pct.in_progress}%` }} />
        <div className="bg-destructive/70" style={{ width: `${p.bands_pct.blocked}%` }} />
      </div>
      <div className="flex flex-wrap gap-x-3 font-mono text-[10px] text-muted-foreground">
        <span>{p.completion_pct}% verified</span><span>{p.bands_pct.in_progress}% in progress</span>
        {p.bands_pct.blocked > 0 && <span className="text-destructive">{p.bands_pct.blocked}% blocked</span>}
        <span>expected by now {p.expected_pct_by_schedule}%</span>
      </div>
    </div>
  );
}

function AiNotice({ ai }: { ai?: PmMe["ai"] | undefined }) {
  if (!ai || ai.configured) return null;
  return (
    <div className="flex items-start gap-2 border border-warning/50 bg-warning/5 px-3 py-2 text-[12px]">
      <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-warning" />
      The AI model is not configured, so document reading, plans and minutes use the labelled rule-based method. Allocation, scores and progress are not affected (they never use AI).
    </div>
  );
}

// ── overview (administrators) ─────────────────────────────────────────────────
function AdminOverview({ go }: { go: (pid: string) => void }) {
  const s = usePm<PmSummary>("/dashboard/summary", { refetch: 30_000 });
  const projects = usePm<PmProgress[]>("/projects");
  const run = usePmAction<void, { allocations: unknown[] }>("POST", () => "/tasks/allocate-all");
  const d = s.data;
  return (
    <div className="space-y-4">
      <Loading q={s} />
      {d && (
        <div className="grid grid-cols-2 gap-2 md:grid-cols-6">
          <Stat label="Projects" value={projects.data?.length ?? "…"} />
          <Stat label="Tasks" value={d.total_tasks} />
          <Stat label="Waiting for approval" value={d.pending_approvals.length} tone={d.pending_approvals.length ? "warn" : undefined} />
          <Stat label="Team" value={d.total_employees} />
          <Stat label="Overloaded" value={d.overloaded_count} tone={d.overloaded_count ? "warn" : undefined} hint="Workload above 85%" />
          <Stat label="Fairness (Gini)" value={d.workload_gini_index.toFixed(3)} hint="0 means workload is spread perfectly evenly" />
        </div>
      )}
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
        <Panel title="Projects" dense className="border border-border" actions={
          <button type="button" className={btn} disabled={run.isPending} onClick={() => run.mutate(undefined, {
            onSuccess: (r) => toast.success(`Allocation ran for ${r.allocations.length} task(s). Critical or heavy assignments wait for approval.`),
            onError: (e) => toast.error(pmError(e)) })}>
            {run.isPending ? <Loader2 className="size-3 animate-spin" /> : <Play className="size-3" />} Allocate open tasks
          </button>}>
          <Loading q={projects} />
          {projects.data?.length === 0 && <div className="p-3"><Empty>No projects yet. Use “New project” to start one, then upload its brief.</Empty></div>}
          <ul>
            {projects.data?.map((p) => (
              <li key={p.project_id}>
                <button type="button" onClick={() => go(p.project_id)} className="block w-full border-b border-border px-3 py-2.5 text-left last:border-0 hover:bg-accent">
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate text-[13px] font-medium">{p.name}</span>
                    <span className="flex gap-1"><Tag>{p.stage_label}</Tag><Tag tone={healthTone(p.health)}>{p.health}</Tag></span>
                  </div>
                  <div className="mt-1.5"><ProgressBar p={p} /></div>
                </button>
              </li>
            ))}
          </ul>
        </Panel>
        <div className="space-y-4">
          <Panel title="How allocation works" dense className="border border-border">
            <div className="space-y-2 px-3 py-3 text-[12px] text-muted-foreground">
              <p>People on leave, without the critical skill, or above 95% capacity are never chosen.</p>
              <p>Everyone else is ranked: 30% skill, 20% availability, 20% workload balance, 15% priority fit, 10% past performance, 5% growth.</p>
              <p>Critical tasks and assignments above 85% load wait for a manager’s approval.</p>
              <p>Progress counts only work a manager accepted.</p>
            </div>
          </Panel>
          {d && (
            <Panel title="Records" dense className="border border-border">
              <div className="px-3 py-2">
                <KeyValue k="Audit ledger" v={d.ledger_status.valid ? "intact" : "CHECK FAILED"} />
                <KeyValue k="Skill reviews waiting" v={d.pending_skill_requests} />
                <KeyValue k="Change requests open" v={d.change_requests.filter((c) => c.status === "open" || c.status === "pending").length} />
                <KeyValue k="Team free hours / week" v={d.team_free_hrs} />
              </div>
            </Panel>
          )}
        </div>
      </div>
    </div>
  );
}

// ── new project ───────────────────────────────────────────────────────────────
function NewProject({ onCreated }: { onCreated: (id: string) => void }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [objective, setObjective] = useState("");
  const [priority, setPriority] = useState("High");
  const [days, setDays] = useState(30);
  const create = usePmAction<void, { id: string }>("POST", () => "/projects/draft", () => ({ name, objective, priority, deadline_days: days }));
  if (!open) return <button type="button" className={btn} onClick={() => setOpen(true)}><Plus className="size-3.5" /> New project</button>;
  return (
    <form className="w-full space-y-2 border border-border bg-surface p-3 md:w-[420px]" onSubmit={(e) => {
      e.preventDefault();
      create.mutate(undefined, { onSuccess: (p) => { toast.success("Project created. Upload its brief next."); setOpen(false); setName(""); setObjective(""); onCreated(p.id); }, onError: (er) => toast.error(pmError(er)) });
    }}>
      <input className={input} value={name} onChange={(e) => setName(e.target.value)} maxLength={120} placeholder="Project name" aria-label="Project name" />
      <textarea className={input} value={objective} onChange={(e) => setObjective(e.target.value)} maxLength={4000} rows={2} placeholder="What should it achieve? (optional)" aria-label="Objective" />
      <div className="flex gap-2">
        <select className={input} value={priority} onChange={(e) => setPriority(e.target.value)} aria-label="Priority">
          {["Critical", "High", "Medium", "Low"].map((p) => <option key={p}>{p}</option>)}
        </select>
        <label className="flex items-center gap-1 whitespace-nowrap text-[12px]">Deadline in
          <input type="number" min={3} max={730} value={days} onChange={(e) => setDays(Number(e.target.value))} className="w-20 border border-border bg-background px-2 py-1 text-[13px]" aria-label="Deadline in days" /> days</label>
      </div>
      <div className="flex gap-2">
        <button type="submit" className={btnPrimary} disabled={create.isPending || name.trim().length < 3}>{create.isPending && <Loader2 className="size-3 animate-spin" />} Create</button>
        <button type="button" className={btn} onClick={() => setOpen(false)}>Cancel</button>
      </div>
    </form>
  );
}

// ── project detail ───────────────────────────────────────────────────────────
type ProjectTab = "overview" | "documents" | "plan" | "tasks" | "budget" | "room";

function ProjectDetail({ pid, isAdmin, onClose }: { pid: string; isAdmin: boolean; onClose: () => void }) {
  const q = usePm<PmProjectDetail>(`/projects/${pid}`, { refetch: 30_000 });
  const [tab, setTab] = useState<ProjectTab>("overview");
  const d = q.data;
  const tabs: Array<[ProjectTab, string]> = [["overview", "Overview"], ["documents", "Documents"], ["plan", "Specification & plan"], ["tasks", "Tasks"], ["budget", "Budget"], ["room", "Team room"]];
  const visible = tabs.filter(([k]) => (k === "budget" ? d?.can_manage : k === "plan" || k === "documents" ? (isAdmin || d?.can_manage) : true));
  return (
    <div className="space-y-3 border border-border bg-surface p-4" data-testid="pm-project">
      <Loading q={q} />
      {d && (
        <>
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <h2 className="text-[15px] font-medium">{d.project.name}</h2>
              <p className="text-[11px] text-muted-foreground">{d.project.id} · {d.project.priority} priority · deadline {d.progress.deadline} ({d.progress.days_remaining} days left)</p>
            </div>
            <div className="flex items-center gap-2"><Tag>{d.stage_label}</Tag><Tag tone={healthTone(d.progress.health)}>{d.progress.health}</Tag>
              <button type="button" aria-label="Close" onClick={onClose}><X className="size-4" /></button></div>
          </div>
          <nav className="flex flex-wrap gap-1 border-b border-border" aria-label="Project sections">
            {visible.map(([k, label]) => (
              <button key={k} type="button" onClick={() => setTab(k)} className={cn("px-2.5 py-1.5 text-[12px]", tab === k ? "border-b-2 border-primary font-medium" : "text-muted-foreground hover:text-foreground")}>{label}</button>
            ))}
          </nav>
          {tab === "overview" && <ProjectOverview d={d} />}
          {tab === "documents" && <ProjectDocuments pid={pid} isAdmin={isAdmin} />}
          {tab === "plan" && <ProjectPlan pid={pid} isAdmin={isAdmin} />}
          {tab === "tasks" && <ProjectTasks d={d} isAdmin={isAdmin} />}
          {tab === "budget" && <ProjectBudget pid={pid} isAdmin={isAdmin} />}
          {tab === "room" && <ProjectRoom pid={pid} canManage={d.can_manage} />}
        </>
      )}
    </div>
  );
}

function ProjectOverview({ d }: { d: PmProjectDetail }) {
  const ev = usePm<{ findings: string[]; corrective_actions: string[]; limitations: string[] }>(`/projects/${d.project.id}/evaluation`);
  return (
    <div className="space-y-3">
      {d.project.business_objective && <p className="text-[13px]">{d.project.business_objective}</p>}
      <ProgressBar p={d.progress} />
      <p className="text-[11px] text-muted-foreground">{d.progress.method}</p>
      {d.progress.milestones.length > 0 && (
        <div className="grid gap-2 md:grid-cols-3">
          {d.progress.milestones.map((m) => (
            <div key={m.name} className="border border-border p-2 text-[12px]"><div className="flex justify-between"><span>{m.name}</span><span className="font-mono text-[11px]">{m.done}/{m.total}</span></div>
              <div className="mt-1"><Meter value={m.total ? (100 * m.done) / m.total : 0} /></div></div>
          ))}
        </div>
      )}
      {d.critical_path.path.length > 0 && <p className="text-[12px]"><span className="label-xs">Critical path</span> {d.critical_path.path.join(" → ")} <span className="text-muted-foreground">({d.critical_path.total_hours} h)</span></p>}
      {ev.data && (ev.data.findings.length > 0 || ev.data.corrective_actions.length > 0) && (
        <div className="grid gap-3 md:grid-cols-2">
          <div><div className="label-xs mb-1">Findings</div><ul className="list-disc space-y-0.5 pl-4 text-[12px]">{ev.data.findings.map((f, i) => <li key={i}>{f}</li>)}</ul></div>
          <div><div className="label-xs mb-1">Suggested actions</div><ul className="list-disc space-y-0.5 pl-4 text-[12px]">{ev.data.corrective_actions.map((f, i) => <li key={i}>{f}</li>)}</ul></div>
        </div>
      )}
      <button type="button" className={btn} onClick={() => void pmDownload(`/projects/${d.project.id}/export.csv`, `${d.project.id}-tasks.csv`).catch((e: Error) => toast.error(e.message))}><Download className="size-3" /> Export tasks (CSV)</button>
    </div>
  );
}

function ProjectDocuments({ pid, isAdmin }: { pid: string; isAdmin: boolean }) {
  const docs = usePm<PmDocument[]>(`/projects/${pid}/documents`);
  const up = usePmUpload<{ results: Array<{ filename: string; status: string; error?: string | null; suspicious_count?: number }> }>(`/projects/${pid}/documents`);
  const del = usePmAction<string>("DELETE", (id) => `/projects/${pid}/documents/${id}`);
  const ref = useRef<HTMLInputElement>(null);
  const [q, setQ] = useState("");
  const [search, setSearch] = useState<string | null>(null);
  const hits = usePm<Array<{ id: string; filename: string; location: string; text: string }>>(search ? `/projects/${pid}/documents-search?q=${encodeURIComponent(search)}` : null);
  return (
    <div className="space-y-3">
      {isAdmin && (
        <div className="flex flex-wrap items-center gap-2">
          <input ref={ref} type="file" multiple accept=".pdf,.docx,.pptx,.xlsx,.csv,.txt,.md" className="hidden" onChange={(e) => {
            const files = Array.from(e.target.files ?? []); if (!files.length) return;
            up.mutate({ files }, {
              onSuccess: (r) => r.results.forEach((x) => x.status === "indexed" ? toast.success(`${x.filename}: read${x.suspicious_count ? ` (${x.suspicious_count} passage(s) that look like instructions were flagged and ignored)` : ""}`)
                : toast.error(`${x.filename}: ${x.error ?? x.status}`)),
              onError: (er) => toast.error(pmError(er)) });
            if (ref.current) ref.current.value = "";
          }} />
          <button type="button" className={btnPrimary} disabled={up.isPending} onClick={() => ref.current?.click()}>{up.isPending ? <Loader2 className="size-3 animate-spin" /> : <Upload className="size-3" />} Upload brief or requirements</button>
          <span className="text-[11px] text-muted-foreground">PDF, Word, PowerPoint, Excel, CSV or text · up to 20 MB each</span>
        </div>
      )}
      <Loading q={docs} />
      {docs.data?.length === 0 && <Empty>No documents yet. Upload the project brief, requirements or proposal so a plan can be drafted from them.</Empty>}
      <ul className="space-y-1">
        {docs.data?.map((d) => (
          <li key={d.id} className={cn("flex items-center justify-between gap-2 border border-border px-2 py-1.5 text-[12px]", !d.is_current && "opacity-60")}>
            <span className="flex min-w-0 items-center gap-2"><FileText className="size-3.5 shrink-0" /><span className="truncate">{d.filename}</span><span className="font-mono text-[10px] text-muted-foreground">v{d.version} · {d.chunk_count} passages</span></span>
            <span className="flex items-center gap-1">
              {d.suspicious_count > 0 && <Tag tone="warn">{d.suspicious_count} flagged</Tag>}
              <Tag tone={d.status === "indexed" ? "ok" : d.status === "failed" ? "bad" : "muted"}>{d.status}</Tag>
              {isAdmin && <button type="button" aria-label={`Delete ${d.filename}`} className="text-destructive" onClick={() => { if (window.confirm(`Delete ${d.filename}?`)) del.mutate(d.id, { onError: (e) => toast.error(pmError(e)) }); }}><XCircle className="size-3.5" /></button>}
            </span>
          </li>
        ))}
      </ul>
      {(docs.data?.length ?? 0) > 0 && (
        <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); setSearch(q.trim() || null); }}>
          <input className={input} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search these documents" aria-label="Search project documents" />
          <button type="submit" className={btn}>Search</button>
        </form>
      )}
      {hits.data && (hits.data.length === 0 ? <Empty>Nothing in the documents matches that.</Empty> : (
        <ul className="space-y-1.5">{hits.data.map((h) => <li key={h.id} className="border-l-2 border-border pl-2 text-[12px]"><span className="font-mono text-[10px] text-muted-foreground">{h.filename} · {h.location}</span><p className="line-clamp-4">{h.text}</p></li>)}</ul>
      ))}
    </div>
  );
}

interface SpecItem { text: string; document?: string; location?: string }
interface Spec { status: string; source: string | null; analysis: (Record<string, SpecItem[] | string | boolean | unknown> & { summary?: string }) | null; clarifications: Array<{ id: string; question: string; why?: string; options?: string[]; status: string; answer: string | null }> }
interface PlanRow { id: string; version: number; source: string; status: string; plan: { summary: string; risks: string[]; resource_gaps: string[]; milestones: Array<{ name: string; due_day: number }>; tasks: Array<{ key: string; title: string; phase: string; priority: string; estimated_hours: number; required_skills: Record<string, string>; depends_on_keys: string[]; suggested_assignee_name?: string | null; suggestion_reason?: string | null }> } }

const SECTION_LABEL: Record<string, string> = {
  objectives: "Objectives", business_requirements: "Business requirements", functional_requirements: "Functional requirements",
  non_functional_requirements: "Quality requirements", deliverables: "Deliverables", technical_requirements: "Technical requirements",
  constraints: "Constraints", deadlines: "Deadlines", budget: "Budget", required_skills: "Skills needed", risks: "Risks",
};

function ProjectPlan({ pid, isAdmin }: { pid: string; isAdmin: boolean }) {
  const spec = usePm<Spec>(`/projects/${pid}/spec`);
  const plan = usePm<PlanRow | { plan: null }>(`/projects/${pid}/plan`);
  const analyze = usePmAction("POST", () => `/projects/${pid}/analyze`);
  const approveSpec = usePmAction("POST", () => `/projects/${pid}/spec/approve`);
  const answer = usePmAction<{ id: string; answer: string }>("POST", (v) => `/projects/${pid}/clarifications/${v.id}`, (v) => ({ answer: v.answer }));
  const gen = usePmAction<boolean>("POST", (force) => `/projects/${pid}/plan/generate${force ? "?force=true" : ""}`);
  const approvePlan = usePmAction<string, { tasks: unknown[]; status?: string }>("POST", (id) => `/projects/${pid}/plan/${id}/approve`);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const s = spec.data;
  const p = plan.data && "id" in plan.data ? plan.data : null;
  const fail = (e: Error) => toast.error(pmError(e));
  return (
    <div className="space-y-4">
      <section className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-[13px] font-medium">1 · Specification from the documents</h3>
          {isAdmin && <button type="button" className={btn} disabled={analyze.isPending} onClick={() => analyze.mutate(undefined, { onSuccess: () => toast.success("Documents read. Check the specification."), onError: fail })}>
            {analyze.isPending ? <Loader2 className="size-3 animate-spin" /> : <RefreshCw className="size-3" />} {s?.status === "not_analyzed" ? "Read the documents" : "Read again"}</button>}
        </div>
        <Loading q={spec} />
        {s?.status === "not_analyzed" && <Empty>Upload documents, then read them to build the specification.</Empty>}
        {s?.analysis && (
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2"><Tag tone={s.status === "approved" ? "ok" : "warn"}>{s.status}</Tag><span className="font-mono text-[10px] text-muted-foreground">made by {s.source?.startsWith("ai:") ? `AI (${s.source.slice(3)})` : "the rule-based reader"}</span></div>
            {typeof s.analysis.summary === "string" && <p className="text-[13px]">{s.analysis.summary}</p>}
            <div className="grid gap-2 md:grid-cols-2">
              {Object.entries(SECTION_LABEL).map(([k, label]) => {
                const items = (s.analysis?.[k] as SpecItem[] | undefined) ?? [];
                if (!items.length) return null;
                return <div key={k} className="border border-border p-2"><div className="label-xs mb-1">{label}</div>
                  <ul className="space-y-0.5 text-[12px]">{items.slice(0, 8).map((i, n) => <li key={n}>{i.text}{i.document && <span className="text-muted-foreground"> — {i.document}{i.location ? `, ${i.location}` : ""}</span>}</li>)}</ul></div>;
              })}
            </div>
          </div>
        )}
        {(s?.clarifications.filter((c) => c.status === "open").length ?? 0) > 0 && (
          <div className="space-y-2 border border-warning/50 bg-warning/5 p-2">
            <div className="label-xs">Questions to answer before approval</div>
            {s!.clarifications.filter((c) => c.status === "open").map((c) => (
              <div key={c.id} className="space-y-1 text-[12px]">
                <p className="font-medium">{c.question}</p>{c.why && <p className="text-muted-foreground">{c.why}</p>}
                {isAdmin && <div className="flex gap-2">
                  <input className={input} list={`opt-${c.id}`} value={answers[c.id] ?? ""} onChange={(e) => setAnswers({ ...answers, [c.id]: e.target.value })} placeholder="Your answer" aria-label={c.question} />
                  <datalist id={`opt-${c.id}`}>{c.options?.map((o) => <option key={o} value={o} />)}</datalist>
                  <button type="button" className={btn} disabled={!(answers[c.id] ?? "").trim()} onClick={() => answer.mutate({ id: c.id, answer: answers[c.id] ?? "" }, { onError: fail })}>Answer</button>
                </div>}
              </div>
            ))}
          </div>
        )}
        {isAdmin && s?.analysis && s.status !== "approved" && (
          <button type="button" className={btnPrimary} disabled={approveSpec.isPending} onClick={() => approveSpec.mutate(undefined, { onSuccess: () => toast.success("Specification approved"), onError: fail })}><CheckCircle2 className="size-3" /> Approve specification</button>
        )}
      </section>

      <section className="space-y-2 border-t border-border pt-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-[13px] font-medium">2 · Plan</h3>
          {isAdmin && s?.status === "approved" && <button type="button" className={btn} disabled={gen.isPending} onClick={() => gen.mutate(!!p && p.status === "draft", { onSuccess: () => toast.success("Plan drafted. Review it, then approve."), onError: fail })}>
            {gen.isPending ? <Loader2 className="size-3 animate-spin" /> : <RefreshCw className="size-3" />} {p ? "Draft a new plan" : "Draft the plan"}</button>}
        </div>
        {!p && <Empty>The plan is drafted after the specification is approved.</Empty>}
        {p && (
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2"><Tag tone={p.status === "approved" ? "ok" : "warn"}>{p.status}</Tag><span className="font-mono text-[10px] text-muted-foreground">version {p.version} · made by {p.source.startsWith("ai:") ? `AI (${p.source.slice(3)})` : "the rule-based planner"}</span></div>
            {p.plan.summary && <p className="text-[13px]">{p.plan.summary}</p>}
            {p.plan.risks.length > 0 && <ul className="space-y-0.5 text-[12px] text-warning">{p.plan.risks.map((r, i) => <li key={i}>⚠ {r}</li>)}</ul>}
            <div className="overflow-x-auto">
              <table className="w-full text-[12px]">
                <thead><tr className="border-b border-border text-left"><th className="label-xs py-1">Task</th><th className="label-xs">Phase</th><th className="label-xs">Priority</th><th className="label-xs">Hours</th><th className="label-xs">Suggested person</th></tr></thead>
                <tbody>{p.plan.tasks.map((t) => (
                  <tr key={t.key} className="border-b border-border align-top"><td className="py-1 pr-2">{t.title}<div className="text-[10px] text-muted-foreground">{Object.entries(t.required_skills).map(([k, v]) => `${k} (${v})`).join(", ")}{t.depends_on_keys.length ? ` · after ${t.depends_on_keys.join(", ")}` : ""}</div></td>
                    <td className="pr-2">{t.phase}</td><td className="pr-2">{t.priority}</td><td className="pr-2 font-mono">{t.estimated_hours}</td>
                    <td title={t.suggestion_reason ?? ""}>{t.suggested_assignee_name ?? <span className="text-warning">nobody eligible</span>}</td></tr>
                ))}</tbody>
              </table>
            </div>
            {p.plan.resource_gaps.length > 0 && <p className="text-[12px] text-muted-foreground">Gaps: {p.plan.resource_gaps.join("; ")}</p>}
            {isAdmin && p.status === "draft" && (
              <button type="button" className={btnPrimary} disabled={approvePlan.isPending} onClick={() => approvePlan.mutate(p.id, { onSuccess: (r) => toast.success(`Plan approved: ${r.tasks.length} task(s) created. Allocate them from the Tasks tab or the overview.`), onError: fail })}>
                <CheckCircle2 className="size-3" /> Approve plan and create tasks</button>
            )}
          </div>
        )}
      </section>
    </div>
  );
}

function Candidates({ taskId, onClose }: { taskId: string; onClose: () => void }) {
  const q = usePm<{ candidates: PmCandidate[] }>(`/tasks/${taskId}/candidates`);
  const assign = usePmAction<string>("POST", () => `/tasks/${taskId}/assign`, (emp) => ({ employee_id: emp, reason: "Chosen by a manager from the ranked list" }));
  return (
    <div className="space-y-1 border border-border bg-background p-2">
      <div className="flex justify-between"><span className="label-xs">Who fits {taskId}</span><button type="button" aria-label="Close" onClick={onClose}><X className="size-3.5" /></button></div>
      <Loading q={q} />
      {q.data?.candidates.slice(0, 8).map((c) => (
        <div key={c.employee_id} className="flex items-center justify-between gap-2 border-b border-border py-1 text-[12px] last:border-0">
          <span className="min-w-0"><span className="font-medium">{c.employee_name}</span> <span className="text-muted-foreground">· {c.designation}</span>
            {!c.eligible && <span className="block text-[11px] text-destructive">{c.hard_violations?.join("; ")}</span>}
            {c.eligible && (c.warnings?.length ?? 0) > 0 && <span className="block text-[11px] text-warning">{c.warnings?.join("; ")}</span>}</span>
          <span className="flex shrink-0 items-center gap-2 font-mono text-[11px]">{c.suitability_score} · load {c.utilization_after_pct}%
            {c.eligible && <button type="button" className={btn} disabled={assign.isPending} onClick={() => assign.mutate(c.employee_id, { onSuccess: () => { toast.success(`Assigned to ${c.employee_name}`); onClose(); }, onError: (e) => toast.error(pmError(e)) })}>Assign</button>}</span>
        </div>
      ))}
    </div>
  );
}

function ProjectTasks({ d, isAdmin }: { d: PmProjectDetail; isAdmin: boolean }) {
  const [pick, setPick] = useState<string | null>(null);
  const run = usePmAction<void, { allocations: unknown[] }>("POST", () => `/tasks/allocate-all?project_id=${d.project.id}`);
  const accept = usePmAction<string>("POST", (id) => `/tasks/${id}/accept`);
  const rework = usePmAction<{ id: string; reason: string }>("POST", (v) => `/tasks/${v.id}/rework`, (v) => ({ reason: v.reason }));
  const fail = (e: Error) => toast.error(pmError(e));
  return (
    <div className="space-y-2">
      {isAdmin && d.tasks.some((t) => !t.assigned_to && t.status !== "COMPLETED_AND_AUDITED") && (
        <button type="button" className={btnPrimary} disabled={run.isPending} onClick={() => run.mutate(undefined, { onSuccess: () => toast.success("Allocated. Critical or heavy assignments wait in Approvals."), onError: fail })}>
          {run.isPending ? <Loader2 className="size-3 animate-spin" /> : <Play className="size-3" />} Allocate this project’s open tasks</button>
      )}
      {d.tasks.length === 0 && <Empty>No tasks yet. They are created when a plan is approved.</Empty>}
      <ul className="space-y-1">
        {d.tasks.map((t) => (
          <li key={t.id} className="border border-border px-2 py-1.5 text-[12px]">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="min-w-0"><span className="font-mono text-[10px] text-muted-foreground">{t.id}</span> <span className="font-medium">{t.title}</span></span>
              <span className="flex items-center gap-1"><Tag>{t.priority}</Tag><Tag tone={statusTone(t.status)}>{STATUS_LABEL[t.status] ?? t.status}</Tag></span>
            </div>
            <div className="mt-0.5 flex flex-wrap items-center justify-between gap-2 text-[11px] text-muted-foreground">
              <span>{t.owner_name ?? "Not assigned"} · {t.estimated_hours} h · reported {t.progress_pct}%{t.blocked ? " · blocked" : ""}</span>
              {d.can_manage && (
                <span className="flex gap-1">
                  {isAdmin && t.status !== "COMPLETED_AND_AUDITED" && <button type="button" className={btn} onClick={() => setPick(pick === t.id ? null : t.id)}><UserPlus className="size-3" /> Who fits?</button>}
                  {t.status === "DELIVERABLE_IN_REVIEW" && <>
                    <button type="button" className={btn} onClick={() => accept.mutate(t.id, { onSuccess: () => toast.success("Accepted: it now counts as done"), onError: fail })}><CheckCircle2 className="size-3" /> Accept</button>
                    <button type="button" className={btn} onClick={() => { const reason = window.prompt("What needs to change?"); if (reason) rework.mutate({ id: t.id, reason }, { onError: fail }); }}>Ask for rework</button>
                  </>}
                </span>
              )}
            </div>
            {pick === t.id && <div className="mt-1"><Candidates taskId={t.id} onClose={() => setPick(null)} /></div>}
          </li>
        ))}
      </ul>
    </div>
  );
}

interface BudgetReport { has_budget: boolean; currency: string | null; estimated_labor_minor: number; estimated_non_labor_minor: number; committed_minor: number; actual_minor: number; tasks_without_rate: string[]; tasks_without_owner: string[]; assumptions: string[]; budget?: { total_minor: number; reserve_minor: number } | null; remaining_minor?: number | null; status?: string }

function ProjectBudget({ pid, isAdmin }: { pid: string; isAdmin: boolean }) {
  const r = usePm<BudgetReport>(`/projects/${pid}/budget`);
  const [cur, setCur] = useState("INR");
  const [total, setTotal] = useState("");
  const set = usePmAction("PUT", () => `/projects/${pid}/budget`, () => ({ currency: cur, total_minor: Math.round(Number(total) * 100) }));
  const opt = usePmAction<void, { proposal_id?: string; summary?: string; message?: string }>("POST", () => `/projects/${pid}/optimize`);
  const b = r.data;
  return (
    <div className="space-y-3">
      <Loading q={r} />
      {b && (
        <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
          <Stat label="Estimated labour" value={money(b.estimated_labor_minor, b.currency)} />
          <Stat label="Other costs" value={money(b.estimated_non_labor_minor, b.currency)} />
          <Stat label="Committed" value={money(b.committed_minor, b.currency)} />
          <Stat label="Spent" value={money(b.actual_minor, b.currency)} />
        </div>
      )}
      {b && !b.has_budget && <Empty>No budget set for this project yet.</Empty>}
      {b && (b.tasks_without_rate.length > 0 || b.tasks_without_owner.length > 0) && <p className="text-[12px] text-muted-foreground">The estimate is a lower bound: {b.tasks_without_owner.length} task(s) have no owner and {b.tasks_without_rate.length} have no approved rate.</p>}
      {isAdmin && (
        <form className="flex flex-wrap items-center gap-2" onSubmit={(e) => { e.preventDefault(); set.mutate(undefined, { onSuccess: () => toast.success("Budget saved"), onError: (er) => toast.error(pmError(er)) }); }}>
          <input className="w-20 border border-border bg-background px-2 py-1 text-[13px]" value={cur} onChange={(e) => setCur(e.target.value.toUpperCase())} maxLength={3} aria-label="Currency" />
          <input className="w-40 border border-border bg-background px-2 py-1 text-[13px]" value={total} onChange={(e) => setTotal(e.target.value)} inputMode="decimal" placeholder="Total budget" aria-label="Total budget" />
          <button type="submit" className={btn} disabled={!Number(total)}>Set budget</button>
        </form>
      )}
      <button type="button" className={btn} disabled={opt.isPending} onClick={() => opt.mutate(undefined, { onSuccess: (x) => toast.message(x.summary ?? x.message ?? "Proposal ready"), onError: (e) => toast.error(pmError(e)) })}>
        {opt.isPending ? <Loader2 className="size-3 animate-spin" /> : <RefreshCw className="size-3" />} Propose a cheaper fair allocation</button>
      {b?.assumptions.map((a, i) => <p key={i} className="text-[11px] text-muted-foreground">{a}</p>)}
    </div>
  );
}

interface Room { members: Array<{ kind: string; name?: string; user_id?: string }>; messages: Array<{ id: string; display_name: string; content: string; created_at: string }>; minutes: Array<{ id: string; title: string; status: string; source: string; extracted: { facts: { decisions: string[]; action_items: Array<{ text: string; owner: string | null; due: string | null }> } } }>; decisions: Array<{ id: string; text: string; approved_by: string; approved_at: string }>; action_items: Array<{ id: string; text: string; owner: string | null; due: string | null; status: string }> }

function ProjectRoom({ pid, canManage }: { pid: string; canManage: boolean }) {
  const r = usePm<Room>(`/projects/${pid}/room`, { refetch: 15_000 });
  const [msg, setMsg] = useState("");
  const [minutes, setMinutes] = useState("");
  const post = usePmAction("POST", () => `/projects/${pid}/room/messages`, () => ({ content: msg }));
  const add = usePmAction("POST", () => `/projects/${pid}/room/minutes`, () => ({ title: "Meeting minutes", text: minutes }));
  const approve = usePmAction<string>("POST", (id) => `/projects/${pid}/room/minutes/${id}/approve`);
  const d = r.data;
  const fail = (e: Error) => toast.error(pmError(e));
  return (
    <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_300px]">
      <div className="space-y-2">
        <Loading q={r} />
        <ul className="max-h-80 space-y-1.5 overflow-y-auto">
          {d?.messages.map((m) => <li key={m.id} className="text-[12px]"><span className="font-mono text-[10px] text-muted-foreground">{m.display_name} · {new Date(m.created_at).toLocaleString()}</span><p className="whitespace-pre-line">{m.content}</p></li>)}
          {d && d.messages.length === 0 && <Empty>No messages yet.</Empty>}
        </ul>
        <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); post.mutate(undefined, { onSuccess: () => setMsg(""), onError: fail }); }}>
          <input className={input} value={msg} onChange={(e) => setMsg(e.target.value)} maxLength={4000} placeholder="Message the project team" aria-label="Room message" />
          <button type="submit" className={btn} disabled={!msg.trim()}><Send className="size-3" /></button>
        </form>
        <details className="border border-border p-2 text-[12px]">
          <summary className="cursor-pointer">Add meeting minutes</summary>
          <textarea className={cn(input, "mt-2")} rows={4} value={minutes} onChange={(e) => setMinutes(e.target.value)} placeholder={"Paste the minutes. Lines like “Decision: …” and “Action: … (owner: Priya) due Friday” are picked up."} aria-label="Meeting minutes" />
          <button type="button" className={cn(btn, "mt-1")} disabled={minutes.trim().length < 10 || add.isPending} onClick={() => add.mutate(undefined, { onSuccess: () => { setMinutes(""); toast.success("Minutes added as a draft. They count after a manager approves them."); }, onError: fail })}>Add as draft</button>
        </details>
        {d?.minutes.filter((m) => m.status === "draft").map((m) => (
          <div key={m.id} className="border border-warning/50 bg-warning/5 p-2 text-[12px]">
            <div className="flex items-center justify-between"><span className="font-medium">{m.title}</span><Tag tone="warn">draft · {m.source.startsWith("ai:") ? "AI" : "rule-based"}</Tag></div>
            <ul className="mt-1 list-disc pl-4">{m.extracted.facts.decisions.map((x, i) => <li key={i}>Decision: {x}</li>)}{m.extracted.facts.action_items.map((x, i) => <li key={`a${i}`}>Action: {x.text}</li>)}</ul>
            {canManage && <button type="button" className={cn(btn, "mt-1")} onClick={() => approve.mutate(m.id, { onSuccess: () => toast.success("Approved: decisions and action items recorded"), onError: fail })}><CheckCircle2 className="size-3" /> Approve</button>}
          </div>
        ))}
      </div>
      <div className="space-y-3">
        <div><div className="label-xs mb-1">Agreed decisions</div>{d?.decisions.length ? <ul className="space-y-1 text-[12px]">{d.decisions.map((x) => <li key={x.id}>{x.text}<span className="block text-[10px] text-muted-foreground">approved by {x.approved_by}</span></li>)}</ul> : <p className="text-[12px] text-muted-foreground">None yet.</p>}</div>
        <div><div className="label-xs mb-1">Action items</div>{d?.action_items.length ? <ul className="space-y-1 text-[12px]">{d.action_items.map((x) => <li key={x.id}>{x.text}<span className="block text-[10px] text-muted-foreground">{x.owner ?? "no owner"}{x.due ? ` · due ${x.due}` : ""}</span></li>)}</ul> : <p className="text-[12px] text-muted-foreground">None yet.</p>}</div>
        <div><div className="label-xs mb-1">Team</div><ul className="text-[12px]">{d?.members.map((m, i) => <li key={i}>{m.name ?? "Project manager"}</li>)}</ul></div>
      </div>
    </div>
  );
}

// ── approvals ─────────────────────────────────────────────────────────────────
function Approvals() {
  const s = usePm<PmSummary>("/dashboard/summary", { refetch: 20_000 });
  const decide = usePmAction<{ id: string; ok: boolean; comments: string }>("POST", (v) => `/approvals/${v.id}/${v.ok ? "approve" : "reject"}`, (v) => ({ comments: v.comments }));
  const resolve = usePmAction<{ id: string; approve: boolean }>("POST", (v) => `/change-requests/${v.id}/resolve`, (v) => ({ approve: v.approve, note: "" }));
  const [note, setNote] = useState<Record<string, string>>({});
  const fail = (e: Error) => toast.error(pmError(e));
  const pending: PmApproval[] = s.data?.pending_approvals ?? [];
  const crs: PmChangeRequest[] = (s.data?.change_requests ?? []).filter((c) => c.status === "open" || c.status === "pending");
  return (
    <div className="space-y-4">
      <Loading q={s} />
      <Panel title={`Allocations waiting for a person (${pending.length})`} dense className="border border-border">
        {pending.length === 0 && <div className="p-3"><Empty>Nothing is waiting. Critical tasks, loads above 85% and leave reallocations appear here.</Empty></div>}
        <ul>
          {pending.map((a) => (
            <li key={a.approval_id} className="space-y-1 border-b border-border px-3 py-2.5 text-[12px] last:border-0">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span><span className="font-medium">{a.task_title}</span> <span className="text-muted-foreground">({a.task_id})</span></span>
                <span className="flex gap-1"><Tag>{a.priority}</Tag><Tag tone="warn">{a.kind === "REALLOCATION" ? "reallocation" : "new assignment"}</Tag></span>
              </div>
              <p>Recommended: <span className="font-medium">{a.recommended_new_owner_name ?? "nobody eligible"}</span> · suitability {a.suitability_score} · load after {a.post_utilization_pct}%{a.previous_owner ? ` · was ${a.previous_owner}` : ""}</p>
              <p className="text-muted-foreground">{a.explanation}</p>
              <div className="flex flex-wrap gap-2">
                <input className="min-w-0 flex-1 border border-border bg-background px-2 py-1 text-[12px]" value={note[a.approval_id] ?? ""} onChange={(e) => setNote({ ...note, [a.approval_id]: e.target.value })} placeholder="Comment (optional)" aria-label="Decision comment" />
                <button type="button" className={btnPrimary} disabled={decide.isPending} onClick={() => decide.mutate({ id: a.approval_id, ok: true, comments: note[a.approval_id] ?? "" }, { onSuccess: () => toast.success("Approved and assigned"), onError: fail })}><CheckCircle2 className="size-3" /> Approve</button>
                <button type="button" className={btn} disabled={decide.isPending} onClick={() => decide.mutate({ id: a.approval_id, ok: false, comments: note[a.approval_id] ?? "" }, { onSuccess: () => toast.success("Rejected"), onError: fail })}><XCircle className="size-3" /> Reject</button>
              </div>
            </li>
          ))}
        </ul>
      </Panel>
      <Panel title={`Requests from the team (${crs.length})`} dense className="border border-border">
        {crs.length === 0 && <div className="p-3"><Empty>No open reassignment, deadline or leave requests.</Empty></div>}
        <ul>{crs.map((c) => (
          <li key={c.id} className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-3 py-2 text-[12px] last:border-0">
            <span><Tag>{c.kind.replace("_", " ")}</Tag> {c.details} <span className="text-muted-foreground">· {c.employee_id}{c.task_id ? ` · ${c.task_id}` : ""}</span></span>
            <span className="flex gap-1"><button type="button" className={btn} onClick={() => resolve.mutate({ id: c.id, approve: true }, { onError: fail })}>Approve</button><button type="button" className={btn} onClick={() => resolve.mutate({ id: c.id, approve: false }, { onError: fail })}>Decline</button></span>
          </li>
        ))}</ul>
      </Panel>
    </div>
  );
}

// ── team roster ──────────────────────────────────────────────────────────────
function Team() {
  const emps = usePm<PmEmployeeScore[]>("/employees");
  const team = usePm<Array<{ user_id: string; name: string; email: string; role: string; on_roster: boolean }>>("/employees/eaawp-team");
  const add = usePmAction<string[], { added: unknown[] }>("POST", () => "/employees/from-team", (ids) => ({ user_ids: ids }));
  const leave = usePmAction<string, { proposals_created: unknown[] }>("POST", () => "/disruptions/simulate", (id) => ({ employee_id: id, new_status: "On Leave", leave_days: 3, reason: "Leave" }));
  const [sel, setSel] = useState<string | null>(null);
  const missing = (team.data ?? []).filter((t) => !t.on_roster);
  const fail = (e: Error) => toast.error(pmError(e));
  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
      <Panel title="Project team" dense className="border border-border" actions={
        <button type="button" className={btn} onClick={() => void pmDownload("/employees/export.csv", "project-team.csv").catch((e: Error) => toast.error(e.message))}><Download className="size-3" /> CSV</button>}>
        <Loading q={emps} />
        {emps.data?.length === 0 && <div className="p-3"><Empty>The roster is empty. Add your EAAWP team members (right) or import a spreadsheet.</Empty></div>}
        <div className="overflow-x-auto">
          <table className="w-full text-[12px]">
            {(emps.data?.length ?? 0) > 0 && <thead><tr className="border-b border-border text-left"><th className="label-xs px-3 py-1">Person</th><th className="label-xs">Status</th><th className="label-xs">Workload</th><th className="label-xs">Free h/wk</th><th className="label-xs">Skill</th><th className="label-xs">Performance</th><th /></tr></thead>}
            <tbody>{emps.data?.map((e) => (
              <tr key={e.employee_id} className={cn("border-b border-border", sel === e.employee_id && "bg-accent")}>
                <td className="px-3 py-1.5"><button type="button" className="text-left hover:underline" onClick={() => setSel(e.employee_id)}>{e.name}</button><div className="text-[10px] text-muted-foreground">{e.designation} · {e.department}</div></td>
                <td><Tag tone={e.status === "On Leave" ? "warn" : "muted"}>{e.status}</Tag></td>
                <td className="w-28 pr-2"><div className="font-mono text-[11px]">{e.workload_score}%</div><Meter value={Math.min(100, e.workload_score)} /></td>
                <td className="font-mono">{e.free_capacity_hrs}</td><td className="font-mono">{e.skill_score}</td><td className="font-mono">{e.performance_score}</td>
                <td className="pr-2"><button type="button" className={btn} disabled={e.status === "On Leave"} onClick={() => { if (window.confirm(`Record that ${e.name} is on leave for 3 days? Their open tasks will get reallocation proposals for approval.`)) leave.mutate(e.employee_id, { onSuccess: (r) => toast.success(`${r.proposals_created.length} reallocation proposal(s) wait in Approvals`), onError: fail }); }}>On leave</button></td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      </Panel>
      <div className="space-y-4">
        <Panel title="Add from your EAAWP team" dense className="border border-border">
          <div className="space-y-2 px-3 py-3 text-[12px]">
            {missing.length === 0 ? <p className="text-muted-foreground">Everyone in the company is on the roster.</p> : (<>
              <ul>{missing.map((m) => <li key={m.user_id}>{m.name} <span className="text-muted-foreground">· {m.email}</span></li>)}</ul>
              <button type="button" className={btnPrimary} disabled={add.isPending} onClick={() => add.mutate(missing.map((m) => m.user_id), { onSuccess: (r) => toast.success(`${r.added.length} added. Add their skills so allocation can use them.`), onError: fail })}><UserPlus className="size-3" /> Add {missing.length} to the roster</button>
              <p className="text-muted-foreground">Skills start empty and unverified: nothing about a person is guessed.</p>
            </>)}
          </div>
        </Panel>
        <ImportTeam />
        {sel && <PersonCard id={sel} onClose={() => setSel(null)} />}
      </div>
    </div>
  );
}

function ImportTeam() {
  const ref = useRef<HTMLInputElement>(null);
  const analyze = usePmUpload<{ records: Array<Record<string, unknown> & { name: string; email: string; issues: Array<{ severity: string; message: string }> }>; files: Array<{ filename: string; status: string; error?: string }> }>("/employees/import/analyze");
  const confirm = usePmAction<unknown[], { imported: unknown[]; failed: unknown[] }>("POST", () => "/employees/import/confirm", (records) => ({ confirm: true, records }));
  const recs = analyze.data?.records ?? [];
  const ok = recs.filter((r) => !r.issues.some((i) => i.severity === "error"));
  return (
    <Panel title="Import people from a file" dense className="border border-border">
      <div className="space-y-2 px-3 py-3 text-[12px]">
        <input ref={ref} type="file" multiple accept=".csv,.xlsx,.pdf,.docx,.txt,.pptx" className="hidden" onChange={(e) => {
          const files = Array.from(e.target.files ?? []); if (files.length) analyze.mutate({ files }, { onError: (er) => toast.error(pmError(er)) }); if (ref.current) ref.current.value = "";
        }} />
        <button type="button" className={btn} disabled={analyze.isPending} onClick={() => ref.current?.click()}>{analyze.isPending ? <Loader2 className="size-3 animate-spin" /> : <Upload className="size-3" />} Choose spreadsheet or document</button>
        <p className="text-muted-foreground">Nothing is saved until you confirm. Records with errors are left out.</p>
        {recs.length > 0 && (<>
          <ul className="max-h-48 space-y-1 overflow-y-auto">{recs.map((r, i) => <li key={i} className="border-b border-border pb-1"><span className="font-medium">{r.name || "(no name)"}</span> <span className="text-muted-foreground">{r.email}</span>
            {r.issues.map((x, j) => <span key={j} className={cn("block text-[11px]", x.severity === "error" ? "text-destructive" : "text-warning")}>{x.message}</span>)}</li>)}</ul>
          <button type="button" className={btnPrimary} disabled={!ok.length || confirm.isPending} onClick={() => confirm.mutate(ok.map(({ issues: _i, source_file: _s, ...rest }) => rest), { onSuccess: (r) => { toast.success(`${r.imported.length} imported`); analyze.reset(); }, onError: (e) => toast.error(pmError(e)) })}>
            <CheckCircle2 className="size-3" /> Import {ok.length} record(s)</button>
        </>)}
      </div>
    </Panel>
  );
}

interface Intelligence { employee: PmEmployeeScore; skills: Array<{ skill: string; score: number; confidence: string; evidence: Array<{ text?: string; kind?: string } | string> }>; completed: PmTask[] }

function PersonCard({ id, onClose }: { id: string; onClose: () => void }) {
  const q = usePm<Intelligence>(`/employees/${id}/intelligence`);
  const evaluate = usePmAction("POST", () => `/employees/${id}/skills/evaluate`);
  const d = q.data;
  return (
    <Panel title="Person" dense className="border border-border" actions={<button type="button" aria-label="Close" onClick={onClose}><X className="size-3.5" /></button>}>
      <Loading q={q} />
      {d && (
        <div className="space-y-2 px-3 py-3 text-[12px]">
          <p className="font-medium">{d.employee.name} <span className="font-normal text-muted-foreground">· {d.employee.designation}</span></p>
          <KeyValue k="Workload" v={`${d.employee.workload_score}%`} /><KeyValue k="Free hours / week" v={d.employee.free_capacity_hrs} /><KeyValue k="Level" v={d.employee.level} />
          <div className="label-xs pt-1">Skills (0–10, with evidence)</div>
          {d.skills.length === 0 && <p className="text-muted-foreground">No skills recorded yet.</p>}
          <ul className="space-y-1">{d.skills.map((s) => <li key={s.skill} className="flex justify-between"><span>{s.skill}</span><span className="font-mono">{s.score} <span className="text-muted-foreground">({s.confidence})</span></span></li>)}</ul>
          <button type="button" className={btn} disabled={evaluate.isPending} onClick={() => evaluate.mutate(undefined, { onSuccess: () => toast.success("Skill scores re-evaluated from the evidence"), onError: (e) => toast.error(pmError(e)) })}><RefreshCw className="size-3" /> Re-evaluate from evidence</button>
          <p className="text-[11px] text-muted-foreground">{d.completed.length} completed task(s) on record.</p>
        </div>
      )}
    </Panel>
  );
}

// ── audit ─────────────────────────────────────────────────────────────────────
function Audit() {
  const q = usePm<{ entries: PmAuditEntry[]; verification: { valid: boolean; entries?: number; broken_at?: string | null } }>("/audit?limit=200");
  return (
    <Panel title="Audit ledger (tamper-evident)" dense className="border border-border" actions={
      <button type="button" className={btn} onClick={() => void pmDownload("/audit/export.csv", "project-audit-ledger.csv").catch((e: Error) => toast.error(e.message))}><Download className="size-3" /> CSV</button>}>
      <Loading q={q} />
      {q.data && <div className="flex items-center gap-2 border-b border-border px-3 py-2 text-[12px]">{q.data.verification.valid ? <ShieldCheck className="size-4 text-success" /> : <AlertTriangle className="size-4 text-destructive" />}{q.data.verification.valid ? "Every entry's SHA-256 chain checks out." : "The chain check FAILED: the records were changed outside the application."}</div>}
      <ul>{q.data?.entries.map((e) => (
        <li key={e.id} className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-3 py-1.5 text-[12px] last:border-0">
          <span><span className="font-mono text-[10px] text-muted-foreground">{new Date(e.timestamp).toLocaleString()}</span> <span className="font-medium">{e.action.replaceAll("_", " ").toLowerCase()}</span> <span className="text-muted-foreground">· {e.entity_id} · by {e.actor}</span></span>
          <span className="font-mono text-[9px] text-muted-foreground" title={e.sha256_proof}>{e.sha256_proof.slice(0, 12)}…</span>
        </li>
      ))}</ul>
    </Panel>
  );
}

// ── my work (everyone) ───────────────────────────────────────────────────────
interface Portal { linked: boolean; message?: string; tasks?: PmTask[]; projects: PmProgress[]; change_requests?: PmChangeRequest[]; growth?: Array<{ skill: string; recommendation: string }> }

function MyWork({ go }: { go: (pid: string) => void }) {
  const q = usePm<Portal>("/me/portal", { refetch: 30_000 });
  const prog = usePmAction<{ id: string; pct: number; review: boolean }>("POST", (v) => `/tasks/${v.id}/progress`, (v) => ({ progress_pct: v.pct, ...(v.review ? { status: "DELIVERABLE_IN_REVIEW" } : { status: "IN_PROGRESS" }) }));
  const ask = usePmAction<{ kind: string; task_id: string | null; details: string }>("POST", () => "/change-requests", (v) => v);
  const [pct, setPct] = useState<Record<string, number>>({});
  const fail = (e: Error) => toast.error(pmError(e));
  const d = q.data;
  return (
    <div className="space-y-4">
      <Loading q={q} />
      {d && !d.linked && <Empty>{d.message}</Empty>}
      {d?.linked && (
        <Panel title={`My tasks (${d.tasks?.length ?? 0})`} dense className="border border-border">
          {(d.tasks?.length ?? 0) === 0 && <div className="p-3"><Empty>No project tasks are assigned to you right now.</Empty></div>}
          <ul>{d.tasks?.map((t) => (
            <li key={t.id} className="space-y-1 border-b border-border px-3 py-2.5 text-[12px] last:border-0">
              <div className="flex flex-wrap items-center justify-between gap-2"><span className="font-medium">{t.title} <span className="font-mono text-[10px] font-normal text-muted-foreground">{t.id}</span></span><Tag tone={statusTone(t.status)}>{STATUS_LABEL[t.status] ?? t.status}</Tag></div>
              {t.why_me && <p className="text-muted-foreground">Why you: {t.why_me}</p>}
              {(t.dependency_status?.some((x) => x.status !== "COMPLETED_AND_AUDITED")) && <p className="text-warning">Waiting on: {t.dependency_status?.filter((x) => x.status !== "COMPLETED_AND_AUDITED").map((x) => x.task_id).join(", ")}</p>}
              {["ASSIGNED", "IN_PROGRESS", "REWORK_REQUESTED"].includes(t.status) && (
                <div className="flex flex-wrap items-center gap-2">
                  <input type="range" min={0} max={100} step={5} value={pct[t.id] ?? t.progress_pct} onChange={(e) => setPct({ ...pct, [t.id]: Number(e.target.value) })} aria-label={`Progress for ${t.title}`} />
                  <span className="w-10 font-mono">{pct[t.id] ?? t.progress_pct}%</span>
                  <button type="button" className={btn} onClick={() => prog.mutate({ id: t.id, pct: pct[t.id] ?? t.progress_pct, review: false }, { onSuccess: () => toast.success("Progress saved"), onError: fail })}>Save progress</button>
                  <button type="button" className={btnPrimary} onClick={() => prog.mutate({ id: t.id, pct: 100, review: true }, { onSuccess: () => toast.success("Sent for review. It counts as done once a manager accepts it."), onError: fail })}>Submit for review</button>
                  <button type="button" className={btn} onClick={() => { const details = window.prompt("What do you need (more time, someone else, …)?"); if (details && details.trim().length >= 3) ask.mutate({ kind: "deadline_change", task_id: t.id, details }, { onSuccess: () => toast.success("Request sent to the administrators"), onError: fail }); }}>Ask for a change</button>
                </div>
              )}
            </li>
          ))}</ul>
        </Panel>
      )}
      {d && d.projects.length > 0 && (
        <Panel title="My projects" dense className="border border-border">
          <ul>{d.projects.map((p) => <li key={p.project_id}><button type="button" onClick={() => go(p.project_id)} className="block w-full border-b border-border px-3 py-2 text-left last:border-0 hover:bg-accent"><div className="flex justify-between text-[13px]"><span>{p.name}</span><Tag tone={healthTone(p.health)}>{p.health}</Tag></div><div className="mt-1"><ProgressBar p={p} /></div></button></li>)}</ul>
        </Panel>
      )}
      {d?.linked && (d.growth?.length ?? 0) > 0 && (
        <Panel title="Growth suggestions" dense className="border border-border"><ul className="space-y-1 px-3 py-2 text-[12px]">{d.growth?.map((g, i) => <li key={i}><span className="font-medium">{g.skill}:</span> {g.recommendation}</li>)}</ul></Panel>
      )}
    </div>
  );
}

// ── page ─────────────────────────────────────────────────────────────────────
type Section = "overview" | "projects" | "approvals" | "team" | "audit" | "mine";

export function ProjectManagerPanel() {
  const me = usePm<PmMe>("/me");
  const isAdmin = !!me.data?.is_admin;
  const [section, setSection] = useState<Section | null>(null);
  const [pid, setPid] = useState<string | null>(null);
  const projects = usePm<PmProgress[]>("/projects");
  const current: Section = section ?? (isAdmin ? "overview" : "mine");
  const sections = useMemo<Array<[Section, string]>>(() => isAdmin
    ? [["overview", "Overview"], ["projects", "Projects"], ["approvals", "Approvals"], ["team", "Team"], ["audit", "Audit"], ["mine", "My work"]]
    : [["mine", "My work"], ["projects", "Projects"]], [isAdmin]);
  const go = (id: string) => { setPid(id); setSection("projects"); };
  if (me.error) {
    return <div className="mx-auto max-w-3xl p-6"><Empty>{pmError(me.error)}</Empty></div>;
  }
  return (
    <div className="mx-auto max-w-7xl space-y-4 p-4 md:p-6" data-testid="pm-panel">
      <header className="flex flex-wrap items-start justify-between gap-3 border-b border-border pb-3">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">Project Manager</h1>
          <p className="mt-0.5 text-xs text-muted-foreground">{isAdmin ? "Plans from project documents, fair task allocation, approvals and verified progress." : "Your project tasks, what they depend on and how to report progress."}</p>
        </div>
        {isAdmin && <NewProject onCreated={go} />}
      </header>
      <AiNotice ai={me.data?.ai} />
      <nav className="flex flex-wrap gap-1" aria-label="Project Manager sections">
        {sections.map(([k, label]) => (
          <button key={k} type="button" onClick={() => setSection(k)} className={cn("border px-3 py-1.5 font-mono text-[10px] uppercase tracking-[0.12em]", current === k ? "border-primary bg-primary text-primary-foreground" : "border-border text-muted-foreground hover:text-foreground")}>{label}</button>
        ))}
      </nav>
      {current === "overview" && isAdmin && <AdminOverview go={go} />}
      {current === "projects" && (
        <div className="grid gap-4 lg:grid-cols-[300px_minmax(0,1fr)]">
          <section aria-label="Projects" className="space-y-1">
            <Loading q={projects} />
            {projects.data?.length === 0 && <Empty>{isAdmin ? "No projects yet." : "You are not on any project yet."}</Empty>}
            {projects.data?.map((p) => (
              <button key={p.project_id} type="button" onClick={() => setPid(p.project_id)} className={cn("block w-full border px-3 py-2 text-left", p.project_id === pid ? "border-primary bg-surface" : "border-border hover:bg-accent")}>
                <div className="flex items-center justify-between gap-2"><span className="truncate text-[13px] font-medium">{p.name}</span><Tag tone={healthTone(p.health)}>{p.health}</Tag></div>
                <span className="text-[11px] text-muted-foreground">{p.stage_label} · {p.completion_pct}% verified</span>
              </button>
            ))}
          </section>
          <main className="min-w-0">{pid ? <ProjectDetail key={pid} pid={pid} isAdmin={isAdmin} onClose={() => setPid(null)} /> : <p className="text-[13px] text-muted-foreground">Select a project.</p>}</main>
        </div>
      )}
      {current === "approvals" && isAdmin && <Approvals />}
      {current === "team" && isAdmin && <Team />}
      {current === "audit" && isAdmin && <Audit />}
      {current === "mine" && <MyWork go={go} />}
    </div>
  );
}
