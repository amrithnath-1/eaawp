// Domain types for EAAWP. UI depends on these, never on transport details.

export type AgentStatus =
  | "MONITORING"
  | "ANALYZING"
  | "EXECUTING"
  | "COMMUNICATING"
  | "WAITING_FOR_APPROVAL"
  | "SCHEDULED"
  | "IDLE"
  | "ERROR";

export type DepartmentKey =
  | "finance"
  | "sales"
  | "customer_service"
  | "hr"
  | "marketing"
  | "operations"
  | "it"
  | "design";

export interface Department {
  key: DepartmentKey;
  name: string;
  systems: string[];
  linkStrength: number; // 0..1 how active the AI link is
}

export interface Company {
  id: string;
  name: string;
  industry: string;
  region: string;
  employees: number;
  agentRole: string;
  agentName: string;
}

export type UserRole = "Company Admin" | "Manager" | "Employee" | "AI Administrator";

export interface SessionUser {
  id: string;
  name: string;
  email: string;
  role: UserRole;
  companyId: string;
  status: "Active" | "Away";
}

export interface ActivityEvent {
  id: string;
  time: string;
  text: string;
  kind: "detect" | "analyze" | "consult" | "result" | "await" | "execute";
  department?: DepartmentKey;
}

export type TaskStatus = "running" | "awaiting_approval" | "completed" | "blocked";

export interface TaskStep {
  label: string;
  detail: string;
  state: "done" | "active" | "pending";
}

export interface AgentTask {
  id: string;
  name: string;
  goal: string;
  status: TaskStatus;
  progress: number;
  startedAt: string;
  department: DepartmentKey;
  requiredAction?: string;
  steps: TaskStep[];
  sources: string[];
}

export interface Insight {
  id: string;
  severity: "critical" | "warning" | "info";
  title: string;
  detail: string;
  department: DepartmentKey;
  detectedAt: string;
  metric?: string;
}

export interface DepartmentExchange {
  id: string;
  from: "AI" | "DEPARTMENT";
  department: DepartmentKey;
  text: string;
  time: string;
}

export interface Schedule {
  id: string;
  task: string;
  frequency: string;
  nextRun: string;
  status: "active" | "paused";
  owner: string;
  department: DepartmentKey;
}

export interface LibraryItem {
  id: string;
  name: string;
  category:
    | "Documents"
    | "Reports"
    | "Policies"
    | "SOPs"
    | "Manuals"
    | "Communications"
    | "Datasets"
    | "Reference";
  size: string;
  updated: string;
  access: "All staff" | "Managers" | "Admins" | "AI only";
  indexed: boolean;
}

export interface KnowledgeStatus {
  documentsIndexed: number;
  knowledgeSources: number;
  lastSync: string;
  pendingUpdates: number;
}

export interface AuditEntry {
  id: string;
  time: string;
  event: string;
  actor: "AI" | "Manager" | "Company Admin" | "System" | "Employee";
  department?: DepartmentKey;
  status: "ok" | "pending" | "denied";
}

export interface RecentItem {
  id: string;
  label: string;
  type: "Task" | "Report" | "Document" | "Department" | "Insight";
  at: string;
}

export type AutonomyLevel = 1 | 2 | 3 | 4;

export interface AgentConfig {
  name: string;
  role: string;
  description: string;
  tone: "Formal" | "Concise" | "Consultative";
  capabilities: Record<string, boolean>;
  tools: Record<string, boolean>;
  permissions: { action: string; mode: "auto" | "approval" | "restricted" }[];
  autonomy: AutonomyLevel;
}

export interface RoleDefinition {
  name: string;
  system: boolean;
  users: number;
  permissions: Record<string, boolean>;
}

export interface MailMessage {
  id: string;
  from: "user" | "ai";
  text: string;
  time: string;
  attachments?: string[];
  delivery?: "auto" | "approval" | "restricted";
}
