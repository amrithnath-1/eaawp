/**
 * ClinicPanel - Medical Assistant (clinic SUPPORT). Appointment requests, clinic staff queue, intake in the
 * patient's own words. It never gives medical advice; emergency wording is shown an immediate safety message.
 */
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Loader2, Plus, Send, AlertTriangle, X, Trash2, ClipboardList } from "lucide-react";
import { cn } from "@/lib/utils";
import { useSession } from "@/state/session";
import {
  useClinicAppointments, useClinicAppointment, useCreateAppointment, useAppointmentNote, useAppointmentCancel,
  useAppointmentStatus, useAppointmentSummarize, useEraseAppointment, useScreenText, type ClinicAppointmentFE,
} from "@/hooks/use-api";

const STATUS: Record<string, string> = {
  requested: "text-warning border-warning/40", confirmed: "text-success border-success/40", completed: "text-muted-foreground border-muted-foreground/40",
  no_show: "text-destructive border-destructive/40", cancelled: "text-muted-foreground border-muted-foreground/40",
};
function Badge({ s }: { s: string }) {
  return <span className={cn("shrink-0 border px-1.5 py-0.5 font-mono text-[9px] tracking-[0.06em]", STATUS[s])}>{s.replace("_", " ").toUpperCase()}</span>;
}
function Alert({ kind, text }: { kind: string; text: string }) {
  return (
    <div role="alert" data-testid="safety-alert" className={cn("flex gap-2 border p-3 text-[13px]", kind === "boundary" ? "border-warning/50" : "border-destructive bg-destructive/10")}>
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /><p>{text}</p>
    </div>
  );
}

function NewAppointment({ disclaimer, onCreated }: { disclaimer: string; onCreated: (a: ClinicAppointmentFE) => void }) {
  const create = useCreateAppointment();
  const screen = useScreenText();
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [when, setWhen] = useState("");
  const [contact, setContact] = useState("");
  useEffect(() => {
    if (reason.trim().length < 5) return;
    const t = setTimeout(() => screen.mutate(reason), 500);
    return () => clearTimeout(t);
  }, [reason]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!open) {
    return <button type="button" onClick={() => setOpen(true)} className="inline-flex items-center gap-2 border border-border bg-surface px-3 py-2 text-[12px] hover:bg-accent"><Plus className="h-4 w-4" /> Request an appointment</button>;
  }
  const g = screen.data;
  return (
    <form className="space-y-2 border border-border bg-surface p-3" onSubmit={(e) => {
      e.preventDefault();
      create.mutate({ reason, preferred_time: when, contact }, { onSuccess: (a) => { setReason(""); setWhen(""); setContact(""); setOpen(false); onCreated(a); }, onError: (er) => toast.error(er.message) });
    }}>
      <p className="text-[11px] text-muted-foreground">{disclaimer}</p>
      {g?.kind && g.message && <Alert kind={g.kind} text={g.message} />}
      <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={4} maxLength={3000} aria-label="Reason for the appointment" placeholder="Tell the clinic why you would like to be seen, in your own words" className="w-full border border-border bg-background px-2 py-1.5 text-[13px]" />
      <input value={when} onChange={(e) => setWhen(e.target.value)} maxLength={80} aria-label="Preferred time" placeholder="Preferred days or times (optional)" className="w-full border border-border bg-background px-2 py-1.5 text-[13px]" />
      <input value={contact} onChange={(e) => setContact(e.target.value)} maxLength={120} aria-label="Contact" placeholder="Phone or email to reach you (optional)" className="w-full border border-border bg-background px-2 py-1.5 text-[13px]" />
      <div className="flex gap-2">
        <button type="submit" disabled={create.isPending || reason.trim().length < 3} className="inline-flex items-center gap-2 border border-border bg-primary px-3 py-1.5 text-[12px] text-primary-foreground disabled:opacity-50">{create.isPending && <Loader2 className="h-3 w-3 animate-spin" />} Send request</button>
        <button type="button" onClick={() => setOpen(false)} className="border border-border px-3 py-1.5 text-[12px] hover:bg-accent">Cancel</button>
      </div>
    </form>
  );
}

function Detail({ id, staff, onClose }: { id: string; staff: boolean; onClose: () => void }) {
  const q = useClinicAppointment(id);
  const note = useAppointmentNote(id);
  const cancel = useAppointmentCancel(id);
  const status = useAppointmentStatus(id);
  const summarize = useAppointmentSummarize(id);
  const erase = useEraseAppointment();
  const [text, setText] = useState("");
  const [internal, setInternal] = useState(false);
  const [when, setWhen] = useState("");
  const [clinician, setClinician] = useState("");
  const a = q.data;
  if (!a) return <div className="p-4 text-[12px] text-muted-foreground">Loading...</div>;
  const open = a.status === "requested" || a.status === "confirmed";
  return (
    <div className="space-y-3 border border-border bg-surface p-4" data-testid="clinic-detail">
      {a.emergency_notice && <Alert kind="emergency" text={a.emergency_notice} />}
      <div className="flex items-start justify-between gap-2">
        <div><h2 className="text-[14px] font-medium">{staff ? a.patient_name : "Your appointment request"}</h2>
          <p className="text-[11px] text-muted-foreground">{a.scheduled_for ? `Scheduled: ${a.scheduled_for}` : "Not scheduled yet"}{a.clinician_name ? ` - ${a.clinician_name}` : ""}{a.preferred_time ? ` - prefers ${a.preferred_time}` : ""}</p></div>
        <div className="flex items-center gap-2">{a.red_flag && <span className="border border-destructive px-1.5 py-0.5 font-mono text-[9px] text-destructive">URGENT WORDING</span>}<Badge s={a.status} /><button type="button" aria-label="Close" onClick={onClose}><X className="h-4 w-4" /></button></div>
      </div>
      <p className="whitespace-pre-line text-[13px]">{a.reason}</p>
      {staff && a.contact && <p className="text-[11px] text-muted-foreground">Contact: {a.contact}</p>}
      {a.intake?.note && (
        <div className="border border-border bg-background p-2 text-[12px]" data-testid="intake">
          <p className="font-mono text-[10px] text-muted-foreground">INTAKE (PATIENT'S OWN WORDS)</p>
          {a.intake.symptoms_reported?.length ? <p>Reported: {a.intake.symptoms_reported.join("; ")}</p> : null}
          {a.intake.duration ? <p>Duration: {a.intake.duration}</p> : null}
          {a.intake.medications_mentioned?.length ? <p>Medicines mentioned: {a.intake.medications_mentioned.join("; ")}</p> : null}
          {a.intake.allergies_mentioned?.length ? <p>Allergies mentioned: {a.intake.allergies_mentioned.join("; ")}</p> : null}
          <p className="text-[11px] text-muted-foreground">{a.intake.note}</p>
        </div>
      )}
      <ol className="space-y-1.5" aria-label="Messages">
        {a.notes.map((n, i) => (
          <li key={i} className={cn("border-l-2 pl-2 text-[12px]", n.internal ? "border-warning" : "border-border")}>
            <span className="font-mono text-[10px] text-muted-foreground">{n.by_name || "system"} - {new Date(n.at).toLocaleString()}{n.internal ? " - INTERNAL" : ""}</span><p>{n.text}</p>
          </li>
        ))}
      </ol>
      {staff && open && (
        <div className="space-y-2 border-t border-border pt-3">
          <div className="flex flex-wrap gap-2">
            <input type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} aria-label="Appointment date and time" className="border border-border bg-background px-2 py-1 text-[12px]" />
            <input value={clinician} onChange={(e) => setClinician(e.target.value)} maxLength={120} placeholder="Clinician (optional)" aria-label="Clinician" className="border border-border bg-background px-2 py-1 text-[12px]" />
            <button type="button" disabled={!when || status.isPending} className="border border-border px-2 py-1 text-[11px] hover:bg-accent disabled:opacity-50" onClick={() => status.mutate({ status: "confirmed", scheduled_for: when, clinician_name: clinician }, { onError: (e) => toast.error(e.message) })}>{a.status === "confirmed" ? "reschedule" : "confirm"}</button>
          </div>
          <div className="flex flex-wrap gap-2">
            {a.status === "confirmed" && <button type="button" className="border border-border px-2 py-1 text-[11px] hover:bg-accent" onClick={() => status.mutate({ status: "completed" }, { onError: (e) => toast.error(e.message) })}>completed</button>}
            {a.status === "confirmed" && <button type="button" className="border border-border px-2 py-1 text-[11px] hover:bg-accent" onClick={() => status.mutate({ status: "no_show" }, { onError: (e) => toast.error(e.message) })}>no show</button>}
            <button type="button" className="border border-border px-2 py-1 text-[11px] text-destructive hover:bg-accent" onClick={() => status.mutate({ status: "cancelled", note: "cancelled by the clinic" }, { onError: (e) => toast.error(e.message) })}>cancel</button>
          </div>
        </div>
      )}
      {staff && (
        <div className="flex flex-wrap gap-2 border-t border-border pt-3">
          <button type="button" disabled={summarize.isPending} className="inline-flex items-center gap-1 border border-border px-2 py-1 text-[11px] hover:bg-accent" onClick={() => summarize.mutate(undefined, { onError: (e) => toast.error(e.message) })}>{summarize.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : <ClipboardList className="h-3 w-3" />} Organise intake</button>
          <button type="button" className="inline-flex items-center gap-1 border border-border px-2 py-1 text-[11px] text-destructive hover:bg-accent" onClick={() => { if (window.confirm("Permanently erase this record?")) erase.mutate(a.id, { onSuccess: onClose, onError: (e) => toast.error(e.message) }); }}><Trash2 className="h-3 w-3" /> Erase record</button>
        </div>
      )}
      {open && (
        <form className="flex flex-wrap items-center gap-2 border-t border-border pt-3" onSubmit={(e) => { e.preventDefault(); note.mutate({ text, internal }, { onSuccess: () => setText(""), onError: (er) => toast.error(er.message) }); }}>
          <input value={text} onChange={(e) => setText(e.target.value)} maxLength={2000} placeholder="Add a message" aria-label="Message" className="min-w-0 flex-1 border border-border bg-background px-2 py-1.5 text-[12px]" />
          {staff && <label className="flex items-center gap-1 text-[11px]"><input type="checkbox" checked={internal} onChange={(e) => setInternal(e.target.checked)} /> internal note</label>}
          <button type="submit" disabled={note.isPending || !text.trim()} className="inline-flex items-center gap-1 border border-border px-2 py-1.5 text-[12px] hover:bg-accent disabled:opacity-50"><Send className="h-3 w-3" /> Send</button>
        </form>
      )}
      {!staff && open && <button type="button" className="border border-border px-2 py-1 text-[11px] text-destructive hover:bg-accent" onClick={() => { if (window.confirm("Cancel this appointment request?")) cancel.mutate(undefined, { onError: (e) => toast.error(e.message) }); }}>Cancel request</button>}
    </div>
  );
}

export function ClinicPanel() {
  const { user } = useSession();
  const staff = user?.role === "Company Admin" || user?.role === "AI Administrator";
  const list = useClinicAppointments();
  const [sel, setSel] = useState<string | null>(null);
  return (
    <div className="mx-auto max-w-6xl space-y-6 p-4 md:p-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold">Clinic Assistant</h1>
          <p className="text-[12px] text-muted-foreground">Appointments and clinic information. This assistant does not give medical advice. In an emergency call your local emergency number.</p>
        </div>
        <NewAppointment disclaimer="This assistant supports clinic administration only. It does not give medical advice, diagnoses or treatment." onCreated={(a) => setSel(a.id)} />
      </header>
      <div className="grid gap-6 md:grid-cols-[320px_1fr]">
        <section aria-label="Appointments" className="space-y-2">
          {list.isLoading && <p className="text-[12px] text-muted-foreground">Loading...</p>}
          {list.data?.length === 0 && <p className="border border-dashed border-border p-3 text-[12px] text-muted-foreground">{staff ? "No appointment requests." : "You have no appointment requests."}</p>}
          {list.data?.map((a) => (
            <button key={a.id} type="button" onClick={() => setSel(a.id)} className={cn("block w-full border px-3 py-2 text-left", a.id === sel ? "border-primary bg-surface" : "border-border hover:bg-accent")}>
              <div className="flex items-center justify-between gap-2"><span className="truncate text-[13px] font-medium">{staff ? a.patient_name : "Appointment request"}</span><Badge s={a.status} /></div>
              <span className="line-clamp-1 text-[11px] text-muted-foreground">{a.red_flag && a.status === "requested" ? "URGENT WORDING - " : ""}{a.reason}</span>
            </button>
          ))}
        </section>
        <main className="min-w-0">{sel ? <Detail key={sel} id={sel} staff={staff} onClose={() => setSel(null)} /> : <p className="text-[13px] text-muted-foreground">Select a request.</p>}</main>
      </div>
    </div>
  );
}
