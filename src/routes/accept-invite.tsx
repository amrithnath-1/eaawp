import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { publicInviteCall } from "@/hooks/use-api";

export const Route = createFileRoute("/accept-invite")({
  component: AcceptInvitePage,
});

interface Looked { company_id: string; company_name: string; email: string; role: string }

function AcceptInvitePage() {
  const [token] = useState(() => new URLSearchParams(window.location.search).get("token") ?? "");
  const [info, setInfo] = useState<Looked | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<{ company_id: string; email: string } | null>(null);

  useEffect(() => {
    if (!token) { setProblem("This invitation link is incomplete."); return; }
    publicInviteCall<Looked>("lookup", { token }).then(setInfo).catch((e: Error) => setProblem(e.message));
  }, [token]);

  const mismatch = pw2.length > 0 && pw !== pw2;
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (pw !== pw2) return;
    setBusy(true); setProblem(null);
    try {
      const r = await publicInviteCall<{ company_id: string; email: string }>("accept", { token, name, password: pw });
      try { window.localStorage.setItem("eaawp.last_company_id", r.company_id); } catch { /* storage may be unavailable */ }
      setDone(r);
    } catch (er) { setProblem((er as Error).message); } finally { setBusy(false); }
  };

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center gap-4 px-4 py-10">
      <h1 className="text-lg font-semibold">Join your team</h1>
      {done ? (
        <div role="status" data-testid="invite-done" className="space-y-3 border border-success/40 bg-success/5 p-4 text-[13px]">
          <p>Your account is ready. Sign in with <strong>{done.email}</strong>. Your company ID is <code className="font-mono">{done.company_id}</code> (we filled it in for you).</p>
          <Link to="/" className="inline-block border border-border bg-primary px-3 py-1.5 text-[12px] text-primary-foreground">Go to sign in</Link>
        </div>
      ) : problem && !info ? (
        <p role="alert" data-testid="invite-problem" className="border border-destructive/50 bg-destructive/10 p-3 text-[13px]">{problem}<br /><span className="text-muted-foreground">Ask your administrator for a new invitation.</span></p>
      ) : !info ? <Loader2 className="h-5 w-5 animate-spin" /> : (
        <form onSubmit={submit} className="space-y-3 border border-border bg-surface p-4">
          <p className="text-[13px]">You have been invited to <strong>{info.company_name}</strong> as <strong>{info.role}</strong>.</p>
          <label className="block text-[11px]">Email<input readOnly value={info.email} className="mt-1 w-full border border-border bg-muted px-2 py-1.5 text-[13px]" /></label>
          <label className="block text-[11px]">Your name<input required value={name} onChange={(e) => setName(e.target.value)} maxLength={120} autoComplete="name" className="mt-1 w-full border border-border bg-background px-2 py-1.5 text-[13px]" /></label>
          <label className="block text-[11px]">Password (at least 8 characters)<input type="password" required minLength={8} maxLength={128} value={pw} onChange={(e) => setPw(e.target.value)} autoComplete="new-password" className="mt-1 w-full border border-border bg-background px-2 py-1.5 text-[13px]" /></label>
          <label className="block text-[11px]">Repeat password<input type="password" required value={pw2} onChange={(e) => setPw2(e.target.value)} autoComplete="new-password" className="mt-1 w-full border border-border bg-background px-2 py-1.5 text-[13px]" /></label>
          {mismatch && <p role="alert" className="text-[12px] text-destructive">Passwords do not match.</p>}
          {problem && <p role="alert" className="text-[12px] text-destructive">{problem}</p>}
          <button type="submit" disabled={busy || !name || pw.length < 8 || pw !== pw2} className="inline-flex items-center gap-2 border border-border bg-primary px-3 py-1.5 text-[12px] text-primary-foreground disabled:opacity-50">{busy && <Loader2 className="h-3 w-3 animate-spin" />} Create my account</button>
        </form>
      )}
    </main>
  );
}
