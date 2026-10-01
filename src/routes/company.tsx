import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { Plus } from "lucide-react";
import { companyService } from "@/services";
import { useSession } from "@/state/session";
import { USE_REAL_API } from "@/lib/api-client";
import type { Company, UserRole } from "@/services/types";
import { cn } from "@/lib/utils";
import { DataConnectionsPanel } from "@/components/eaawp/DataConnectionsPanel";
import { EmailIntegrationPanel } from "@/components/eaawp/EmailIntegrationPanel";
import { AIWorkforcePanel } from "@/components/eaawp/AIWorkforcePanel";
import { OnboardingFlow } from "@/components/eaawp/OnboardingFlow";
import { useRealCompanies, type RealCompanyFE } from "@/hooks/use-api";

export const Route = createFileRoute("/company")({
  component: CompanySelect,
});

const ROLES: UserRole[] = ["Company Admin", "Manager", "Employee", "AI Administrator"];

function CompanySelect() {
  const { user, hydrated, selectCompany, setRole } = useSession();
  const navigate = useNavigate();
  const [mockCompanies, setMockCompanies] = useState<Company[]>([]);
  const [picked, setPicked] = useState<string | null>(null);
  const [role, setLocalRole] = useState<UserRole>("Company Admin");
  const [showOnboarding, setShowOnboarding] = useState(false);
  const [tab, setTab] = useState<"select" | "workforce">("select");

  // Real companies from backend when in real mode
  const { data: realCompanies } = useRealCompanies();

  useEffect(() => {
    void companyService.list().then(setMockCompanies);
  }, []);

  useEffect(() => {
    if (hydrated && !user) navigate({ to: "/", replace: true });
  }, [hydrated, user, navigate]);

  function enter() {
    if (!picked) return;
    setRole(role);
    selectCompany(picked);
    navigate({ to: "/cabin", replace: true });
  }

  function handleOnboardComplete(companyId: string, _companyName: string) {
    setShowOnboarding(false);
    setPicked(companyId);
  }

  // Build combined company list: real backend + mock (demo) companies
  const displayCompanies: Array<{ id: string; name: string; industry: string; region: string; employees: number; agentRole: string; isReal: boolean }> = USE_REAL_API
    ? (realCompanies ?? []).map(c => ({
        id: c.id, name: c.name, industry: c.industry,
        region: c.region, employees: c.employees,
        agentRole: "Digital Marketing Manager", isReal: true,
      }))
    : mockCompanies.map(c => ({
        id: c.id, name: c.name, industry: c.industry,
        region: c.region, employees: c.employees,
        agentRole: c.agentRole, isReal: false,
      }));

  const isAdmin = role === "Company Admin" || role === "AI Administrator";

  return (
    <div className="grid-canvas min-h-screen px-6 py-10">
      <div className="mx-auto max-w-4xl">
        <span className="font-mono text-xs tracking-[0.3em]">EAAWP</span>
        <h1 className="mt-6 text-2xl font-semibold tracking-tight">Company environment</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Select your company or register a new one to access your AI workforce.
        </p>

        {/* Mode indicator */}
        <div className={cn(
          "mt-3 inline-flex items-center gap-1.5 border px-2.5 py-1 font-mono text-[9px] tracking-widest",
          USE_REAL_API
            ? "border-success/30 bg-success/5 text-success"
            : "border-warning/30 bg-warning/5 text-warning",
        )}>
          <span className={cn("size-1.5 rounded-full", USE_REAL_API ? "bg-success" : "bg-warning")} />
          {USE_REAL_API ? "LIVE MODE" : "SIMULATION MODE — external actions are simulated"}
        </div>

        {/* Tabs */}
        <div className="mt-6 flex gap-1.5">
          {(["select", "workforce"] as const).map(t => (
            <button key={t} onClick={() => setTab(t)}
              className={cn("border px-3 py-1.5 font-mono text-[10px] tracking-widest",
                tab === t ? "border-primary text-primary" : "border-border text-muted-foreground hover:text-foreground")}>
              {t === "select" ? "SELECT COMPANY" : "AI WORKFORCE"}
            </button>
          ))}
        </div>

        {tab === "select" && (
          <>
            {/* New company button */}
            {USE_REAL_API && (
              <div className="mt-4 flex items-center justify-between">
                <p className="text-[12px] text-muted-foreground">
                  {displayCompanies.length > 0 ? `${displayCompanies.length} company(ies) available` : "No companies yet"}
                </p>
                <button onClick={() => setShowOnboarding(s => !s)}
                  className="flex items-center gap-1.5 border border-primary px-3 py-1.5 font-mono text-[10px] tracking-widest text-primary hover:bg-primary/10">
                  <Plus className="size-3" strokeWidth={2.5} />
                  NEW COMPANY
                </button>
              </div>
            )}

            {/* Onboarding form */}
            {showOnboarding && (
              <div className="mt-4">
                <OnboardingFlow
                  onComplete={handleOnboardComplete}
                  onCancel={() => setShowOnboarding(false)}
                />
              </div>
            )}

            {/* Company list */}
            <div className="mt-4 border border-border">
              {displayCompanies.length === 0 && !showOnboarding && (
                <div className="p-6 text-center text-[13px] text-muted-foreground">
                  {USE_REAL_API
                    ? "No companies found. Click \"New Company\" to register your organisation."
                    : "Running in simulation mode. Using demo companies."}
                </div>
              )}
              {displayCompanies.map((c) => (
                <button
                  key={c.id}
                  onClick={() => setPicked(c.id)}
                  className={cn(
                    "grid w-full grid-cols-1 items-center gap-1 border-b border-border px-4 py-3 text-left last:border-0 md:grid-cols-[1.3fr_1fr_1fr_auto]",
                    picked === c.id ? "bg-surface-2" : "hover:bg-surface",
                  )}
                >
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-semibold tracking-tight">{c.name}</span>
                      {!c.isReal && (
                        <span className="border border-border px-1 font-mono text-[8px] text-muted-foreground tracking-widest">DEMO</span>
                      )}
                    </div>
                    <div className="label-xs mt-1">{c.industry}</div>
                  </div>
                  <div className="font-mono text-[11px] text-muted-foreground">{c.region}</div>
                  <div className="font-mono text-[11px] text-muted-foreground">{c.employees.toLocaleString()} employees</div>
                  <div className={cn("font-mono text-[10px] tracking-[0.12em]", picked === c.id ? "text-primary" : "text-muted-foreground")}>
                    {c.agentRole.toUpperCase()}
                  </div>
                </button>
              ))}
            </div>

            {/* Role selection */}
            <h2 className="label-xs mt-8">Your role in this environment</h2>
            <div className="mt-2 flex flex-wrap gap-2">
              {ROLES.map((r) => (
                <button key={r} onClick={() => setLocalRole(r)}
                  className={cn("border px-3 py-1.5 font-mono text-[10px] tracking-[0.14em]",
                    role === r ? "border-primary text-primary" : "border-border text-muted-foreground hover:text-foreground")}>
                  {r.toUpperCase()}
                </button>
              ))}
            </div>

            <button onClick={enter} disabled={!picked}
              className="mt-8 h-9 border border-primary bg-primary px-6 font-mono text-[11px] tracking-[0.18em] text-primary-foreground disabled:opacity-40">
              ENTER WORKSPACE
            </button>

            {/* Admin-only panels */}
            {isAdmin && picked && (
              <div className="mt-10 border-t border-border pt-8">
                <DataConnectionsPanel />
              </div>
            )}
            {isAdmin && picked && (
              <div className="mt-8 border-t border-border pt-8">
                <h2 className="mb-1 font-mono text-xs tracking-[0.2em] text-muted-foreground">EMAIL INTEGRATION</h2>
                <p className="mb-4 text-sm text-muted-foreground">
                  Configure SMTP for the Digital Marketing Manager to send emails after human approval.
                  Credentials are encrypted at rest and never exposed to the AI.
                </p>
                <EmailIntegrationPanel />
              </div>
            )}
          </>
        )}

        {tab === "workforce" && (
          <div className="mt-4">
            <AIWorkforcePanel {...(picked !== null ? { tenantId: picked } : {})} />
          </div>
        )}
      </div>
    </div>
  );
}
