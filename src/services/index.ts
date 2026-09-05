/**
 * Service layer — the ONLY boundary the UI talks to.
 * Today it resolves mock data; later each function becomes an API/RPC call
 * (LLM → orchestrator → RAG → tools) without touching components.
 */
import * as mock from "./mockData";
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
  async signIn(email: string, _password: string): Promise<SessionUser> {
    void _password;
    return latency({
      ...mock.sessionUserSeed,
      email: email || mock.sessionUserSeed.email,
      companyId: "",
      role: "Company Admin" as UserRole,
    });
  },
};

export const companyService = {
  list: (): Promise<Company[]> => latency(mock.companies),
  get: (id: string) => mock.companies.find((c) => c.id === id) ?? mock.companies[0],
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
