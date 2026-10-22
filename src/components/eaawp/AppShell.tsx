import { useEffect, useState, type ReactNode } from "react";
import { Link, useNavigate, useRouterState } from "@tanstack/react-router";
import { NotificationBell } from "@/components/eaawp/NotificationBell";
import { ArrowLeftRight, LogOut, Mail, Menu, MoreHorizontal, ShieldAlert, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { useSession, useWorkspaceGuard } from "@/state/session";
import { useAgentStatus } from "@/state/useAgentStatus";
import { useUnreadMessages, useWorkspace, type WorkspaceStateFE } from "@/hooks/use-api";
import { apiErrorMessage } from "@/lib/api-client";
import { IS_ADMIN_ROLE, PAGE_OWNER, ROLE_META, navItems, pathAllowed } from "@/lib/workspace";
import { AmoebaButton } from "./AmoebaButton";
import { LetterBoxDrawer } from "./LetterBoxDrawer";

function Centered({ children }: { children: ReactNode }) {
  return <div className="flex min-h-screen items-center justify-center p-6">{children}</div>;
}

/** Shown instead of a page that is not part of the person's current workspace (e.g. opened by direct URL). */
function NotInWorkspace({ pathname, ws, isAdmin }: { pathname: string; ws: WorkspaceStateFE; isAdmin: boolean }) {
  const owner = PAGE_OWNER[pathname];
  const card = owner ? ws.roles.find((r) => r.key === owner) : undefined;
  return (
    <div data-testid="not-in-workspace" className="mx-auto max-w-lg p-6">
      <div className="border border-border bg-surface p-5">
        <div className="flex items-center gap-2 text-sm font-semibold">
          <ShieldAlert className="size-4 text-warning" /> Not part of your {ws.selected?.name} workspace
        </div>
        {card ? (
          card.available ? (
            <>
              <p className="mt-2 text-[13px] text-muted-foreground">This page belongs to the {card.name} AI employee. Switch to that workspace to use it. Your data in every workspace is kept.</p>
              <Link to="/select-role" search={{ role: card.key }} className="mt-4 inline-flex items-center gap-1.5 border border-primary bg-primary px-3 py-1.5 font-mono text-[10px] tracking-[0.14em] text-primary-foreground">
                <ArrowLeftRight className="size-3" /> SWITCH TO {card.name.toUpperCase()}
              </Link>
            </>
          ) : (
            <p className="mt-2 text-[13px] text-muted-foreground">{card.unavailable_reason}</p>
          )
        ) : (
          <p className="mt-2 text-[13px] text-muted-foreground">
            {isAdmin ? "This page is not available in this workspace." : "This page is for company administrators."}
          </p>
        )}
        <Link to="/workspace" className="mt-4 ml-2 inline-block font-mono text-[10px] tracking-[0.14em] text-muted-foreground hover:text-foreground">BACK TO DASHBOARD</Link>
      </div>
    </div>
  );
}

export function AppShell({ children, contentClassName }: { children: ReactNode; contentClassName?: string }) {
  const { ready, user, company } = useWorkspaceGuard();
  const { signOut } = useSession();
  const { status, label } = useAgentStatus();
  const unread = useUnreadMessages().data?.unread ?? 0;
  const workspace = useWorkspace(user?.id);
  const ws = workspace.data;
  const navigate = useNavigate();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const [drawer, setDrawer] = useState(false);
  const [mail, setMail] = useState(false);

  const mustSelect = !!ws?.needs_selection;
  useEffect(() => {
    if (mustSelect) void navigate({ to: "/select-role", replace: true });
  }, [mustSelect, navigate]);

  function doSignOut() {
    signOut();
    void navigate({ to: "/", replace: true });
  }

  if (!ready || !user || !company || workspace.isLoading || mustSelect) {
    return <Centered><span className="label-xs">Establishing workspace session…</span></Centered>;
  }
  if (workspace.isError || !ws || !ws.selected) {
    return (
      <Centered>
        <div className="max-w-sm border border-border p-4 text-[13px]">
          <p className="font-semibold">Your workspace could not be loaded.</p>
          <p className="mt-1 text-muted-foreground">{apiErrorMessage(workspace.error)}</p>
          <div className="mt-3 flex gap-3 font-mono text-[10px] tracking-[0.14em]">
            <button onClick={() => void workspace.refetch()} className="text-primary">RETRY</button>
            <button onClick={doSignOut} className="text-muted-foreground">SIGN OUT</button>
          </div>
        </div>
      </Centered>
    );
  }

  const role = ws.selected.role_key;
  const meta = ROLE_META[role];
  const isAdmin = IS_ADMIN_ROLE(user.role);
  const nav = navItems(ws.navigation, role);
  const allowed = pathAllowed(pathname, ws.navigation, isAdmin);

  const sidebar = (
    <nav className="flex h-full w-full flex-col bg-sidebar">
      <div className="flex h-14 items-center gap-2 border-b border-sidebar-border px-3">
        <span className="grid size-6 place-items-center border border-border-strong text-foreground">
          <meta.icon className="size-3.5" strokeWidth={1.5} />
        </span>
        <div className="min-w-0 leading-none">
          <div className="font-mono text-[11px] tracking-[0.22em] text-sidebar-foreground">EAAWP</div>
          <div data-testid="sidebar-role" className="mt-1 truncate text-[9px] tracking-[0.14em] text-muted-foreground">{ws.selected.name.toUpperCase()}</div>
        </div>
        <button className="ml-auto md:hidden" onClick={() => setDrawer(false)} aria-label="Close navigation">
          <X className="size-4 text-muted-foreground" />
        </button>
      </div>

      <ul data-testid="workspace-nav" className="flex-1 overflow-y-auto py-2">
        {nav.map((item) => {
          const active = pathname === item.to;
          return (
            <li key={item.to}>
              <Link
                to={item.to}
                data-nav={item.key}
                onClick={() => setDrawer(false)}
                className={cn(
                  "flex items-center gap-2.5 border-l-2 px-3 py-2 text-[13px] transition-colors",
                  active
                    ? "border-foreground bg-sidebar-accent text-sidebar-accent-foreground"
                    : "border-transparent text-sidebar-foreground hover:bg-sidebar-accent/60",
                )}
              >
                <item.icon className="size-3.5 shrink-0" strokeWidth={1.5} />
                {item.label}
                {item.key === "messages" && unread > 0 && <span data-testid="nav-unread" className="ml-auto bg-primary px-1.5 font-mono text-[10px] text-primary-foreground">{unread}</span>}
              </Link>
            </li>
          );
        })}
      </ul>

      {ws.can_switch && (
        <Link
          to="/select-role"
          data-testid="switch-role"
          onClick={() => setDrawer(false)}
          className="mx-3 mb-3 flex items-center justify-center gap-1.5 border border-border py-2 font-mono text-[10px] tracking-[0.14em] text-muted-foreground hover:border-border-strong hover:text-foreground"
        >
          <ArrowLeftRight className="size-3" /> SWITCH AI EMPLOYEE
        </Link>
      )}

      <div className="border-t border-sidebar-border p-3">
        <div className="flex items-center gap-2">
          <span className="grid size-8 shrink-0 place-items-center border border-border-strong font-mono text-[11px]">
            {user.name.split(" ").map((n) => n[0]).join("")}
          </span>
          <div className="min-w-0 leading-tight">
            <div className="truncate text-xs font-medium">{user.name}</div>
            <div className="truncate font-mono text-[10px] text-muted-foreground">{user.role}</div>
            <div className="truncate font-mono text-[10px] text-muted-foreground">{company.name}</div>
          </div>
        </div>
        <div className="mt-2 flex items-center justify-between">
          <span className="flex items-center gap-1.5 font-mono text-[10px] text-muted-foreground">
            <span className="inline-block size-1.5 rounded-full bg-foreground" /> {user.status.toUpperCase()}
          </span>
          <button
            className="flex items-center gap-1 font-mono text-[10px] text-muted-foreground hover:text-foreground"
            onClick={doSignOut}
          >
            <LogOut className="size-3" /> SIGN OUT
          </button>
        </div>
      </div>
    </nav>
  );

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      <aside className="hidden w-[204px] shrink-0 border-r border-sidebar-border md:block">{sidebar}</aside>

      {drawer && (
        <div className="fixed inset-0 z-50 md:hidden">
          <div className="absolute inset-0 bg-background/80" onClick={() => setDrawer(false)} />
          <div className="absolute inset-y-0 left-0 w-[240px] border-r border-sidebar-border">{sidebar}</div>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="grid h-14 shrink-0 grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 border-b border-border bg-surface px-3 md:px-4">
          <div className="flex items-center gap-2">
            <button className="-ml-1 grid size-10 place-items-center md:hidden" onClick={() => setDrawer(true)} aria-label="Open navigation">
              <Menu className="size-4" strokeWidth={1.5} />
            </button>
            <button
              onClick={() => setMail(true)}
              title="Open letter box"
              aria-label="Open letter box"
              className="grid size-8 place-items-center border border-border text-muted-foreground hover:border-border-strong hover:text-foreground"
            >
              <Mail className="size-4" strokeWidth={1.5} />
            </button>
          </div>

          <div className="min-w-0 md:pl-2">
            <div data-testid="header-role" className="truncate font-mono text-[12px] uppercase tracking-[0.18em] text-foreground">
              {ws.selected.name}
            </div>
            <div className="truncate font-mono text-[10px] tracking-[0.14em] text-muted-foreground">
              {company.name}
            </div>
          </div>

          <div className="flex items-center gap-2 md:gap-3">
            <span className="hidden font-mono text-[10px] tracking-[0.14em] text-muted-foreground lg:inline">
              {label.toUpperCase()}
            </span>
            {ws.can_switch && (
              <Link
                to="/select-role"
                aria-label="Switch AI employee"
                title="Switch AI employee"
                className="hidden items-center gap-1 border border-border px-2 py-1 font-mono text-[10px] tracking-[0.12em] text-muted-foreground hover:text-foreground sm:flex"
              >
                <ArrowLeftRight className="size-3" /> SWITCH
              </Link>
            )}
            <NotificationBell />
            <Link
              to="/settings"
              aria-label="Profile and settings"
              className="hidden size-7 place-items-center border border-border font-mono text-[10px] text-muted-foreground hover:text-foreground sm:grid"
            >
              {user.name.split(" ").map((n) => n[0]).join("")}
            </Link>
            <AmoebaButton status={status} size={44} className={cn(pathname === "/cabin" && "xl:hidden")} />
          </div>
        </header>

        {ws.selected.source === "migration_default" && (
          <div data-testid="default-workspace-notice" className="border-b border-border bg-surface px-4 py-1.5 text-[12px] text-muted-foreground">
            Your account was placed in the {ws.selected.name} workspace, the one EAAWP used before role selection existed.{" "}
            <Link to="/select-role" className="text-primary hover:underline">Choose a different AI employee</Link> any time, or keep this one.
          </div>
        )}

        <main className={cn("min-h-0 flex-1 overflow-y-auto pb-14 md:pb-0", contentClassName)}>
          {allowed ? children : <NotInWorkspace pathname={pathname} ws={ws} isAdmin={isAdmin} />}
        </main>

        <nav className="fixed inset-x-0 bottom-0 z-40 grid h-14 grid-cols-4 border-t border-border bg-surface md:hidden">
          {nav.slice(0, 3).map((item) => {
            const active = pathname === item.to;
            return (
              <Link
                key={item.to}
                to={item.to}
                className={cn(
                  "flex flex-col items-center justify-center gap-1 text-[10px]",
                  active ? "text-foreground" : "text-muted-foreground",
                )}
              >
                <item.icon className="size-4" strokeWidth={1.5} />
                <span className="max-w-full truncate px-1">{item.label}</span>
              </Link>
            );
          })}
          <button
            onClick={() => setDrawer(true)}
            className="flex flex-col items-center justify-center gap-1 text-[10px] text-muted-foreground"
          >
            <MoreHorizontal className="size-4" strokeWidth={1.5} />
            More
          </button>
        </nav>
      </div>

      <LetterBoxDrawer open={mail} onClose={() => setMail(false)} />
    </div>
  );
}
