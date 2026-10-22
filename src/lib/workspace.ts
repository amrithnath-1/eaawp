/**
 * Workspace navigation and role presentation.
 *
 * The SERVER decides which navigation entries a person gets (GET /api/v1/workspace -> `navigation`), from their
 * selected AI employee, their company's active modules and whether they are an administrator. This file only maps
 * those entry keys to routes, labels and icons. Hiding an entry is a convenience: every page's data is still
 * protected by its own server-side checks.
 */
import {
  BarChart3,
  BotMessageSquare,
  Cable,
  CalendarClock,
  CheckSquare,
  ClipboardList,
  Database,
  Home,
  LayoutGrid,
  Library,
  Megaphone,
  MessageSquare,
  Plug,
  ScrollText,
  Settings,
  SlidersHorizontal,
  Stethoscope,
  Store,
  UserPlus,
  Users,
  Workflow,
  Presentation,
  type LucideIcon,
} from "lucide-react";
import type { WorkspaceRoleKey } from "@/hooks/use-api";
import type { FileRoutesByTo } from "@/routeTree.gen";

export interface NavItem { key: string; to: keyof FileRoutesByTo; label: string; icon: LucideIcon }

const BASE: Record<string, Omit<NavItem, "key">> = {
  cabin: { to: "/cabin", label: "AI Employee", icon: Home },
  workspace: { to: "/workspace", label: "Dashboard", icon: LayoutGrid },
  customize: { to: "/customize", label: "Campaigns & Content", icon: SlidersHorizontal },
  integrations: { to: "/integrations", label: "Integrations", icon: Plug },
  scheduled: { to: "/scheduled", label: "Scheduled", icon: CalendarClock },
  meeting: { to: "/meeting", label: "Meeting Room", icon: Presentation },
  clerk: { to: "/clerk", label: "Service Requests", icon: ClipboardList },
  clinic: { to: "/clinic", label: "Clinic Desk", icon: Stethoscope },
  data: { to: "/data", label: "Datasets & Analysis", icon: Database },
  approvals: { to: "/approvals", label: "Approvals", icon: CheckSquare },
  messages: { to: "/messages", label: "Messages", icon: MessageSquare },
  library: { to: "/library", label: "Knowledge Library", icon: Library },
  workflows: { to: "/workflows", label: "Workflows", icon: Workflow },
  activity: { to: "/activity", label: "Activity", icon: BotMessageSquare },
  settings: { to: "/settings", label: "Settings", icon: Settings },
  team: { to: "/team", label: "Team", icon: UserPlus },
  employees: { to: "/employees", label: "AI Employees", icon: Users },
  marketplace: { to: "/marketplace", label: "Marketplace", icon: Store },
  connections: { to: "/connections", label: "Connections", icon: Cable },
  audit: { to: "/audit", label: "Audit", icon: ScrollText },
};

/** Role-specific wording for shared entries, so each workspace reads like its own application. */
const ROLE_LABELS: Partial<Record<WorkspaceRoleKey, Partial<Record<string, string>>>> = {
  DIGITAL_MARKETING_MANAGER: { workspace: "Marketing Dashboard", integrations: "Analytics & SEO", library: "Marketing Knowledge" },
  INSTITUTIONAL_CLERK: { workspace: "Clerk Dashboard", library: "Policies & Templates" },
  MEDICAL_ASSISTANT: { workspace: "Clinic Dashboard", library: "Clinic Information" },
  DATA_INTELLIGENCE_ANALYST: { workspace: "Analytics Dashboard", library: "Data Documentation" },
};

export function navItems(keys: string[], role: WorkspaceRoleKey | undefined): NavItem[] {
  const labels = role ? ROLE_LABELS[role] ?? {} : {};
  return keys.flatMap((key) => {
    const base = BASE[key];
    return base ? [{ key, ...base, label: labels[key] ?? base.label }] : [];
  });
}

/** Routes inside the shell that are never navigation entries but always reachable for a signed-in person. */
const ALWAYS_ALLOWED = new Set(["/recents", "/select-role"]);
/** Shell routes that belong to company administration (the API refuses non-admins anyway). */
const ADMIN_ONLY = new Set(["/roles"]);

/** The navigation key that owns a path, if any. */
export function navKeyForPath(pathname: string): string | null {
  const hit = Object.entries(BASE).find(([, v]) => v.to === pathname);
  return hit ? hit[0] : null;
}

/** Is this path part of the person's current workspace? */
export function pathAllowed(pathname: string, navigation: string[], isAdmin: boolean): boolean {
  if (ALWAYS_ALLOWED.has(pathname)) return true;
  if (ADMIN_ONLY.has(pathname)) return isAdmin;
  const key = navKeyForPath(pathname);
  return key === null ? true : navigation.includes(key);
}

/** Which workspace a role-specific page belongs to (used to offer the right switch). */
export const PAGE_OWNER: Partial<Record<string, WorkspaceRoleKey>> = {
  "/customize": "DIGITAL_MARKETING_MANAGER",
  "/integrations": "DIGITAL_MARKETING_MANAGER",
  "/meeting": "DIGITAL_MARKETING_MANAGER",
  "/clerk": "INSTITUTIONAL_CLERK",
  "/clinic": "MEDICAL_ASSISTANT",
  "/data": "DATA_INTELLIGENCE_ANALYST",
};

export interface RoleMeta { icon: LucideIcon; short: string; dashboardTitle: string; dashboardSubtitle: string }

export const ROLE_META: Record<WorkspaceRoleKey, RoleMeta> = {
  DIGITAL_MARKETING_MANAGER: {
    icon: Megaphone, short: "Marketing",
    dashboardTitle: "Marketing campaign & SEO workspace",
    dashboardSubtitle: "Campaign performance, SEO and analytics signals, content planning and reporting.",
  },
  INSTITUTIONAL_CLERK: {
    icon: ClipboardList, short: "Clerk",
    dashboardTitle: "Institutional records & service requests",
    dashboardSubtitle: "Request intake, document drafting and extraction, approvals and issued records.",
  },
  MEDICAL_ASSISTANT: {
    icon: Stethoscope, short: "Clinic",
    dashboardTitle: "Clinic administration",
    dashboardSubtitle: "Appointment requests, clinic information and intake. Administrative support only: no diagnosis or clinical decisions.",
  },
  DATA_INTELLIGENCE_ANALYST: {
    icon: BarChart3, short: "Analytics",
    dashboardTitle: "Data analysis workspace",
    dashboardSubtitle: "Datasets, database connections, deterministic analysis, charts and reports.",
  },
};

export const IS_ADMIN_ROLE = (role: string | undefined) =>
  ["admin", "superadmin", "company admin", "ai administrator"].includes((role ?? "").toLowerCase());
