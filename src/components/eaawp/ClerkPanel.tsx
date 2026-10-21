/**
 * ClerkPanel - Institutional Clerk: service requests with a visible timeline, review queue for
 * administrators, templated documents that are drafted, then issued with a serial number.
 * Everything shown comes from the backend; members only ever see their own requests.
 */
import { useRef, useState } from "react";
import { toast } from "sonner";
import { Loader2, Plus, Send, FileText, Download, Ban, CheckCircle2, X, Upload } from "lucide-react";
import { cn } from "@/lib/utils";
import { useSession } from "@/state/session";
import {
  useClerkMeta, useClerkRequests, useClerkRequest, useCreateClerkRequest, useClerkComment, useClerkCancel, useClerkStatus,
  useClerkDocuments, useDraftClerkDocument, useClerkDocumentAction, downloadClerkDocument, useExtractClerkFields,
  type ClerkRequestFE, type ClerkDocumentFE,
} from "@/hooks/use-api";

const STATUS: Record<string, { label: string; cls: string }> = {
  submitted: { label: "SUBMITTED", cls: "text-muted-foreground border-muted-foreground/40" },
  in_review: { label: "IN REVIEW", cls: "text-warning border-warning/40" },
  needs_info: { label: "NEEDS INFO", cls: "text-warning border-warning/40" },
  approved: { label: "APPROVED", cls: "text-success border-success/40" },
  rejected: { label: "REJECTED", cls: "text-destructive border-destructive/40" },
  fulfilled: { label: "FULFILLED", cls: "text-success border-success/40" },
  cancelled: { label: "CANCELLED", cls: "text-muted-foreground border-muted-foreground/40" },
};
const NEXT: Record<string, string[]> = {
  submitted: ["in_review", "needs_info", "approved", "rejected"],
  in_review: ["needs_info", "approved", "rejected"],
  needs_info: ["in_review", "rejected"],
  approved: ["fulfilled"],
};

function Badge({ status }: { status: string }) {
  const c = STATUS[status] ?? STATUS["submitted"]!;
  return <span className={cn("shrink-0 border px-1.5 py-0.5 font-mono text-[9px] tracking-[0.06em]", c.cls)}>{c.label}</span>;
}

function NewRequest({ onCreated }: { onCreated: (id: string) => void }) {
  const meta = useClerkMeta();
  const create = useCreateClerkRequest();
  const [type, setType] = useState("certificate");
  const [title, setTitle] = useState("");
  const [details, setDetails] = useState("");
  const [open, setOpen] = useState(false);
  if (!open) {
    return (
      <button type="button" onClick={() => setOpen(true)} className="inline-flex items-center gap-2 border border-border bg-surface px-3 py-2 text-[12px] hover:bg-accent">
        <Plus className="h-4 w-4" /> New request
      </button>
    );
  }
  return (
    <form className="space-y-2 border border-border bg-surface p-3" onSubmit={(e) => {
      e.preventDefault();
      create.mutate({ request_type: type, title, details }, {
        onSuccess: (d) => { toast.success("Request submitted"); setTitle(""); setDetails(""); setOpen(false); onCreated(d.id); },
        onError: (er) => toast.error(er.message),
      });
    }}>
      <select value={type} onChange={(e) => setType(e.target.value)} aria-label="Request type" className="w-full border border-border bg-background px-2 py-1.5 text-[13px]">
        {Object.entries(meta.data?.request_types ?? { certificate: "Certificate" }).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
      </select>
      <input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} placeholder="Short title, e.g. Bonafide certificate for bank loan" aria-label="Request title" className="w-full border border-border bg-background px-2 py-1.5 text-[13px]" />
      <textarea value={details} onChange={(e) => setDetails(e.target.value)} maxLength={4000} rows={3} placeholder="Details that help the clerk (dates, purpose, ID number)" aria-label="Request details" className="w-full border border-border bg-background px-2 py-1.5 text-[13px]" />
      <div className="flex gap-2">
        <button type="submit" disabled={create.isPending || title.trim().length < 3} className="inline-flex items-center gap-2 border border-border bg-primary px-3 py-1.5 text-[12px] text-primary-foreground disabled:opacity-50">
          {create.isPending && <Loader2 className="h-3 w-3 animate-spin" />} Submit
        </button>
        <button type="button" onClick={() => setOpen(false)} className="border border-border px-3 py-1.5 text-[12px] hover:bg-accent">Cancel</button>
      </div>
    </form>
  );
}

function DocumentRow({ d, isAdmin }: { d: ClerkDocumentFE; isAdmin: boolean }) {
  const act = useClerkDocumentAction();
  return (
    <li className="border border-border bg-background p-2 text-[12px]">
      <div className="flex items-center justify-between gap-2">
        <span className="font-medium">{d.title}</span>
        <span className="font-mono text-[10px] text-muted-foreground">{d.status.toUpperCase()}{d.serial ? ` - ${d.serial}` : ""}</span>
      </div>
      <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap text-[11px] text-muted-foreground">{d.body}</pre>
      <div className="mt-1 flex gap-2">
        {d.status === "issued" && <button type="button" className="inline-flex items-center gap-1 border border-border px-2 py-0.5 text-[11px] hover:bg-accent" onClick={() => void downloadClerkDocument(d.id).catch((e: Error) => toast.error(e.message))}><Download className="h-3 w-3" /> Download</button>}
        {isAdmin && d.status === "draft" && <button type="button" disabled={act.isPending} className="inline-flex items-center gap-1 border border-border px-2 py-0.5 text-[11px] hover:bg-accent" onClick={() => act.mutate({ id: d.id, action: "issue" }, { onSuccess: (x) => toast.success(`Issued ${x.serial}`), onError: (e) => toast.error(e.message) })}><CheckCircle2 className="h-3 w-3" /> Issue</button>}
        {isAdmin && d.status !== "void" && <button type="button" className="inline-flex items-center gap-1 border border-border px-2 py-0.5 text-[11px] text-destructive hover:bg-accent" onClick={() => { const reason = window.prompt("Why is this document being voided?"); if (reason) act.mutate({ id: d.id, action: "void", reason }, { onError: (e) => toast.error(e.message) }); }}><Ban className="h-3 w-3" /> Void</button>}
      </div>
    </li>
  );
}

function DraftForm({ requestId }: { requestId: string }) {
  const meta = useClerkMeta();
  const draft = useDraftClerkDocument();
  const extract = useExtractClerkFields();
  const fileRef = useRef<HTMLInputElement>(null);
  const [key, setKey] = useState("bonafide");
  const [vals, setVals] = useState<Record<string, string>>({});
  const tpl = meta.data?.templates.find((t) => t.key === key);
  return (
    <div className="space-y-2 border border-border p-2">
      <div className="flex flex-wrap items-center gap-2">
        <select value={key} onChange={(e) => { setKey(e.target.value); setVals({}); }} aria-label="Document template" className="border border-border bg-background px-2 py-1 text-[12px]">
          {meta.data?.templates.map((t) => <option key={t.key} value={t.key}>{t.title}</option>)}
        </select>
        <input ref={fileRef} type="file" accept=".pdf,.docx,.txt,.md" className="hidden" onChange={(e) => {
          const f = e.target.files?.[0]; if (!f) return;
          extract.mutate(f, { onSuccess: (r) => { setVals((v) => ({ ...v, ...r.fields })); toast.success(`Filled ${Object.keys(r.fields).length} field(s) from the document - please check them`); }, onError: (er) => toast.error(er.message) });
          if (fileRef.current) fileRef.current.value = "";
        }} />
        <button type="button" onClick={() => fileRef.current?.click()} disabled={extract.isPending} className="inline-flex items-center gap-1 border border-border px-2 py-1 text-[11px] hover:bg-accent">
          {extract.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : <Upload className="h-3 w-3" />} Fill from a document
        </button>
      </div>
      {tpl?.fields.map((f) => (
        <input key={f.name} value={vals[f.name] ?? ""} onChange={(e) => setVals({ ...vals, [f.name]: e.target.value })} maxLength={500}
          placeholder={`${f.label}${f.required ? " *" : ""}`} aria-label={f.label} className="w-full border border-border bg-background px-2 py-1 text-[12px]" />
      ))}
      <button type="button" disabled={draft.isPending} className="inline-flex items-center gap-1 border border-border px-2 py-1 text-[12px] hover:bg-accent disabled:opacity-50"
        onClick={() => draft.mutate({ template_key: key, fields: vals, request_id: requestId }, { onSuccess: () => { toast.success("Draft prepared"); setVals({}); }, onError: (e) => toast.error(e.message) })}>
        <FileText className="h-3 w-3" /> Prepare draft
      </button>
    </div>
  );
}

function Detail({ id, isAdmin, onClose }: { id: string; isAdmin: boolean; onClose: () => void }) {
  const q = useClerkRequest(id);
  const comment = useClerkComment(id);
  const cancel = useClerkCancel(id);
  const status = useClerkStatus(id);
  const [text, setText] = useState("");
  const [internal, setInternal] = useState(false);
  const [note, setNote] = useState("");
  const r = q.data;
  if (!r) return <div className="p-4 text-[12px] text-muted-foreground">Loading...</div>;
  const open = ["submitted", "in_review", "needs_info"].includes(r.status);
  return (
    <div className="space-y-3 border border-border bg-surface p-4" data-testid="clerk-detail">
      <div className="flex items-start justify-between gap-2">
        <div>
          <h2 className="text-[14px] font-medium">{r.title}</h2>
          <p className="text-[11px] text-muted-foreground">{r.request_type.replace("_", " ")} - by {r.requester_name}{r.assignee_name ? ` - assigned to ${r.assignee_name}` : ""}</p>
        </div>
        <div className="flex items-center gap-2"><Badge status={r.status} /><button type="button" aria-label="Close" onClick={onClose}><X className="h-4 w-4" /></button></div>
      </div>
      {r.details && <p className="whitespace-pre-line text-[13px]">{r.details}</p>}
      {r.decision_note && <p className="text-[12px] text-muted-foreground">Decision note: {r.decision_note}</p>}

      <ol className="space-y-1.5" aria-label="Timeline">
        {r.events.map((e) => (
          <li key={e.id} className={cn("border-l-2 pl-2 text-[12px]", e.internal ? "border-warning" : "border-border")}>
            <span className="font-mono text-[10px] text-muted-foreground">{e.actor_name || "system"} - {new Date(e.created_at).toLocaleString()}{e.internal ? " - INTERNAL" : ""}</span>
            <p className="whitespace-pre-line">{e.body}</p>
          </li>
        ))}
      </ol>

      {r.documents.length > 0 && <ul className="space-y-2" aria-label="Documents">{r.documents.map((d) => <DocumentRow key={d.id} d={d} isAdmin={isAdmin} />)}</ul>}

      {isAdmin && NEXT[r.status] && (
        <div className="space-y-2 border-t border-border pt-3">
          <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={2000} placeholder="Note for the requester (required to reject or ask for info)" aria-label="Status note" className="w-full border border-border bg-background px-2 py-1 text-[12px]" />
          <div className="flex flex-wrap gap-2">
            {NEXT[r.status]!.map((s) => (
              <button key={s} type="button" disabled={status.isPending} className="border border-border px-2 py-1 text-[11px] hover:bg-accent disabled:opacity-50"
                onClick={() => status.mutate({ status: s, note }, { onSuccess: () => setNote(""), onError: (e) => toast.error(e.message) })}>{(STATUS[s]?.label ?? s).toLowerCase()}</button>
            ))}
          </div>
        </div>
      )}
      {isAdmin && ["approved", "fulfilled"].includes(r.status) && <DraftForm requestId={r.id} />}

      {open || isAdmin ? (
        r.status !== "rejected" && r.status !== "cancelled" && r.status !== "fulfilled" && (
          <form className="flex flex-wrap items-center gap-2 border-t border-border pt-3" onSubmit={(e) => { e.preventDefault(); comment.mutate({ body: text, internal }, { onSuccess: () => setText(""), onError: (er) => toast.error(er.message) }); }}>
            <input value={text} onChange={(e) => setText(e.target.value)} maxLength={4000} placeholder="Add a comment" aria-label="Comment" className="min-w-0 flex-1 border border-border bg-background px-2 py-1.5 text-[12px]" />
            {isAdmin && <label className="flex items-center gap-1 text-[11px]"><input type="checkbox" checked={internal} onChange={(e) => setInternal(e.target.checked)} /> internal note</label>}
            <button type="submit" disabled={comment.isPending || !text.trim()} className="inline-flex items-center gap-1 border border-border px-2 py-1.5 text-[12px] hover:bg-accent disabled:opacity-50"><Send className="h-3 w-3" /> Send</button>
          </form>
        )
      ) : null}
      {!isAdmin && open && (
        <button type="button" className="inline-flex items-center gap-1 border border-border px-2 py-1 text-[11px] text-destructive hover:bg-accent" onClick={() => { if (window.confirm("Cancel this request?")) cancel.mutate(undefined, { onError: (e) => toast.error(e.message) }); }}><Ban className="h-3 w-3" /> Cancel request</button>
      )}
    </div>
  );
}

export function ClerkPanel() {
  const { user } = useSession();
  const isAdmin = user?.role === "Company Admin" || user?.role === "AI Administrator";
  const [filter, setFilter] = useState<string>("");
  const reqs = useClerkRequests(filter || undefined);
  const docs = useClerkDocuments(isAdmin);
  const [sel, setSel] = useState<string | null>(null);
  const list: ClerkRequestFE[] = reqs.data ?? [];
  return (
    <div className="mx-auto max-w-6xl space-y-6 p-4 md:p-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold">Institutional Clerk</h1>
          <p className="text-[12px] text-muted-foreground">{isAdmin ? "Review requests, ask for details, approve and issue numbered documents." : "Submit a request and follow it until it is done."}</p>
        </div>
        <NewRequest onCreated={setSel} />
      </header>
      <div className="grid gap-6 md:grid-cols-[320px_1fr]">
        <section aria-label="Requests" className="space-y-2">
          {isAdmin && (
            <select value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Filter by status" className="w-full border border-border bg-background px-2 py-1.5 text-[12px]">
              <option value="">All requests</option>
              {Object.keys(STATUS).map((s) => <option key={s} value={s}>{STATUS[s]!.label.toLowerCase()}</option>)}
            </select>
          )}
          {reqs.isLoading && <p className="text-[12px] text-muted-foreground">Loading...</p>}
          {!reqs.isLoading && list.length === 0 && <p className="border border-dashed border-border p-3 text-[12px] text-muted-foreground">{isAdmin ? "No requests yet." : "You have not made any requests yet."}</p>}
          {list.map((r) => (
            <button key={r.id} type="button" onClick={() => setSel(r.id)} className={cn("block w-full border px-3 py-2 text-left", r.id === sel ? "border-primary bg-surface" : "border-border hover:bg-accent")}>
              <div className="flex items-center justify-between gap-2"><span className="truncate text-[13px] font-medium">{r.title}</span><Badge status={r.status} /></div>
              <span className="text-[11px] text-muted-foreground">{r.request_type.replace("_", " ")}{isAdmin ? ` - ${r.requester_name}` : ""} - {new Date(r.created_at).toLocaleDateString()}</span>
            </button>
          ))}
        </section>
        <main className="min-w-0 space-y-6">
          {sel ? <Detail key={sel} id={sel} isAdmin={isAdmin} onClose={() => setSel(null)} /> : <p className="text-[13px] text-muted-foreground">Select a request to see its timeline.</p>}
          {isAdmin && (docs.data?.length ?? 0) > 0 && (
            <section aria-label="All documents" className="space-y-2">
              <h2 className="text-[14px] font-medium">Documents</h2>
              <ul className="space-y-2">{docs.data!.slice(0, 20).map((d) => <DocumentRow key={d.id} d={d} isAdmin />)}</ul>
            </section>
          )}
        </main>
      </div>
    </div>
  );
}
