import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { Check, Lock, LogOut, ShieldCheck } from "lucide-react";
import { toast } from "sonner";
import { useSession, useWorkspaceGuard } from "@/state/session";
import { useSelectWorkspace, useWorkspace, type WorkspaceRoleKey } from "@/hooks/use-api";
import { apiErrorMessage } from "@/lib/api-client";
import { ROLE_META } from "@/lib/workspace";
import { cn } from "@/lib/utils";

const ROLE_KEYS: WorkspaceRoleKey[] = ["DIGITAL_MARKETING_MANAGER", "INSTITUTIONAL_CLERK", "MEDICAL_ASSISTANT", "DATA_INTELLIGENCE_ANALYST"];

export const Route = createFileRoute("/select-role")({
  validateSearch: (s: Record<string, unknown>): { role?: WorkspaceRoleKey } =>
    ROLE_KEYS.includes(s["role"] as WorkspaceRoleKey) ? { role: s["role"] as WorkspaceRoleKey } : {},
  component: SelectRolePage,
});

function SelectRolePage() {
  const { ready, user, company } = useWorkspaceGuard();
  const { signOut } = useSession();
  const search = Route.useSearch();
  const navigate = useNavigate();
  const workspace = useWorkspace(user?.id);
  const select = useSelectWorkspace(user?.id);
  const ws = workspace.data;
  const [choice, setChoice] = useState<WorkspaceRoleKey | null>(null);

  // Preselect the role a "switch to …" link asked for, else the current one.
  useEffect(() => {
    if (!ws || choice) return;
    const wanted = search.role ?? ws.selected?.role_key ?? null;
    if (wanted && ws.roles.find((r) => r.key === wanted)?.available) setChoice(wanted);
  }, [ws, search.role, choice]);

  if (!ready || !user || !company || workspace.isLoading) {
    return <div className="flex min-h-screen items-center justify-center"><span className="label-xs">Loading AI employees…</span></div>;
  }
  if (workspace.isError || !ws) {
    return (
      <div className="flex min-h-screen items-center justify-center p-6 text-[13px]">
        <div className="border border-border p-4">
          <p className="font-semibold">AI employees could not be loaded.</p>
          <p className="mt-1 text-muted-foreground">{apiErrorMessage(workspace.error)}</p>
          <button onClick={() => void workspace.refetch()} className="mt-3 font-mono text-[10px] tracking-[0.14em] text-primary">RETRY</button>
        </div>
      </div>
    );
  }

  const switching = !!ws.selected;
  const anyAvailable = ws.roles.some((r) => r.available);

  function proceed() {
    if (!choice) return;
    if (choice === ws?.selected?.role_key) { void navigate({ to: "/workspace" }); return; }
    select.mutate(choice, {
      onSuccess: (state) => {
        toast.success(`${state.selected?.name ?? "Workspace"} workspace is ready.`);
        void navigate({ to: "/workspace", replace: true });
      },
      onError: (err) => toast.error(apiErrorMessage(err)),
    });
  }

  return (
    <div className="min-h-screen bg-background">
      <header className="flex h-14 items-center gap-2 border-b border-border px-4">
        <span className="grid size-6 place-items-center border border-border font-mono text-[10px]">E</span>
        <span className="font-mono text-xs tracking-[0.3em]">EAAWP</span>
        <span className="ml-3 hidden truncate font-mono text-[10px] tracking-[0.14em] text-muted-foreground sm:inline">{company.name}</span>
        <button
          onClick={() => { signOut(); void navigate({ to: "/", replace: true }); }}
          className="ml-auto flex items-center gap-1 font-mono text-[10px] text-muted-foreground hover:text-foreground"
        >
          <LogOut className="size-3" /> SIGN OUT
        </button>
      </header>

      <main className="mx-auto max-w-5xl px-4 py-8">
        <p className="label-xs">{switching ? "Switch AI employee" : ws.notice ? "Workspace unavailable" : "Step 2 of 2 · Set up your workspace"}</p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight">
          {switching
            ? "Which AI employee do you want to work with?"
            : ws.notice
              ? "Choose another AI employee"
              : `Welcome, ${user.name.split(" ")[0]}. Choose your AI employee.`}
        </h1>
        <p className="mt-2 max-w-2xl text-[13px] text-muted-foreground">
          Your choice sets up your workspace: its pages, dashboard, tools, workflows and the knowledge the AI may use. You can switch later.
          Switching never deletes your data.
        </p>

        {ws.notice && <div data-testid="workspace-notice" className="mt-4 border border-warning/50 bg-warning/5 px-3 py-2 text-[12px]">{ws.notice}</div>}
        {!anyAvailable && (
          <div className="mt-4 border border-destructive/40 bg-destructive/5 px-3 py-2 text-[12px]">
            No AI employee is active for your company. A company administrator can activate one in the Marketplace.
          </div>
        )}

        <div role="radiogroup" aria-label="AI employees" className="mt-6 grid grid-cols-1 gap-3 md:grid-cols-2">
          {ws.roles.map((r) => {
            const meta = ROLE_META[r.key];
            const picked = choice === r.key;
            const current = ws.selected?.role_key === r.key;
            return (
              <button
                key={r.key}
                type="button"
                role="radio"
                aria-checked={picked}
                disabled={!r.available}
                data-testid={`role-card-${r.key}`}
                onClick={() => setChoice(r.key)}
                className={cn(
                  "flex flex-col border p-4 text-left transition-colors",
                  picked ? "border-foreground bg-surface ring-1 ring-foreground" : "border-border hover:border-border-strong",
                  !r.available && "cursor-not-allowed opacity-60 hover:border-border",
                )}
              >
                <div className="flex items-center gap-2">
                  <span className="grid size-8 place-items-center border border-border-strong"><meta.icon className="size-4" strokeWidth={1.5} /></span>
                  <div className="min-w-0">
                    <div className="text-[15px] font-semibold">{r.name}</div>
                    {current && <div className="font-mono text-[9px] tracking-[0.14em] text-primary">CURRENT WORKSPACE</div>}
                  </div>
                  <span className="ml-auto">
                    {!r.available ? <Lock className="size-4 text-muted-foreground" /> : picked ? <Check className="size-4" /> : null}
                  </span>
                </div>
                <p className="mt-2 text-[13px]">{r.purpose}</p>

                <div className="mt-3 label-xs">Capabilities</div>
                <ul className="mt-1 list-disc pl-4 text-[12px] text-muted-foreground">
                  {r.capabilities.map((c) => <li key={c}>{c}</li>)}
                </ul>

                <div className="mt-3 label-xs">Knowledge domain</div>
                <p className="mt-1 text-[12px] text-muted-foreground">{r.knowledge_domain}</p>

                <div className="mt-3 label-xs">Main tools</div>
                <div className="mt-1 flex flex-wrap gap-1">
                  {r.main_tools.slice(0, 7).map((t) => (
                    <span key={t.name} className="border border-border px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
                      {t.name}{t.requires_approval ? " · approval" : ""}
                    </span>
                  ))}
                  {r.main_tools.length > 7 && <span className="px-1 font-mono text-[10px] text-muted-foreground">+{r.main_tools.length - 7} more</span>}
                </div>

                {!r.available && r.unavailable_reason && (
                  <p data-testid={`role-unavailable-${r.key}`} className="mt-3 border-t border-border pt-2 text-[11px] text-muted-foreground">{r.unavailable_reason}</p>
                )}
              </button>
            );
          })}
        </div>

        <p className="mt-5 flex items-start gap-1.5 text-[11px] text-muted-foreground">
          <ShieldCheck className="mt-0.5 size-3.5 shrink-0" />
          Choosing a role gives the AI that role's instructions, knowledge scope, approved tools and safety rules from your company's configuration.
          It does not retrain the underlying language model, and it never grants access your account or company does not already have.
        </p>

        <div className="mt-6 flex items-center gap-3">
          <button
            data-testid="role-continue"
            onClick={proceed}
            disabled={!choice || select.isPending}
            className="h-9 border border-primary bg-primary px-5 font-mono text-[11px] tracking-[0.18em] text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            {select.isPending ? "SETTING UP…" : "CONTINUE"}
          </button>
          {switching && (
            <Link to="/workspace" className="font-mono text-[10px] tracking-[0.14em] text-muted-foreground hover:text-foreground">CANCEL</Link>
          )}
        </div>
      </main>
    </div>
  );
}
