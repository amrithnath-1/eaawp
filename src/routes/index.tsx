import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useState, useEffect } from "react";
import { authService } from "@/services";
import { useSession } from "@/state/session";
import { OnboardingFlow } from "@/components/eaawp/OnboardingFlow";

export const Route = createFileRoute("/")({
  component: LoginPage,
});

const USE_REAL_API = import.meta.env["VITE_USE_REAL_API"] === "true";

function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [companyId, setCompanyId] = useState(() => window.localStorage.getItem("eaawp.last_company_id") ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [registering, setRegistering] = useState(false);
  const { signIn, user, hydrated } = useSession();
  const navigate = useNavigate();

  // Clear any stale mock session when the login page loads in real mode
  useEffect(() => {
    if (USE_REAL_API) {
      // If there's a session but no real JWT token, it's a stale mock session — clear it
      const hasJwt = window.localStorage.getItem("eaawp.access_token");
      if (!hasJwt) {
        window.localStorage.removeItem("eaawp.session");
      }
    }
  }, []);

  // Already signed in: open the saved workspace (the shell sends people without one to role selection)
  useEffect(() => {
    if (hydrated && user?.companyId) {
      void navigate({ to: "/workspace", replace: true });
    }
  }, [hydrated, user, navigate]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const sessionUser = await authService.signIn(email, password, USE_REAL_API ? companyId : undefined);
      signIn(sessionUser);
      // If user already has a company (real auth), skip company selector
      if (sessionUser.companyId) {
        void navigate({ to: "/workspace", replace: true });
      } else {
        void navigate({ to: "/company", replace: true });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed — check your credentials.");
    } finally {
      setBusy(false);
    }
  }

  async function finishRegistration(newCompanyId: string, adminEmail: string, adminPassword: string) {
    setCompanyId(newCompanyId);
    setError(null);
    setBusy(true);
    try {
      const sessionUser = await authService.signIn(adminEmail, adminPassword, newCompanyId);
      signIn(sessionUser);
      // A new company admin always chooses an AI employee first.
      void navigate({ to: "/select-role", replace: true });
    } catch {
      setRegistering(false);
      setError(`Company created. Sign in with your registration email and password, using company ID ${newCompanyId}.`);
    } finally {
      setBusy(false);
    }
  }

  const field = "mt-1.5 h-9 w-full border border-input bg-surface px-2.5 text-sm outline-none focus:border-ring";

  return (
    <div className="min-h-screen w-full">
      <section className="flex min-h-screen w-full items-center justify-center p-6">
        {registering ? (
          <div className="w-full max-w-lg">
            <button type="button" onClick={() => setRegistering(false)} className="mb-3 font-mono text-[10px] text-muted-foreground hover:text-foreground">← BACK TO SIGN IN</button>
            <OnboardingFlow
              onComplete={(newCompanyId, _companyName, adminEmail, adminPassword) => { void finishRegistration(newCompanyId, adminEmail, adminPassword); }}
              onCancel={() => setRegistering(false)}
            />
            {error && <p className="mt-3 border border-border p-3 text-xs text-muted-foreground">{error}</p>}
          </div>
        ) : <form onSubmit={(e) => { e.preventDefault(); void submit(e); }} className="w-full max-w-sm">
          <div className="mb-8 flex items-center gap-2">
            <span className="grid size-6 place-items-center border border-border font-mono text-[10px]">E</span>
            <span className="font-mono text-xs tracking-[0.3em]">EAAWP</span>
          </div>

          <h2 className="text-xl font-semibold tracking-tight">Sign in</h2>
          <p className="mt-1 text-xs text-muted-foreground">
            {USE_REAL_API
              ? "Enter your registered company credentials."
              : "Demo mode — using local mock data."}
          </p>

          {/* Error banner */}
          {error && (
            <div className="mt-4 border border-destructive/40 bg-destructive/5 px-3 py-2 font-mono text-[11px] text-destructive">
              {error}
            </div>
          )}

          <label className="label-xs mt-6 block">Work email</label>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className={field}
            placeholder="admin@company.com"
            required
            autoComplete="email"
          />

          <label className="label-xs mt-4 block">Password</label>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className={field}
            placeholder="••••••••"
            required
            autoComplete="current-password"
          />

          {USE_REAL_API && (
            <>
              <label className="label-xs mt-4 block">Company ID</label>
              <input
                value={companyId}
                onChange={(e) => setCompanyId(e.target.value)}
                className={field + " font-mono text-[12px]"}
                placeholder="company ID from your welcome/setup details"
                required
                autoComplete="off"
                spellCheck={false}
              />
              <p className="mt-1 text-[10px] text-muted-foreground">Use the company ID from your EAAWP welcome/setup details. This field is prefilled on this device after registration.</p>
            </>
          )}

          <button
            type="submit"
            disabled={busy}
            className="mt-6 h-9 w-full border border-primary bg-primary font-mono text-[11px] tracking-[0.18em] text-primary-foreground hover:bg-primary/90 disabled:opacity-60"
          >
            {busy ? "AUTHENTICATING…" : "SIGN IN"}
          </button>

          {USE_REAL_API && (
            <p className="mt-4 text-center text-[11px] text-muted-foreground">
              New company?{" "}
              <button
                type="button"
                onClick={() => { setError(null); setRegistering(true); }}
                className="font-mono text-[10px] tracking-[0.1em] text-primary hover:underline"
              >
                REGISTER YOUR COMPANY
              </button>
            </p>
          )}
        </form>}
      </section>
    </div>
  );
}
