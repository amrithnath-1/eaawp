/**
 * TeamPanel - invite people to the company and manage members (administrators only).
 * The invitation link is shown ONCE when it is created; the server keeps only a hash of it.
 */
import { useState } from "react";
import { toast } from "sonner";
import { Loader2, UserPlus, Copy, RefreshCw, Ban } from "lucide-react";
import { cn } from "@/lib/utils";
import { useSession } from "@/state/session";
import {
  useTeamMeta, useTeamMembers, useInvitations, useInvite, useInvitationAction, useMemberAction,
  type InvitationIssuedFE, type TeamMemberFE,
} from "@/hooks/use-api";

const fmt = (s: string) => new Date(s).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
const linkFor = (path: string) => `${window.location.origin}${path}`;

function IssuedLink({ issued, onDone }: { issued: InvitationIssuedFE; onDone: () => void }) {
  const url = linkFor(issued.accept_path);
  return (
    <div role="status" data-testid="invite-link" className="space-y-2 border border-success/40 bg-success/5 p-3 text-[12px]">
      <p>Invitation for <strong>{issued.email}</strong> created. Share this link with them securely. <strong>It is shown only once</strong> and expires on {fmt(issued.expires_at)}.</p>
      <div className="flex gap-2">
        <input readOnly value={url} aria-label="Invitation link" onFocus={(e) => e.currentTarget.select()} className="min-w-0 flex-1 border border-border bg-background px-2 py-1 font-mono text-[11px]" />
        <button type="button" className="inline-flex items-center gap-1 border border-border px-2 py-1 hover:bg-accent" onClick={() => { void navigator.clipboard?.writeText(url).then(() => toast.success("Link copied"), () => toast.error("Select the link and copy it manually")); }}><Copy className="h-3 w-3" /> Copy</button>
        <button type="button" className="border border-border px-2 py-1 hover:bg-accent" onClick={onDone}>Done</button>
      </div>
      {issued.email_delivery?.sent
        ? <p className="text-success" data-testid="email-result">An email with this link was sent to {issued.email}.</p>
        : issued.email_delivery
          ? <p className="text-destructive" role="alert" data-testid="email-result">Email not sent: {issued.email_delivery.error} Share the link yourself.</p>
          : <p className="text-muted-foreground">No email was sent. Share the link yourself, or tick "Email it to them" next time (needs email set up for the company).</p>}
    </div>
  );
}

function InviteForm({ roles }: { roles: string[] }) {
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("Employee");
  const [mail, setMail] = useState(false);
  const [issued, setIssued] = useState<InvitationIssuedFE | null>(null);
  const invite = useInvite();
  if (issued) return <IssuedLink issued={issued} onDone={() => setIssued(null)} />;
  return (
    <form className="flex flex-wrap items-end gap-2 border border-border bg-surface p-3" onSubmit={(e) => { e.preventDefault(); invite.mutate({ email, role, send_email: mail }, { onSuccess: (d) => { setIssued(d); setEmail(""); }, onError: (er) => toast.error(er.message) }); }}>
      <label className="flex min-w-[220px] flex-1 flex-col gap-1 text-[11px]">Email
        <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} maxLength={255} aria-label="Invitee email" placeholder="name@company.com" className="border border-border bg-background px-2 py-1.5 text-[13px]" />
      </label>
      <label className="flex flex-col gap-1 text-[11px]">Role
        <select value={role} onChange={(e) => setRole(e.target.value)} aria-label="Invitee role" className="border border-border bg-background px-2 py-1.5 text-[13px]">{roles.map((r) => <option key={r}>{r}</option>)}</select>
      </label>
      <label className="flex items-center gap-1.5 pb-2 text-[12px]"><input type="checkbox" checked={mail} onChange={(e) => setMail(e.target.checked)} aria-label="Email it to them" /> Email it to them</label>
      <button type="submit" disabled={invite.isPending || !email} className="inline-flex items-center gap-2 border border-border bg-primary px-3 py-1.5 text-[12px] text-primary-foreground disabled:opacity-50">{invite.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : <UserPlus className="h-4 w-4" />} Create invitation</button>
    </form>
  );
}

function MemberRow({ m, me, roles }: { m: TeamMemberFE; me: boolean; roles: string[] }) {
  const act = useMemberAction();
  const editable = !me && roles.includes(m.role);
  return (
    <li className="flex flex-wrap items-center gap-2 border border-border px-3 py-2 text-[12px]" data-testid="member-row">
      <div className="min-w-0 flex-1"><div className="truncate font-medium">{m.name}{me && <span className="ml-2 text-muted-foreground">(you)</span>}</div><div className="truncate text-muted-foreground">{m.email}</div></div>
      {editable ? (
        <select value={m.role} aria-label={`Role for ${m.email}`} disabled={act.isPending} onChange={(e) => act.mutate({ id: m.id, action: "role", role: e.target.value }, { onSuccess: () => toast.success("Role updated"), onError: (er) => toast.error(er.message) })} className="border border-border bg-background px-2 py-1 text-[12px]">{roles.map((r) => <option key={r}>{r}</option>)}</select>
      ) : <span className="font-mono text-[10px] text-muted-foreground">{m.role}</span>}
      <span className={cn("border px-1.5 py-0.5 font-mono text-[9px]", m.is_active ? "border-success/40 text-success" : "border-muted-foreground/40 text-muted-foreground")}>{m.is_active ? "ACTIVE" : "DEACTIVATED"}</span>
      {editable && (m.is_active
        ? <button type="button" disabled={act.isPending} className="border border-border px-2 py-1 text-[11px] text-destructive hover:bg-accent" onClick={() => { if (window.confirm(`Deactivate ${m.name}? They will be signed out and unable to log in.`)) act.mutate({ id: m.id, action: "deactivate" }, { onError: (er) => toast.error(er.message) }); }}>Deactivate</button>
        : <button type="button" disabled={act.isPending} className="border border-border px-2 py-1 text-[11px] hover:bg-accent" onClick={() => act.mutate({ id: m.id, action: "reactivate" }, { onError: (er) => toast.error(er.message) })}>Reactivate</button>)}
    </li>
  );
}

export function TeamPanel() {
  const { user } = useSession();
  const isAdmin = user?.role === "Company Admin" || user?.role === "AI Administrator";
  const meta = useTeamMeta(isAdmin);
  const members = useTeamMembers(isAdmin);
  const invs = useInvitations(isAdmin);
  const invAct = useInvitationAction();
  const [reissued, setReissued] = useState<InvitationIssuedFE | null>(null);
  if (!isAdmin) return <p className="p-6 text-[13px] text-muted-foreground" role="alert">Only company administrators can manage the team.</p>;
  const roles = meta.data?.roles ?? [];
  const pending = (invs.data ?? []).filter((i) => i.status === "pending" || i.status === "expired");
  return (
    <div className="mx-auto max-w-4xl space-y-6 p-4 sm:p-6">
      <header><h1 className="text-lg font-semibold">Team</h1><p className="text-[12px] text-muted-foreground">Invite colleagues and manage who can sign in to this company.</p></header>
      <section aria-label="Invite" className="space-y-2"><h2 className="label-xs">INVITE SOMEONE</h2>{roles.length > 0 && <InviteForm roles={roles} />}</section>
      {reissued && <IssuedLink issued={reissued} onDone={() => setReissued(null)} />}
      <section aria-label="Pending invitations" className="space-y-2">
        <h2 className="label-xs">PENDING INVITATIONS ({pending.length})</h2>
        {pending.length === 0 ? <p className="text-[12px] text-muted-foreground">No pending invitations.</p> : (
          <ul className="space-y-2">{pending.map((i) => (
            <li key={i.id} className="flex flex-wrap items-center gap-2 border border-border px-3 py-2 text-[12px]" data-testid="invitation-row">
              <div className="min-w-0 flex-1"><div className="truncate">{i.email} <span className="text-muted-foreground">as {i.role}</span></div><div className="text-muted-foreground">{i.status === "expired" ? "Expired" : "Expires"} {fmt(i.expires_at)} · invited by {i.invited_by_name}</div></div>
              <button type="button" disabled={invAct.isPending} className="inline-flex items-center gap-1 border border-border px-2 py-1 text-[11px] hover:bg-accent" onClick={() => invAct.mutate({ id: i.id, action: "resend" }, { onSuccess: (d) => setReissued(d as InvitationIssuedFE), onError: (e) => toast.error(e.message) })}><RefreshCw className="h-3 w-3" /> New link</button>
              <button type="button" disabled={invAct.isPending} className="inline-flex items-center gap-1 border border-border px-2 py-1 text-[11px] hover:bg-accent" onClick={() => invAct.mutate({ id: i.id, action: "resend", send_email: true }, { onSuccess: (d) => setReissued(d as InvitationIssuedFE), onError: (e) => toast.error(e.message) })}>Email new link</button>
              <button type="button" disabled={invAct.isPending} className="inline-flex items-center gap-1 border border-border px-2 py-1 text-[11px] text-destructive hover:bg-accent" onClick={() => invAct.mutate({ id: i.id, action: "revoke" }, { onSuccess: () => toast.success("Invitation revoked"), onError: (e) => toast.error(e.message) })}><Ban className="h-3 w-3" /> Revoke</button>
            </li>))}</ul>)}
      </section>
      <section aria-label="Members" className="space-y-2">
        <h2 className="label-xs">MEMBERS ({members.data?.length ?? 0})</h2>
        {members.isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <ul className="space-y-2">{(members.data ?? []).map((m) => <MemberRow key={m.id} m={m} me={m.id === user?.id} roles={roles} />)}</ul>}
      </section>
    </div>
  );
}
