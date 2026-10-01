/**
 * AIWorkforcePanel — AI Workforce Roster
 *
 * Shows the DMM as the only active AI employee.
 * Future roles clearly show "Coming Soon" — no fake functionality.
 * Architecture is extensible for future roles and orchestrators.
 */
import { CheckCircle, Clock, Info, Lock } from "lucide-react";
import { cn } from "@/lib/utils";
import { AI_WORKFORCE_ROLES, useOnboardingStatus, type AIWorkforceRole } from "@/hooks/use-api";
import { USE_REAL_API } from "@/lib/api-client";

function RoleCard({ role, tenantId }: { role: AIWorkforceRole; tenantId?: string }) {
  const { data: status } = useOnboardingStatus(
    role.status === "active" && tenantId ? tenantId : null
  );

  const isActive = role.status === "active";
  const dmmReady = status?.has_ai_employee ?? false;

  return (
    <div className={cn(
      "border p-4 space-y-2",
      isActive ? "border-border bg-surface" : "border-border opacity-50 bg-surface",
    )}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-[16px]">{role.icon}</span>
            <h3 className="text-[13px] font-semibold">{role.display_name}</h3>
          </div>
          <p className="mt-1 text-[11px] text-muted-foreground">{role.description}</p>
        </div>
        <div className="shrink-0">
          {isActive ? (
            dmmReady ? (
              <span className="flex items-center gap-1 border border-success/40 bg-success/5 px-2 py-0.5 font-mono text-[9px] tracking-widest text-success">
                <CheckCircle className="size-3" strokeWidth={2} /> ACTIVE
              </span>
            ) : (
              <span className="flex items-center gap-1 border border-warning/40 px-2 py-0.5 font-mono text-[9px] tracking-widest text-warning">
                <Clock className="size-3" strokeWidth={2} /> CONFIGURING
              </span>
            )
          ) : (
            <span className="flex items-center gap-1 border border-border px-2 py-0.5 font-mono text-[9px] tracking-widest text-muted-foreground">
              <Lock className="size-3" strokeWidth={2} /> COMING SOON
            </span>
          )}
        </div>
      </div>

      {isActive && !USE_REAL_API && (
        <p className="font-mono text-[9px] tracking-widest text-muted-foreground/60">
          SIMULATION MODE
        </p>
      )}
      {isActive && USE_REAL_API && status && (
        <p className="font-mono text-[9px] tracking-widest text-muted-foreground">
          Status: {status.status.replace(/_/g, " ").toUpperCase()}
        </p>
      )}
    </div>
  );
}

export function AIWorkforcePanel({ tenantId }: { tenantId?: string }) {
  const activeRoles = AI_WORKFORCE_ROLES.filter(r => r.status === "active");
  const comingSoon = AI_WORKFORCE_ROLES.filter(r => r.status === "coming_soon");

  return (
    <div className="space-y-4">
      <div>
        <p className="label-xs mb-2 flex items-center gap-1">
          ACTIVE AI EMPLOYEES
        </p>
        <div className="space-y-2">
          {activeRoles.map(role => (
            <RoleCard key={role.role_key} role={role} {...(tenantId !== undefined ? { tenantId } : {})} />
          ))}
        </div>
      </div>

      <div>
        <p className="label-xs mb-2 flex items-center gap-1 opacity-50">
          FUTURE AI EMPLOYEES
        </p>
        <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
          {comingSoon.map(role => (
            <RoleCard key={role.role_key} role={role} {...(tenantId !== undefined ? { tenantId } : {})} />
          ))}
        </div>
      </div>

      <div className="flex gap-2 border border-border bg-surface-2 p-2 text-[11px] text-muted-foreground">
        <Info className="size-3.5 shrink-0 mt-0.5" strokeWidth={1.5} />
        <span>
          The EAAWP AI Workforce is extensible. Future AI employees and orchestrator agents
          will be added as they are implemented. Only the DMM is active in this release.
        </span>
      </div>
    </div>
  );
}
