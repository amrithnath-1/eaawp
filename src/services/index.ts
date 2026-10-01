/**
 * Service layer — the ONLY boundary the UI talks to.
 * Today it resolves mock data; later each function becomes an API/RPC call
 * (LLM → orchestrator → RAG → tools) without touching components.
 */
import * as mock from "./mockData";
import { USE_REAL_API } from "@/lib/api-client";
import type {
  ActivityEvent,
  AgentConfig,
  AgentTask,
  AuditEntry,
  Company,
  Department,
  DepartmentExchange,
  ExecutionTrace,
  Insight,
  KnowledgeStatus,
  LibraryItem,
  MailMessage,
  RecentItem,
  RoleDefinition,
  Schedule,
  SessionUser,
  UserRole,
} from "./types";

const latency = <T,>(value: T, ms = 120): Promise<T> =>
  new Promise((resolve) => setTimeout(() => resolve(value), ms));

export const authService = {
  async signIn(email: string, password: string, companyId?: string): Promise<SessionUser> {
    // Real API mode: call the JWT auth endpoint
    if (USE_REAL_API) {
      const { API_BASE_URL } = await import("@/lib/api-client");
      // Use companyId if provided, otherwise try to find from email or use a default
      const company_id = companyId || window.localStorage.getItem("eaawp.last_company_id") || "demo-company-001";
      const res = await fetch(`${API_BASE_URL}/api/v1/auth/token`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password, company_id }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Login failed" })) as { detail?: string };
        throw new Error(err.detail ?? "Invalid credentials");
      }
      const data = await res.json() as {
        access_token: string;
        refresh_token: string;
        tenant_id: string;
        user_id: string;
        user_name: string;
        role: string;
      };
      // Store tokens securely in localStorage
      window.localStorage.setItem("eaawp.access_token", data.access_token);
      window.localStorage.setItem("eaawp.refresh_token", data.refresh_token);
      window.localStorage.setItem("eaawp.last_company_id", data.tenant_id);
      return {
        id: data.user_id,
        name: data.user_name,
        email,
        role: data.role as UserRole,
        companyId: data.tenant_id,
        status: "Active",
      };
    }
    // Mock mode: accepts any credentials
    void password;
    return latency({
      ...mock.sessionUserSeed,
      email: email || mock.sessionUserSeed.email,
      companyId: "",
      role: "Company Admin" as UserRole,
    });
  },

  signOut() {
    window.localStorage.removeItem("eaawp.access_token");
    window.localStorage.removeItem("eaawp.refresh_token");
  },

  getAccessToken(): string | null {
    return window.localStorage.getItem("eaawp.access_token");
  },
};

export const companyService = {
  list: (): Promise<Company[]> => latency(mock.companies),
  get: (id: string) => {
    // Try mock companies first, then fall back to null
    return mock.companies.find((c) => c.id === id) ?? null;
  },
  departments: (): Department[] => mock.departments,
};

export const taskService = {
  list: (): AgentTask[] => mock.tasks,
  get: (id: string) => mock.tasks.find((t) => t.id === id),
};

export const activityService = {
  feed: (): ActivityEvent[] => mock.activityFeed,
  candidates: () => mock.streamCandidates,
};

export const insightService = {
  list: (): Insight[] => mock.insights,
};

export const departmentService = {
  exchanges: (): DepartmentExchange[] => mock.exchanges,
  forDepartment: (key: string) => mock.exchanges.filter((e) => e.department === key),
  liveScript: (): DepartmentExchange[] => mock.liveMeetingScript,
};

export const scheduleService = {
  list: (): Schedule[] => mock.schedules,
};

export const knowledgeService = {
  items: (): LibraryItem[] => mock.libraryItems,
  status: (): KnowledgeStatus => mock.knowledgeStatus,
};

export const auditService = {
  list: (): AuditEntry[] => mock.auditEntries,
  traces: () => mock.executionTraces,
};

export const recentService = {
  list: (): RecentItem[] => mock.recents,
};

export const agentConfigService = {
  get: (): AgentConfig => mock.agentConfig,
};

export const roleService = {
  list: (): RoleDefinition[] => mock.roleDefinitions,
};

export const mailService = {
  thread: (): MailMessage[] => mock.mailThread,
  send: async (text: string, attachments: string[] = []): Promise<MailMessage> =>
    latency({
      id: `m-${Date.now()}`,
      from: "user",
      text,
      attachments,
      time: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    }),
};

export { departmentName } from "./mockData";
