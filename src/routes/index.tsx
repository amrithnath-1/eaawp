import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { authService } from "@/services";
import { useSession } from "@/state/session";

export const Route = createFileRoute("/")({
  component: LoginPage,
});

function LoginPage() {
  const [email, setEmail] = useState("elena.marsh@nexora.io");
  const [password, setPassword] = useState("demo1234");
  const [remember, setRemember] = useState(true);
  const [busy, setBusy] = useState(false);
  const { signIn } = useSession();
  const navigate = useNavigate();

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    const user = await authService.signIn(email, password);
    signIn(user);
    navigate({ to: "/company" });
  }

  return (
    <div className="min-h-screen w-full">
      <section className="flex min-h-screen w-full items-center justify-center p-6">
        <form onSubmit={submit} className="w-full max-w-sm">
          <div className="mb-8">
            <span className="font-mono text-xs tracking-[0.3em]">EAAWP</span>
          </div>

          <h2 className="text-xl font-semibold tracking-tight">Sign in</h2>
          <p className="mt-1 text-xs text-muted-foreground">Enterprise credentials · SSO enforced by your admin</p>

          <label className="label-xs mt-8 block">Work email</label>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="mt-1.5 h-9 w-full border border-input bg-surface px-2.5 text-sm outline-none focus:border-ring"
            required
          />

          <label className="label-xs mt-4 block">Password</label>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="mt-1.5 h-9 w-full border border-input bg-surface px-2.5 text-sm outline-none focus:border-ring"
            required
          />

          <div className="mt-3 flex items-center justify-between">
            <label className="flex items-center gap-2 font-mono text-[10px] tracking-[0.1em] text-muted-foreground">
              <input
                type="checkbox"
                checked={remember}
                onChange={(e) => setRemember(e.target.checked)}
                className="size-3 accent-[var(--color-primary)]"
              />
              REMEMBER ME
            </label>
            <button type="button" className="font-mono text-[10px] tracking-[0.1em] text-muted-foreground hover:text-foreground">
              FORGOT PASSWORD
            </button>
          </div>

          <button
            type="submit"
            disabled={busy}
            className="mt-6 h-9 w-full border border-primary bg-primary font-mono text-[11px] tracking-[0.18em] text-primary-foreground hover:bg-primary/90 disabled:opacity-60"
          >
            {busy ? "AUTHENTICATING…" : "SIGN IN"}
          </button>

          <p className="mt-6 border-t border-border pt-3 text-[11px] text-muted-foreground">
            Prototype build — authentication is simulated and any credentials are accepted.
          </p>
        </form>
      </section>
    </div>
  );
}
