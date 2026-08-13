import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { companyService } from "@/services";
import { useSession } from "@/state/session";
import type { Company, UserRole } from "@/services/types";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/company")({
  head: () => ({
    meta: [
      { title: "Select company environment — EAAWP" },
      { name: "description", content: "Choose the company environment and your role inside the EAAWP agentic workspace." },
      { property: "og:title", content: "Select company environment — EAAWP" },
      { property: "og:description", content: "Choose the company environment and role for your AI workforce workspace." },
    ],
  }),
  component: CompanySelect,
});

const ROLES: UserRole[] = ["Company Admin", "Manager", "Employee", "AI Administrator"];

function CompanySelect() {
  const { user, hydrated, selectCompany, setRole } = useSession();
  const navigate = useNavigate();
  const [companies, setCompanies] = useState<Company[]>([]);
  const [picked, setPicked] = useState<string | null>(null);
  const [role, setLocalRole] = useState<UserRole>("Company Admin");

  useEffect(() => {
    void companyService.list().then(setCompanies);
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

  return (
    <div className="grid-canvas min-h-screen px-6 py-10">
      <div className="mx-auto max-w-4xl">
        <span className="font-mono text-xs tracking-[0.3em]">EAAWP</span>
        <h1 className="mt-6 text-2xl font-semibold tracking-tight">Select company environment</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          You will stay inside this environment. Switching requires an administrator action.
        </p>

        <div className="mt-6 border border-border">
          {companies.map((c) => (
            <button
              key={c.id}
              onClick={() => setPicked(c.id)}
              className={cn(
                "grid w-full grid-cols-1 items-center gap-1 border-b border-border px-4 py-3 text-left last:border-0 md:grid-cols-[1.3fr_1fr_1fr_auto]",
                picked === c.id ? "bg-surface-2" : "hover:bg-surface",
              )}
            >
              <div>
                <div className="text-sm font-semibold tracking-tight">{c.name}</div>
                <div className="label-xs mt-1">{c.industry}</div>
              </div>
              <div className="font-mono text-[11px] text-muted-foreground">{c.region}</div>
              <div className="font-mono text-[11px] text-muted-foreground">{c.employees} employees</div>
              <div className={cn("font-mono text-[10px] tracking-[0.12em]", picked === c.id ? "text-primary" : "text-muted-foreground")}>
                {c.agentRole.toUpperCase()}
              </div>
            </button>
          ))}
        </div>

        <h2 className="label-xs mt-8">Your role in this environment</h2>
        <div className="mt-2 flex flex-wrap gap-2">
          {ROLES.map((r) => (
            <button
              key={r}
              onClick={() => setLocalRole(r)}
              className={cn(
                "border px-3 py-1.5 font-mono text-[10px] tracking-[0.14em]",
                role === r ? "border-primary text-primary" : "border-border text-muted-foreground hover:text-foreground",
              )}
            >
              {r.toUpperCase()}
            </button>
          ))}
        </div>

        <button
          onClick={enter}
          disabled={!picked}
          className="mt-8 h-9 border border-primary bg-primary px-6 font-mono text-[11px] tracking-[0.18em] text-primary-foreground disabled:opacity-40"
        >
          ENTER WORKSPACE
        </button>
      </div>
    </div>
  );
}
