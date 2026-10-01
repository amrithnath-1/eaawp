import { useState, type ReactNode } from "react";
import { Link, useNavigate, useRouterState } from "@tanstack/react-router";
import {
  Bell,
  BotMessageSquare,
  CalendarClock,
  CheckSquare,
  Clock3,
  Home,
  LayoutGrid,
  Library,
  LogOut,
  Mail,
  Menu,
  MoreHorizontal,
  Plug,
  ScrollText,
  Settings,
  ShieldCheck,
  SlidersHorizontal,
  Users,
  Workflow,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useSession, useWorkspaceGuard } from "@/state/session";
import { useAgentStatus } from "@/state/useAgentStatus";
import { AmoebaButton } from "./AmoebaButton";
import { LetterBoxDrawer } from "./LetterBoxDrawer";

const NAV = [
  { to: "/cabin",       label: "Cabin",       icon: Home },
  { to: "/workspace",   label: "Workspace",   icon: LayoutGrid },
  { to: "/integrations",label: "Integrations",icon: Plug },
  { to: "/employees",   label: "Employees",   icon: Users },
  { to: "/approvals",   label: "Approvals",   icon: CheckSquare },
  { to: "/workflows",   label: "Workflows",   icon: Workflow },
  { to: "/activity",    label: "Activity",    icon: BotMessageSquare },
  { to: "/scheduled",   label: "Scheduled",   icon: CalendarClock },
  { to: "/library",     label: "Library",     icon: Library },
  { to: "/customize",   label: "Customize",   icon: SlidersHorizontal },
  { to: "/audit",       label: "Audit",       icon: ScrollText },
  { to: "/settings",    label: "Settings",    icon: Settings },
] as const;

const MOBILE_NAV = [
  { to: "/cabin",       label: "Cabin",       icon: Home },
  { to: "/workspace",   label: "Workspace",   icon: LayoutGrid },
  { to: "/integrations",label: "Integrations",icon: Plug },
] as const;

export function AppShell({ children, contentClassName }: { children: ReactNode; contentClassName?: string }) {
  const { ready, user, company } = useWorkspaceGuard();
  const { signOut } = useSession();
  const { status, label } = useAgentStatus();
  const navigate = useNavigate();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const [drawer, setDrawer] = useState(false);
  const [mail, setMail] = useState(false);

  if (!ready || !user || !company) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <span className="label-xs">Establishing workspace session…</span>
      </div>
    );
  }

  const sidebar = (
    <nav className="flex h-full w-full flex-col bg-sidebar">
      <div className="flex h-14 items-center gap-2 border-b border-sidebar-border px-3">
        <span className="grid size-6 place-items-center border border-border-strong font-mono text-[10px] text-foreground">
          E
        </span>
        <div className="leading-none">
          <div className="font-mono text-[11px] tracking-[0.22em] text-sidebar-foreground">EAAWP</div>
          <div className="mt-1 text-[9px] tracking-[0.14em] text-muted-foreground">AGENTIC WORKFORCE</div>
        </div>
        <button className="ml-auto md:hidden" onClick={() => setDrawer(false)} aria-label="Close navigation">
          <X className="size-4 text-muted-foreground" />
        </button>
      </div>

      <ul className="flex-1 overflow-y-auto py-2">
        {NAV.map((item) => {
          const active = pathname === item.to;
          return (
            <li key={item.to}>
              <Link
                to={item.to}
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
              </Link>
            </li>
          );
        })}
      </ul>

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
            onClick={() => {
              signOut();
              navigate({ to: "/", replace: true });
            }}
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
            <button className="md:hidden" onClick={() => setDrawer(true)} aria-label="Open navigation">
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
            <div className="truncate font-mono text-[12px] uppercase tracking-[0.18em] text-foreground">
              {company.agentRole}
            </div>
            <div className="truncate font-mono text-[10px] tracking-[0.14em] text-muted-foreground">
              {company.name}
            </div>
          </div>

          <div className="flex items-center gap-2 md:gap-3">
            <span className="hidden font-mono text-[10px] tracking-[0.14em] text-muted-foreground lg:inline">
              {label.toUpperCase()}
            </span>
            <button className="relative hidden sm:block" aria-label="Notifications">
              <Bell className="size-4 text-muted-foreground hover:text-foreground" strokeWidth={1.5} />
              <span className="absolute -right-0.5 -top-0.5 size-1.5 rounded-full bg-foreground" />
            </button>
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

        <main className={cn("min-h-0 flex-1 overflow-y-auto pb-14 md:pb-0", contentClassName)}>{children}</main>

        <nav className="fixed inset-x-0 bottom-0 z-40 grid h-14 grid-cols-4 border-t border-border bg-surface md:hidden">
          {MOBILE_NAV.map((item) => {
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
                {item.label}
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
