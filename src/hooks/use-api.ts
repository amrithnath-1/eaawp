/**
 * EAAWP API Hooks
 *
 * TanStack Query hooks that call the real backend when VITE_USE_REAL_API=true,
 * or fall back to the mock service layer when it's false.
 *
 * This is the ONLY place in the frontend that decides real vs mock.
 * Components never check the flag themselves.
 */

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient, USE_REAL_API, API_BASE_URL } from "@/lib/api-client";

// ── Single shared API helper ───────────────────────────────────────────────────
// All domain-specific *Fetch helpers (intFetch, dataFetch, actionFetch, …) were
// identical switch statements delegating to apiClient. They are replaced by this
// single function. The old per-domain helpers are kept as thin aliases below
// their respective section headers for grep-ability, but they all call apiFetch.
async function apiFetch<T>(method: string, path: string, body?: unknown): Promise<T> {
  switch (method) {
    case "GET":    return apiClient.get<T>(path);
    case "POST":   return apiClient.post<T>(path, body ?? {});
    case "PATCH":  return apiClient.patch<T>(path, body);
    case "DELETE": return apiClient.delete<T>(path);
    default:       return apiClient.post<T>(path, body ?? {});
  }
}

import {
  activityService,
  taskService,
  insightService,
  knowledgeService,
  auditService,
  scheduleService,
  recentService,
  agentConfigService,
  mailService,
} from "@/services";
import type {
  ActivityEvent,
  AgentTask,
  Insight,
  LibraryItem,
  KnowledgeStatus,
  AuditEntry,
  ExecutionTrace,
  Schedule,
  RecentItem,
  AgentConfig,
  MailMessage,
} from "@/services/types";

// ── Query key factory ─────────────────────────────────────────────────────────

export const queryKeys = {
  activity: ["activity"] as const,
  tasks: ["tasks"] as const,
  task: (id: string) => ["tasks", id] as const,
  insights: ["insights"] as const,
  library: ["library"] as const,
  knowledgeStatus: ["knowledge-status"] as const,
  audit: ["audit"] as const,
  traces: ["audit", "traces"] as const,
  schedules: ["schedules"] as const,
  recents: ["recents"] as const,
  agentConfig: ["agent-config"] as const,
  mailThread: ["mail-thread"] as const,
  chatHistory: (sessionId: string) => ["chat", sessionId] as const,
};

// ── Activity ──────────────────────────────────────────────────────────────────

export function useActivityFeed() {
  return useQuery<ActivityEvent[]>({
    queryKey: queryKeys.activity,
    queryFn: () =>
      USE_REAL_API
        ? apiClient.get<ActivityEvent[]>("/api/v1/activity")
        : Promise.resolve(activityService.feed()),
    staleTime: 30_000,
  });
}

// ── Tasks ─────────────────────────────────────────────────────────────────────

export function useTasks() {
  return useQuery<AgentTask[]>({
    queryKey: queryKeys.tasks,
    queryFn: () =>
      USE_REAL_API
        ? apiClient.get<AgentTask[]>("/api/v1/tasks")
        : Promise.resolve(taskService.list()),
    staleTime: 15_000,
  });
}

// ── Insights ──────────────────────────────────────────────────────────────────

export function useInsights() {
  return useQuery<Insight[]>({
    queryKey: queryKeys.insights,
    queryFn: () =>
      USE_REAL_API
        ? apiClient.get<Insight[]>("/api/v1/insights")
        : Promise.resolve(insightService.list()),
    staleTime: 60_000,
  });
}

// ── Library ───────────────────────────────────────────────────────────────────

export function useLibraryItems() {
  return useQuery<LibraryItem[]>({
    queryKey: queryKeys.library,
    queryFn: () =>
      USE_REAL_API
        ? apiClient.get<LibraryItem[]>("/api/v1/knowledge/documents")
        : Promise.resolve(knowledgeService.items()),
    staleTime: 60_000,
  });
}

export function useKnowledgeStatus() {
  return useQuery<KnowledgeStatus>({
    queryKey: queryKeys.knowledgeStatus,
    queryFn: () =>
      USE_REAL_API
        ? apiClient.get<KnowledgeStatus>("/api/v1/knowledge/status")
        : Promise.resolve(knowledgeService.status()),
    staleTime: 30_000,
  });
}

// ── Audit ─────────────────────────────────────────────────────────────────────

export function useAuditLog() {
  return useQuery<AuditEntry[]>({
    queryKey: queryKeys.audit,
    queryFn: () =>
      USE_REAL_API
        ? apiClient.get<AuditEntry[]>("/api/v1/audit")
        : Promise.resolve(auditService.list()),
    staleTime: 15_000,
  });
}

export function useExecutionTraces() {
  return useQuery<ExecutionTrace[]>({
    queryKey: queryKeys.traces,
    queryFn: () =>
      USE_REAL_API
        ? apiClient.get<ExecutionTrace[]>("/api/v1/audit/traces")
        : Promise.resolve(auditService.traces()),
    staleTime: 30_000,
  });
}

// ── Schedules ─────────────────────────────────────────────────────────────────

export function useSchedules() {
  return useQuery<Schedule[]>({
    queryKey: queryKeys.schedules,
    queryFn: () =>
      USE_REAL_API
        ? apiClient.get<Schedule[]>("/api/v1/schedules")
        : Promise.resolve(scheduleService.list()),
    staleTime: 60_000,
  });
}

// ── Recents ───────────────────────────────────────────────────────────────────

export function useRecents() {
  return useQuery<RecentItem[]>({
    queryKey: queryKeys.recents,
    queryFn: () =>
      USE_REAL_API
        ? apiClient.get<RecentItem[]>("/api/v1/activity?limit=10")
            .then((items: unknown[]) =>
              (items as Array<{id: string; event_type?: string; summary?: string; created_at?: string}>).map((e) => ({
                id: e.id,
                label: e.summary ?? e.event_type ?? "Activity",
                type: e.event_type ?? "activity",
                time: e.created_at ?? new Date().toISOString(),
              })) as unknown as RecentItem[]
            )
        : Promise.resolve(recentService.list()),
    staleTime: 30_000,
  });
}

// ── Agent config ──────────────────────────────────────────────────────────────

export function useAgentConfig() {
  return useQuery<AgentConfig>({
    queryKey: queryKeys.agentConfig,
    queryFn: () =>
      USE_REAL_API
        ? apiClient.get<AgentConfig>("/api/v1/agent/config")
        : Promise.resolve(agentConfigService.get()),
    staleTime: 120_000,
  });
}

// ── Mail thread ───────────────────────────────────────────────────────────────

export function useMailThread() {
  return useQuery<MailMessage[]>({
    queryKey: queryKeys.mailThread,
    queryFn: () =>
      USE_REAL_API
        ? apiClient.get<MailMessage[]>("/api/v1/email/drafts")
            .catch(() => [] as MailMessage[])   // endpoint may return empty if no drafts
        : Promise.resolve(mailService.thread()),
    staleTime: 10_000,
  });
}

// ── Role Configuration ────────────────────────────────────────────────────────

export type ToolGovernanceApi = "enabled" | "requires_approval" | "disabled";

export interface RoleToolScope {
  name: string;
  tool_key: string;
  governance: ToolGovernanceApi;
  description: string;
}

export interface RoleWorkflow {
  id: string;
  name: string;
  description: string;
  trigger: string;
  enabled: boolean;
}

export interface RoleMonitoringRule {
  id: string;
  name: string;
  condition: string;
  action: string;
  enabled: boolean;
}

export interface RoleApprovalRule {
  action: string;
  mode: "auto" | "approval" | "restricted";
}

export interface RoleSchedulePreference {
  task: string;
  frequency: string;
  enabled: boolean;
}

export interface RoleMemorySettings {
  conversation_window: number;
  retain_tool_results: boolean;
  summarise_after_turns: number;
}

export interface RoleConfigFull {
  id: string;
  tenant_id: string;
  role_key: string;
  role_name: string;
  agent_name: string;
  description: string;
  responsibilities: string[];
  objectives: string[];
  instructions: string;
  system_persona: string;
  allowed_tools: string[];
  guarded_tools: string[];
  tool_scopes: RoleToolScope[];
  capabilities: Record<string, boolean>;
  permissions: RoleApprovalRule[];
  workflows: RoleWorkflow[];
  monitoring_rules: RoleMonitoringRule[];
  communication_style: string;
  schedule_preferences: RoleSchedulePreference[];
  memory_settings: RoleMemorySettings;
  llm_model: string;
  autonomy_level: number;
  quick_prompts: string[];
  updated_at: string;
}

export interface RoleConfigUpdate {
  role_name?: string;
  agent_name?: string;
  description?: string;
  responsibilities?: string[];
  objectives?: string[];
  instructions?: string;
  tool_scopes?: RoleToolScope[];
  capabilities?: Record<string, boolean>;
  permissions?: RoleApprovalRule[];
  workflows?: RoleWorkflow[];
  monitoring_rules?: RoleMonitoringRule[];
  communication_style?: string;
  schedule_preferences?: RoleSchedulePreference[];
  memory_settings?: RoleMemorySettings;
  llm_model?: string;
  autonomy_level?: number;
  quick_prompts?: string[];
}

export interface ActiveBlueprintResponse {
  role_key: string;
  agent_id: string;
  role_name: string;
  system_persona: string;
  allowed_tools: string[];
  guarded_tools: string[];
  tenant_id: string;
  llm_model: string;
}

/** Mock role config for Digital Marketing Manager — used when real API is off */
const MOCK_ROLE_CONFIG: RoleConfigFull = {
  id: "mock-dmm-config",
  tenant_id: "default-tenant",
  role_key: "DIGITAL_MARKETING_MANAGER",
  role_name: "Digital Marketing Manager",
  agent_name: "Marketing Intelligence Agent",
  description:
    "Monitors campaigns, surfaces content opportunities, and prepares marketing performance reports.",
  responsibilities: [
    "Monitor campaign performance across all channels",
    "Analyse audience engagement metrics",
    "Surface content opportunities and trends",
    "Prepare data-driven marketing reports",
    "Support A/B testing initiatives",
  ],
  objectives: [
    "Improve campaign ROI through continuous performance monitoring",
    "Reduce reporting time by automating data collection",
    "Identify underperforming channels before budget is wasted",
    "Surface actionable insights for the marketing team",
  ],
  instructions:
    "Always cite the data sources behind your insights. Never send external communications without explicit human approval. Keep responses concise and data-first.",
  system_persona:
    "You are the Marketing Intelligence Agent for this company. Your role is to support the Digital Marketing Manager by continuously monitoring campaign performance, analysing audience engagement metrics, surfacing content opportunities, and preparing data-driven marketing reports. You have access to campaign analytics, CRM contact data, content scheduling tools, and the company knowledge base. You operate under strict data governance: you never send external communications without explicit human approval, and you always cite the data sources behind your insights. Your communication style is concise and data-first. Every action you take is logged in the audit trail.",
  allowed_tools: ["query_campaign_analytics", "fetch_knowledge_base", "generate_report", "query_company_data", "create_internal_task"],
  guarded_tools: ["send_email"],
  tool_scopes: [
    { name: "Query Campaign Analytics", tool_key: "query_campaign_analytics", governance: "enabled", description: "Read-only access to campaign performance metrics" },
    { name: "Fetch Knowledge Base", tool_key: "fetch_knowledge_base", governance: "enabled", description: "Vector search across indexed marketing documents" },
    { name: "Generate Report", tool_key: "generate_report", governance: "enabled", description: "Produce structured marketing performance documents" },
    { name: "Query Company Data", tool_key: "query_company_data", governance: "enabled", description: "Read-only structured access to authorized company database entities via semantic mapping" },
    { name: "Create Internal Task", tool_key: "create_internal_task", governance: "enabled", description: "Create an internal EAAWP task record — low-risk, no external actions" },
    { name: "Send Email", tool_key: "send_email", governance: "requires_approval", description: "Send emails — always requires human approval" },
  ],
  capabilities: {
    "Campaign analytics": true,
    "Content generation": true,
    "Competitor research": true,
    "Email drafting": true,
    "Report writing": true,
    "Social media scheduling": true,
    "SEO analysis": true,
    "A/B test suggestions": true,
    "Budget tracking": false,
    "Direct ad spend": false,
  },
  permissions: [
    { action: "Read campaign analytics", mode: "auto" },
    { action: "Read knowledge base", mode: "auto" },
    { action: "Generate reports", mode: "auto" },
    { action: "Send email", mode: "approval" },
    { action: "Update CRM records", mode: "approval" },
    { action: "Access financial data", mode: "restricted" },
  ],
  workflows: [
    { id: "wf-weekly-report", name: "Weekly Performance Report", description: "Compile and present weekly campaign metrics", trigger: "scheduled", enabled: true },
    { id: "wf-anomaly-detect", name: "Campaign Anomaly Detection", description: "Alert when a campaign metric deviates significantly", trigger: "event", enabled: true },
  ],
  monitoring_rules: [
    { id: "mr-ctr-drop", name: "CTR Drop Alert", condition: "CTR drops more than 20% week-over-week", action: "Flag for review", enabled: true },
    { id: "mr-open-rate", name: "Email Open Rate Watch", condition: "Email open rate below 15%", action: "Notify manager", enabled: true },
  ],
  communication_style: "Concise",
  schedule_preferences: [
    { task: "Weekly Performance Report", frequency: "Every Monday 08:00", enabled: true },
    { task: "Monthly Summary", frequency: "1st of month 07:00", enabled: true },
  ],
  memory_settings: { conversation_window: 10, retain_tool_results: true, summarise_after_turns: 20 },
  llm_model: "gpt-4o-mini",
  autonomy_level: 3,
  quick_prompts: [
    "Analyse campaign performance this week",
    "What content is trending in our industry?",
    "Prepare monthly marketing report",
    "Which channels are underperforming?",
    "Suggest A/B test ideas for email",
    "Summarise social media engagement",
  ],
  updated_at: new Date().toISOString(),
};


/**
 * Fetch the full role configuration for a given role key.
 * When real API is on, calls GET /api/v1/roles/{role_key}.
 * Falls back to the mock config in mock mode.
 */
export function useRoleConfig(roleKey: string = "DIGITAL_MARKETING_MANAGER") {
  return useQuery<RoleConfigFull>({
    queryKey: ["role-config", roleKey] as const,
    queryFn: () =>
      USE_REAL_API
        ? apiClient.get<RoleConfigFull>(`/api/v1/roles/${roleKey}`, undefined)
        : Promise.resolve(MOCK_ROLE_CONFIG),
    staleTime: 60_000,
  });
}

/**
 * Mutation to partially update the role configuration.
 * PATCH /api/v1/roles/{role_key}
 */
export function useUpdateRoleConfig(roleKey: string = "DIGITAL_MARKETING_MANAGER") {
  const queryClient = useQueryClient();

  return useMutation<RoleConfigFull, Error, RoleConfigUpdate>({
    mutationFn: (update) => {
      if (USE_REAL_API) {
        return apiClient.patch<RoleConfigFull>(`/api/v1/roles/${roleKey}`, update);
      }
      // Mock: merge the update into the mock config
      return Promise.resolve({ ...MOCK_ROLE_CONFIG, ...update, updated_at: new Date().toISOString() });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["role-config", roleKey] });
    },
  });
}

/**
 * Fetch the AgentBlueprint that would be sent to DynamicAgentEngine
 * for the current role configuration. Used for preview/debugging.
 */
export function useActiveBlueprint(roleKey: string = "DIGITAL_MARKETING_MANAGER") {
  return useQuery<ActiveBlueprintResponse>({
    queryKey: ["role-blueprint", roleKey] as const,
    queryFn: () =>
      USE_REAL_API
        ? apiClient.get<ActiveBlueprintResponse>(`/api/v1/roles/${roleKey}/blueprint`)
        : Promise.resolve({
            role_key: MOCK_ROLE_CONFIG.role_key,
            agent_id: `default-tenant-${roleKey.toLowerCase()}`,
            role_name: MOCK_ROLE_CONFIG.role_name,
            system_persona: MOCK_ROLE_CONFIG.system_persona,
            allowed_tools: MOCK_ROLE_CONFIG.allowed_tools,
            guarded_tools: MOCK_ROLE_CONFIG.guarded_tools,
            tenant_id: "default-tenant",
            llm_model: MOCK_ROLE_CONFIG.llm_model,
          }),
    staleTime: 60_000,
  });
}

/**
 * Build an AgentBlueprint from a live RoleConfigFull.
 * This is the bridge between the Role Config layer and the execution engine.
 */
export function roleConfigToBlueprint(
  cfg: RoleConfigFull,
  tenantId: string = "default-tenant",
): AgentBlueprint {
  return {
    agent_id: `${tenantId}-${cfg.role_key.toLowerCase()}`,
    role_name: cfg.role_name,
    system_persona: cfg.system_persona,
    allowed_tools: cfg.allowed_tools,
    guarded_tools: cfg.guarded_tools,
    tenant_id: tenantId,
  };
}

// ── Natural-Language Configuration ───────────────────────────────────────────

export interface ProposedChangeLine {
  section: string;
  action: "add" | "remove" | "update";
  description: string;
}

export interface ConfigChangePatch {
  responsibilities_add: string[];
  responsibilities_remove: string[];
  objectives_add: string[];
  objectives_remove: string[];
  instructions_append: string;
  schedule_add: Array<{ task: string; frequency: string }>;
  schedule_remove: string[];
  monitoring_rules_add: Array<{ id: string; name: string; condition: string; action: string }>;
  monitoring_rules_remove: string[];
  quick_prompts_add: string[];
  quick_prompts_remove: string[];
  communication_style: string | null;
}

export interface ConfigProposal {
  id: string;
  role_key: string;
  tenant_id: string;
  original_instruction: string;
  interpreted_intent: string;
  proposed_changes: ProposedChangeLine[];
  patch: ConfigChangePatch;
  validation_errors: string[];
  validation_warnings: string[];
  approval_status: "pending" | "approved" | "rejected";
  created_at: string;
  approved_at: string | null;
  approved_by: string | null;
}


/**
 * Submit a natural-language configuration instruction.
 * Returns a proposal — does NOT change the configuration until approved.
 */
export function useNLConfigure(roleKey: string = "DIGITAL_MARKETING_MANAGER") {
  return useMutation<ConfigProposal, Error, { instruction: string; requested_by?: string }>({
    mutationFn: ({ instruction, requested_by = "admin" }) => {
      if (USE_REAL_API) {
        return apiClient.post<ConfigProposal>(
          `/api/v1/roles/${roleKey}/nl-configure`,
          { instruction, requested_by },
        );
      }
      // Mock path — simulate LLM interpretation
      return new Promise((resolve) =>
        setTimeout(() => {
          const mockPatch: ConfigChangePatch = {
            responsibilities_add: instruction.toLowerCase().includes("responsib")
              ? [instruction.replace(/^(add|include|monitor|ensure)\s*/i, "").trim()]
              : [],
            responsibilities_remove: [],
            objectives_add: [],
            objectives_remove: [],
            instructions_append: instruction.toLowerCase().includes("approv") || instruction.toLowerCase().includes("permission")
              ? instruction
              : "",
            schedule_add: instruction.toLowerCase().includes("monday") || instruction.toLowerCase().includes("weekly")
              ? [{ task: "Weekly analysis", frequency: "Every Monday 09:00" }]
              : [],
            schedule_remove: [],
            monitoring_rules_add: instruction.toLowerCase().includes("monitor") || instruction.toLowerCase().includes("alert") || instruction.toLowerCase().includes("drop")
              ? [{ id: `mr-${Date.now()}`, name: "Custom Alert", condition: instruction.slice(0, 80), action: "Notify admin" }]
              : [],
            monitoring_rules_remove: [],
            quick_prompts_add: instruction.toLowerCase().includes("focus") || instruction.toLowerCase().includes("prompt")
              ? [instruction.slice(0, 60)]
              : [],
            quick_prompts_remove: [],
            communication_style: null,
          };

          const changes: ProposedChangeLine[] = [];
          if (mockPatch.responsibilities_add.length)
            changes.push({ section: "Responsibilities", action: "add", description: `+ ${mockPatch.responsibilities_add[0]}` });
          if (mockPatch.schedule_add.length)
            changes.push({ section: "Schedule", action: "add", description: `+ ${mockPatch.schedule_add[0]!.task} — ${mockPatch.schedule_add[0]!.frequency}` });
          if (mockPatch.monitoring_rules_add.length)
            changes.push({ section: "Monitoring Rules", action: "add", description: `+ ${mockPatch.monitoring_rules_add[0]!.name}: ${mockPatch.monitoring_rules_add[0]!.condition}` });
          if (mockPatch.instructions_append)
            changes.push({ section: "Instructions", action: "add", description: `Append: "${mockPatch.instructions_append.slice(0, 80)}"` });
          if (mockPatch.quick_prompts_add.length)
            changes.push({ section: "Quick Prompts", action: "add", description: `+ "${mockPatch.quick_prompts_add[0]}"` });

          resolve({
            id: `mock-${Date.now()}`,
            role_key: roleKey,
            tenant_id: "default-tenant",
            original_instruction: instruction,
            interpreted_intent: `[MOCK] Interpreted as: ${instruction.slice(0, 100)}`,
            proposed_changes: changes.length > 0 ? changes : [
              { section: "Instructions", action: "add", description: `Append: "${instruction.slice(0, 80)}"` }
            ],
            patch: changes.length > 0 ? mockPatch : { ...mockPatch, instructions_append: instruction },
            validation_errors: [],
            validation_warnings: changes.length === 0 ? ["No specific configuration changes detected — appending to instructions."] : [],
            approval_status: "pending",
            created_at: new Date().toISOString(),
            approved_at: null,
            approved_by: null,
          } satisfies ConfigProposal);
        }, 1200),
      );
    },
  });
}

/**
 * Approve a pending configuration proposal.
 * Applies the patch to the role configuration.
 */
export function useApproveProposal(roleKey: string = "DIGITAL_MARKETING_MANAGER") {
  const queryClient = useQueryClient();

  return useMutation<ConfigProposal, Error, { proposalId: string; reviewed_by?: string }>({
    mutationFn: ({ proposalId, reviewed_by = "admin" }) => {
      if (USE_REAL_API) {
        return apiClient.post<ConfigProposal>(
          `/api/v1/roles/${roleKey}/proposals/${proposalId}/approve`,
          { reviewed_by },
        );
      }
      // Mock: just return the proposal as approved
      return Promise.resolve({
        id: proposalId,
        role_key: roleKey,
        tenant_id: "default-tenant",
        original_instruction: "",
        interpreted_intent: "",
        proposed_changes: [],
        patch: { responsibilities_add: [], responsibilities_remove: [], objectives_add: [], objectives_remove: [], instructions_append: "", schedule_add: [], schedule_remove: [], monitoring_rules_add: [], monitoring_rules_remove: [], quick_prompts_add: [], quick_prompts_remove: [], communication_style: null },
        validation_errors: [],
        validation_warnings: [],
        approval_status: "approved",
        created_at: new Date().toISOString(),
        approved_at: new Date().toISOString(),
        approved_by: reviewed_by,
      } satisfies ConfigProposal);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["role-config", roleKey] });
      void queryClient.invalidateQueries({ queryKey: ["role-blueprint", roleKey] });
    },
  });
}

/**
 * Reject a pending configuration proposal.
 * Configuration is left unchanged.
 */
export function useRejectProposal(roleKey: string = "DIGITAL_MARKETING_MANAGER") {
  return useMutation<ConfigProposal, Error, { proposalId: string; reviewed_by?: string }>({
    mutationFn: ({ proposalId, reviewed_by = "admin" }) => {
      if (USE_REAL_API) {
        return apiClient.post<ConfigProposal>(
          `/api/v1/roles/${roleKey}/proposals/${proposalId}/reject`,
          { reviewed_by },
        );
      }
      return Promise.resolve({
        id: proposalId, role_key: roleKey, tenant_id: "default-tenant",
        original_instruction: "", interpreted_intent: "", proposed_changes: [],
        patch: { responsibilities_add: [], responsibilities_remove: [], objectives_add: [], objectives_remove: [], instructions_append: "", schedule_add: [], schedule_remove: [], monitoring_rules_add: [], monitoring_rules_remove: [], quick_prompts_add: [], quick_prompts_remove: [], communication_style: null },
        validation_errors: [], validation_warnings: [],
        approval_status: "rejected",
        created_at: new Date().toISOString(),
        approved_at: new Date().toISOString(),
        approved_by: reviewed_by,
      } satisfies ConfigProposal);
    },
  });
}

// ── Knowledge Base / Library ──────────────────────────────────────────────────

export type DocumentStatus = "uploading" | "processing" | "indexed" | "failed";

export interface KnowledgeDocument {
  id: string;
  tenant_id: string;
  name: string;
  doc_type: string;
  size_bytes: number;
  access_level: string;
  role_scope: string;
  status: DocumentStatus;
  error_message: string | null;
  chunk_count: number;
  uploaded_by: string;
  uploaded_at: string;
  indexed_at: string | null;
}

export interface KnowledgeStatusReal {
  documents_indexed: number;
  documents_total: number;
  documents_failed: number;
  documents_processing: number;
  last_indexed_at: string | null;
}

export interface RetrievedChunk {
  chunk_id: string;
  document_id: string;
  document_name: string;
  doc_type: string;
  role_scope: string;
  text: string;
  score: number;
}

export interface RetrievalResponse {
  query: string;
  chunks: RetrievedChunk[];
  total_found: number;
}


/** List all knowledge documents for the tenant. */
export function useKnowledgeDocuments() {
  return useQuery<KnowledgeDocument[]>({
    queryKey: ["knowledge-documents"] as const,
    queryFn: () =>
      USE_REAL_API
        ? apiClient.get<KnowledgeDocument[]>("/api/v1/knowledge/documents")
        : Promise.resolve([]),
    staleTime: 10_000,
    refetchInterval: (query) => {
      // Auto-refresh while any document is processing
      const data = query.state.data;
      if (!Array.isArray(data)) return false;
      const processing = data.some(
        (d) => d.status === "uploading" || d.status === "processing",
      );
      return processing ? 3000 : false;
    },
  });
}

/** Get aggregate knowledge status. */
export function useKnowledgeStatusReal() {
  return useQuery<KnowledgeStatusReal>({
    queryKey: ["knowledge-status-real"] as const,
    queryFn: () =>
      USE_REAL_API
        ? apiClient.get<KnowledgeStatusReal>("/api/v1/knowledge/status")
        : Promise.resolve({
            documents_indexed: 0,
            documents_total: 0,
            documents_failed: 0,
            documents_processing: 0,
            last_indexed_at: null,
          }),
    staleTime: 15_000,
  });
}

/** Upload a document. */
export function useUploadDocument() {
  const queryClient = useQueryClient();
  return useMutation<KnowledgeDocument, Error, FormData>({
    mutationFn: (formData) => {
      if (!USE_REAL_API) {
        return Promise.reject(new Error("Upload requires real API mode."));
      }
      // Multipart upload — cannot use apiClient (it forces application/json Content-Type).
      // Inject Authorization manually; do NOT set Content-Type so the browser sets the multipart boundary.
      const accessToken = typeof window !== "undefined"
        ? window.localStorage.getItem("eaawp.access_token")
        : null;
      const headers: Record<string, string> = {};
      if (accessToken) headers["Authorization"] = `Bearer ${accessToken}`;
      return fetch(`${API_BASE_URL}/api/v1/knowledge/upload`, {
        method: "POST",
        headers,
        body: formData,
      }).then(async (res) => {
        if (!res.ok) {
          const body = await res.json().catch(() => ({ detail: res.statusText }));
          throw new Error(
            typeof body === "object" && body !== null && "detail" in body
              ? String((body as Record<string, unknown>)["detail"])
              : res.statusText,
          );
        }
        return res.json() as Promise<KnowledgeDocument>;
      });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["knowledge-documents"] });
      void queryClient.invalidateQueries({ queryKey: ["knowledge-status-real"] });
    },
  });
}

/** Delete a document. */
export function useDeleteDocument() {
  const queryClient = useQueryClient();
  return useMutation<void, Error, string>({
    mutationFn: (docId) => {
      if (!USE_REAL_API) return Promise.resolve();
      return apiClient.delete<void>(`/api/v1/knowledge/documents/${docId}`);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["knowledge-documents"] });
      void queryClient.invalidateQueries({ queryKey: ["knowledge-status-real"] });
    },
  });
}

// ── Chat / agent execute ──────────────────────────────────────────────────────

export interface AgentBlueprint {
  agent_id: string;
  role_name: string;
  system_persona: string;
  allowed_tools: string[];
  guarded_tools: string[];
  tenant_id: string;
}

export interface AgentExecutionRequest {
  blueprint: AgentBlueprint;
  user_prompt: string;
  session_id?: string;
}

export interface AgentExecutionResponse {
  message: string;
  tool_calls?: Array<{ name: string; args: Record<string, unknown> }>;
  sources?: string[];
  requires_approval?: boolean;
  session_id: string;
  plan_id?: string | null;
  plan_status?: string | null;
  step_summaries?: string[];
  /** Set when the request is saved waiting for an integration to be set up. */
  pending_task_id?: string | null;
}

/**
 * Default blueprint for the Digital Marketing Manager role.
 * Used when callers don't provide a custom blueprint.
 */
export const DEFAULT_BLUEPRINT: AgentBlueprint = {
  agent_id: "marketing-intelligence-agent",
  role_name: "Digital Marketing Manager",
  system_persona:
    "You are the Marketing Intelligence Agent for this company. Your role is to support the Digital Marketing Manager by continuously monitoring campaign performance, analysing audience engagement metrics, surfacing content opportunities, and preparing data-driven marketing reports. You have access to campaign analytics, CRM contact data, content scheduling tools, the company knowledge base, and authorized company database access via semantic mappings. You operate under strict data governance: you never send external communications without explicit human approval, and you always cite the data sources behind your insights. Your communication style is concise and data-first. Every action you take is logged in the audit trail.",
  allowed_tools: ["query_campaign_analytics", "fetch_knowledge_base", "generate_report", "query_company_data", "create_internal_task"],
  guarded_tools: ["send_email"],
  tenant_id: "default-tenant",
};

/**
 * Mutation for sending a prompt to the agent.
 * Requires a full AgentExecutionRequest (including blueprint) so the backend
 * can enforce tool scoping. When VITE_USE_REAL_API=false, resolves with a
 * clearly-labelled mock response so the UI doesn't silently fake real AI.
 */
export function useAgentExecute() {
  const queryClient = useQueryClient();

  return useMutation<AgentExecutionResponse, Error, AgentExecutionRequest>({
    mutationFn: (req) => {
      if (USE_REAL_API) {
        return apiClient.post<AgentExecutionResponse>("/api/v1/agent/execute", req);
      }
      // Mock path — clearly labelled, never pretends to be real AI
      return new Promise((resolve) =>
        setTimeout(
          () =>
            resolve({
              message:
                `[MOCK — backend not connected] Received prompt: "${req.user_prompt}". ` +
                `In production this calls the FastAPI backend at ${import.meta.env["VITE_API_BASE_URL"] ?? "http://localhost:8000"}/api/v1/agent/execute. ` +
                `Connect the backend and set VITE_USE_REAL_API=true to enable real AI responses.`,
              sources: [],
              requires_approval: false,
              session_id: req.session_id ?? `mock-${Date.now()}`,
            }),
          800,
        ),
      );
    },
    onSuccess: () => {
      // Invalidate activity and tasks after an agent execution
      void queryClient.invalidateQueries({ queryKey: queryKeys.activity });
      void queryClient.invalidateQueries({ queryKey: queryKeys.tasks });
    },
  });
}

// ── Company Data Integrations ─────────────────────────────────────────────────

export type ConnectionStatus = "not_tested" | "testing" | "connected" | "failed";

export interface ColumnMetaFE {
  name: string;
  data_type: string;
  is_nullable: boolean;
  is_primary_key: boolean;
}

export interface SchemaEntityFE {
  id: string;
  connection_id: string;
  schema_name: string;
  entity_name: string;
  entity_type: string;
  columns: ColumnMetaFE[];
  row_count_estimate: number | null;
  is_allowed: boolean;
  discovered_at: string;
}

export interface DataConnectionFE {
  id: string;
  tenant_id: string;
  display_name: string;
  db_type: string;
  host: string;
  port: number;
  database_name: string;
  username: string;
  ssl_required: boolean;
  status: ConnectionStatus;
  last_tested_at: string | null;
  error_message: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
  entity_count: number;
  allowed_entity_count: number;
}

export interface DataConnectionCreate {
  display_name: string;
  db_type: string;
  host: string;
  port: number;
  database_name: string;
  username: string;
  password: string;
  ssl_required: boolean;
  created_by?: string;
}

export interface ConnectionTestResponse {
  connection_id: string;
  success: boolean;
  status: ConnectionStatus;
  server_version: string | null;
  error_message: string | null;
}


async function intFetch<T>(method: string, path: string, body?: unknown): Promise<T> {
  return apiFetch<T>(method, path, body);
}

/** List all data connections for this tenant. */
export function useDataConnections() {
  return useQuery<DataConnectionFE[]>({
    queryKey: ["data-connections"] as const,
    queryFn: () =>
      USE_REAL_API
        ? intFetch<DataConnectionFE[]>("GET", "/api/v1/integrations/connections")
        : Promise.resolve([]),
    staleTime: 15_000,
  });
}

/** Create a new data connection. Password is sent once and encrypted server-side. */
export function useCreateConnection() {
  const queryClient = useQueryClient();
  return useMutation<DataConnectionFE, Error, DataConnectionCreate>({
    mutationFn: (body) => {
      if (!USE_REAL_API) return Promise.reject(new Error("Requires real API mode."));
      return intFetch<DataConnectionFE>("POST", "/api/v1/integrations/connections", body);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["data-connections"] });
    },
  });
}

/** Delete a connection and all its schema entities. */
export function useDeleteConnection() {
  const queryClient = useQueryClient();
  return useMutation<void, Error, string>({
    mutationFn: (connId) => {
      if (!USE_REAL_API) return Promise.resolve();
      return intFetch<void>("DELETE", `/api/v1/integrations/connections/${connId}`);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["data-connections"] });
    },
  });
}

/** Test a connection — returns real status from the external DB. */
export function useTestConnection() {
  const queryClient = useQueryClient();
  return useMutation<ConnectionTestResponse, Error, string>({
    mutationFn: (connId) => {
      if (!USE_REAL_API) return Promise.reject(new Error("Requires real API mode."));
      return intFetch<ConnectionTestResponse>(
        "POST",
        `/api/v1/integrations/connections/${connId}/test`,
      );
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["data-connections"] });
    },
  });
}

/** Discover schema for a connection — returns discovered entities. */
export function useDiscoverSchema() {
  const queryClient = useQueryClient();
  return useMutation<SchemaEntityFE[], Error, string>({
    mutationFn: (connId) => {
      if (!USE_REAL_API) return Promise.reject(new Error("Requires real API mode."));
      return intFetch<SchemaEntityFE[]>(
        "POST",
        `/api/v1/integrations/connections/${connId}/discover`,
      );
    },
    onSuccess: (_data, connId) => {
      void queryClient.invalidateQueries({ queryKey: ["schema-entities", connId] });
      void queryClient.invalidateQueries({ queryKey: ["data-connections"] });
    },
  });
}

/** List schema entities for a connection. */
export function useSchemaEntities(connId: string | null) {
  return useQuery<SchemaEntityFE[]>({
    queryKey: ["schema-entities", connId] as const,
    queryFn: () => {
      if (!connId) return Promise.resolve([]);
      if (!USE_REAL_API) return Promise.resolve([]);
      return intFetch<SchemaEntityFE[]>(
        "GET",
        `/api/v1/integrations/connections/${connId}/entities`,
      );
    },
    enabled: !!connId,
    staleTime: 30_000,
  });
}

/** Set allowed flag on a single entity. */
export function useSetEntityPermission() {
  const queryClient = useQueryClient();
  return useMutation<
    SchemaEntityFE,
    Error,
    { entityId: string; connId: string; is_allowed: boolean }
  >({
    mutationFn: ({ entityId, is_allowed }) => {
      if (!USE_REAL_API) return Promise.reject(new Error("Requires real API mode."));
      return intFetch<SchemaEntityFE>(
        "PATCH",
        `/api/v1/integrations/entities/${entityId}/permission`,
        { is_allowed },
      );
    },
    onSuccess: (_data, { connId }) => {
      void queryClient.invalidateQueries({ queryKey: ["schema-entities", connId] });
      void queryClient.invalidateQueries({ queryKey: ["data-connections"] });
    },
  });
}

/** Bulk set permissions for multiple entities. */
export function useBulkEntityPermission() {
  const queryClient = useQueryClient();
  return useMutation<
    { updated: number; is_allowed: boolean },
    Error,
    { connId: string; entity_ids: string[]; is_allowed: boolean }
  >({
    mutationFn: ({ connId, entity_ids, is_allowed }) => {
      if (!USE_REAL_API) return Promise.reject(new Error("Requires real API mode."));
      return intFetch<{ updated: number; is_allowed: boolean }>(
        "POST",
        `/api/v1/integrations/connections/${connId}/entities/bulk-permission`,
        { entity_ids, is_allowed },
      );
    },
    onSuccess: (_data, { connId }) => {
      void queryClient.invalidateQueries({ queryKey: ["schema-entities", connId] });
      void queryClient.invalidateQueries({ queryKey: ["data-connections"] });
    },
  });
}

// ── Semantic Data Mappings ────────────────────────────────────────────────────

export interface SemanticMappingFE {
  id: string;
  tenant_id: string;
  semantic_concept: string;
  connection_id: string;
  entity_id: string;
  field_name: string;
  display_label: string;
  created_by: string;
  created_at: string;
}

export interface SemanticMappingCreate {
  semantic_concept: string;
  connection_id: string;
  entity_id: string;
  field_name: string;
  display_label?: string;
  created_by?: string;
}


async function dataFetch<T>(method: string, path: string, body?: unknown): Promise<T> {
  return apiFetch<T>(method, path, body);
}

/** List all semantic mappings for this tenant. */
export function useSemanticMappings() {
  return useQuery<SemanticMappingFE[]>({
    queryKey: ["semantic-mappings"] as const,
    queryFn: () =>
      USE_REAL_API
        ? dataFetch<SemanticMappingFE[]>("GET", "/api/v1/data/mappings")
        : Promise.resolve([]),
    staleTime: 30_000,
  });
}

/** Create a new semantic mapping. */
export function useCreateSemanticMapping() {
  const queryClient = useQueryClient();
  return useMutation<SemanticMappingFE, Error, SemanticMappingCreate>({
    mutationFn: (body) => {
      if (!USE_REAL_API) return Promise.reject(new Error("Requires real API mode."));
      return dataFetch<SemanticMappingFE>("POST", "/api/v1/data/mappings", body);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["semantic-mappings"] });
    },
  });
}

/** Delete a semantic mapping. */
export function useDeleteSemanticMapping() {
  const queryClient = useQueryClient();
  return useMutation<void, Error, string>({
    mutationFn: (mappingId) => {
      if (!USE_REAL_API) return Promise.resolve();
      return dataFetch<void>("DELETE", `/api/v1/data/mappings/${mappingId}`);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["semantic-mappings"] });
    },
  });
}

// ── Action Tool Framework ─────────────────────────────────────────────────────

export type ActionStatus =
  | "proposed"
  | "approved"
  | "executed"
  | "rejected"
  | "failed"
  | "unauthorized"
  | "invalid_arguments";

export interface ActionAuditFE {
  id: string;
  tenant_id: string;
  role_key: string;
  tool_name: string;
  arguments_json: string;
  risk_level: string;
  approval_status: string;
  execution_status: string;
  approval_request_id: string | null;
  task_id: string | null;
  error_message: string | null;
  created_at: string;
  approved_at: string | null;
  executed_at: string | null;
}

export interface ActionToolMeta {
  tool_name: string;
  display_name: string;
  description: string;
  risk_level: string;
  requires_approval: boolean;
  target_integration: string;
  allowed_roles: string[];
}

export interface ActionDecisionResult {
  tool_name: string;
  status: ActionStatus;
  approval_request_id: string | null;
  task_id: string | null;
  message: string;
  details: Record<string, unknown>;
}


async function actionFetch<T>(method: string, path: string, body?: unknown): Promise<T> {
  return apiFetch<T>(method, path, body);
}

/** List all action audit records for this tenant. */
export function useActionAudits() {
  return useQuery<ActionAuditFE[]>({
    queryKey: ["action-audits"] as const,
    queryFn: () =>
      USE_REAL_API
        ? actionFetch<ActionAuditFE[]>("GET", "/api/v1/actions/audits")
        : Promise.resolve([]),
    staleTime: 10_000,
    // Auto-refresh while any action is pending
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!Array.isArray(data)) return false;
      const pending = data.some((a) => a.approval_status === "proposed");
      return pending ? 5000 : false;
    },
  });
}

/** List registered action tools. */
export function useActionTools() {
  return useQuery<ActionToolMeta[]>({
    queryKey: ["action-tools"] as const,
    queryFn: () =>
      USE_REAL_API
        ? actionFetch<ActionToolMeta[]>("GET", "/api/v1/actions/tools")
        : Promise.resolve([
            {
              tool_name: "create_internal_task",
              display_name: "Create Internal Task",
              description: "Creates an internal EAAWP task record. Low-risk, no external actions.",
              risk_level: "low",
              requires_approval: false,
              target_integration: "internal",
              allowed_roles: ["DIGITAL_MARKETING_MANAGER"],
            },
          ]),
    staleTime: 120_000,
  });
}

/** Approve a pending action (re-validates + executes server-side). */
export function useApproveAction() {
  const queryClient = useQueryClient();
  return useMutation<ActionDecisionResult, Error, { auditId: string }>({
    mutationFn: ({ auditId }) => {
      if (!USE_REAL_API) return Promise.reject(new Error("Requires real API mode."));
      return actionFetch<ActionDecisionResult>(
        "POST",
        `/api/v1/actions/audits/${auditId}/approve`,
        { decision: "approved" },
      );
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["action-audits"] });
      void queryClient.invalidateQueries({ queryKey: ["approvals"] });
      void queryClient.invalidateQueries({ queryKey: queryKeys.tasks });
    },
  });
}

/** Reject a pending action — it will never execute. */
export function useRejectAction() {
  const queryClient = useQueryClient();
  return useMutation<ActionDecisionResult, Error, { auditId: string }>({
    mutationFn: ({ auditId }) => {
      if (!USE_REAL_API) return Promise.reject(new Error("Requires real API mode."));
      return actionFetch<ActionDecisionResult>(
        "POST",
        `/api/v1/actions/audits/${auditId}/reject`,
        { decision: "rejected" },
      );
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["action-audits"] });
      void queryClient.invalidateQueries({ queryKey: ["approvals"] });
    },
  });
}

// ── Multi-Step Planning ───────────────────────────────────────────────────────

export type PlanStatus = "planning" | "running" | "awaiting_approval" | "completed" | "failed" | "rejected";
export type StepStatus = "pending" | "running" | "completed" | "failed" | "awaiting_approval" | "approved" | "rejected" | "skipped";

export interface PlanStepFE {
  step_id: string;
  plan_id: string;
  step_index: number;
  step_type: string;
  description: string;
  tool_name: string | null;
  arguments_json: string;
  depends_on: number[];
  status: StepStatus;
  result_summary: string;
  approval_request_id: string | null;
  action_audit_id: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface ExecutionPlanFE {
  id: string;
  tenant_id: string;
  role_key: string;
  session_id: string | null;
  objective: string;
  status: PlanStatus;
  total_steps: number;
  completed_steps: number;
  tool_calls_used: number;
  final_message: string;
  error_message: string | null;
  steps: PlanStepFE[];
  created_at: string;
  completed_at: string | null;
}


/** Fetch a specific execution plan with all its steps. */
export function useExecutionPlan(planId: string | null) {
  return useQuery<ExecutionPlanFE>({
    queryKey: ["execution-plan", planId] as const,
    queryFn: () => {
      if (!planId || !USE_REAL_API) return Promise.reject(new Error("No plan ID"));
      return apiClient.get<ExecutionPlanFE>(`/api/v1/planning/plans/${planId}`);
    },
    enabled: !!planId && USE_REAL_API,
    staleTime: 5_000,
    refetchInterval: (query) => {
      const s = query.state.data?.status;
      return s === "running" || s === "planning" ? 2000 : false;
    },
  });
}

/** List all execution plans for the tenant. */
export function useExecutionPlans() {
  return useQuery<ExecutionPlanFE[]>({
    queryKey: ["execution-plans"] as const,
    queryFn: () =>
      USE_REAL_API
        ? apiClient.get<ExecutionPlanFE[]>("/api/v1/planning/plans")
        : Promise.resolve([]),
    staleTime: 15_000,
  });
}

/** Resume a paused plan after approval. */
export function useResumePlan() {
  const queryClient = useQueryClient();
  return useMutation<ExecutionPlanFE, Error, { planId: string }>({
    mutationFn: ({ planId }) => {
      if (!USE_REAL_API) return Promise.reject(new Error("Requires real API mode."));
      return apiClient.post<ExecutionPlanFE>(
        `/api/v1/planning/plans/${planId}/resume`,
        { plan_id: planId },
      );
    },
    onSuccess: (_, { planId }) => {
      void queryClient.invalidateQueries({ queryKey: ["execution-plan", planId] });
      void queryClient.invalidateQueries({ queryKey: ["execution-plans"] });
      void queryClient.invalidateQueries({ queryKey: ["approvals"] });
      void queryClient.invalidateQueries({ queryKey: ["action-audits"] });
      void queryClient.invalidateQueries({ queryKey: queryKeys.tasks });
    },
  });
}

/** Reject the pending action for a plan and stop it without executing the action. */
export function useRejectPlan() {
  const queryClient = useQueryClient();
  return useMutation<ExecutionPlanFE, Error, { planId: string }>({
    mutationFn: ({ planId }) => {
      if (!USE_REAL_API) return Promise.reject(new Error("Requires real API mode."));
      return apiClient.post<ExecutionPlanFE>(
        `/api/v1/planning/plans/${planId}/reject`,
        { plan_id: planId },
      );
    },
    onSuccess: (_, { planId }) => {
      void queryClient.invalidateQueries({ queryKey: ["execution-plan", planId] });
      void queryClient.invalidateQueries({ queryKey: ["execution-plans"] });
      void queryClient.invalidateQueries({ queryKey: ["approvals"] });
      void queryClient.invalidateQueries({ queryKey: ["action-audits"] });
    },
  });
}

// ── Autonomous Monitoring ─────────────────────────────────────────────────────
// Hooks for the Monitoring and Trigger Engine.
//
// IMPORTANT: In mock mode (VITE_USE_REAL_API=false), these hooks return
// clearly-labelled SIMULATED data. They do NOT claim real monitoring is
// occurring. Real monitoring requires the backend scheduler to be running.

export type MonitoringOperator =
  | "decreases_by_more_than_pct"
  | "increases_by_more_than_pct"
  | "falls_below"
  | "exceeds"
  | "equals"
  | "is_unavailable"
  | "count_falls_below"
  | "count_exceeds";

export type MonitoringFrequency = "hourly" | "every_6h" | "daily";

export type MonitoringAggregateFn = "avg" | "sum" | "count" | "max" | "min" | "latest";

export type MonitoringRuleStatus = "idle" | "evaluating" | "triggered" | "error" | "disabled";

export type MonitoringResultCode =
  | "condition_false"
  | "condition_true"
  | "condition_true_cooldown"
  | "error"
  | "permission_denied"
  | "no_data";

export interface MonitoringCondition {
  metric_field: string;
  operator: MonitoringOperator;
  threshold: number;
  comparison_window_hours?: number;
  aggregate_fn?: MonitoringAggregateFn;
}

export interface MonitoringRuleFE {
  id: string;
  tenant_id: string;
  role_key: string;
  name: string;
  description: string;
  enabled: boolean;
  semantic_concept: string;
  condition: MonitoringCondition;
  evaluation_frequency: MonitoringFrequency;
  action_objective: string;
  require_approval_on_trigger: boolean;
  cooldown_hours: number;
  last_evaluated_at: string | null;
  last_triggered_at: string | null;
  next_evaluation_at: string | null;
  created_at: string;
  updated_at: string;
  status: MonitoringRuleStatus;
  last_evaluation_result: MonitoringResultCode | null;
  last_error_message: string | null;
  last_triggered_plan_id: string | null;
}

export interface MonitoringRuleCreate {
  name: string;
  description?: string;
  enabled?: boolean;
  semantic_concept: string;
  condition: MonitoringCondition;
  evaluation_frequency: MonitoringFrequency;
  action_objective: string;
  require_approval_on_trigger?: boolean;
  cooldown_hours?: number;
}

export interface MonitoringRuleUpdate {
  name?: string;
  description?: string;
  enabled?: boolean;
  semantic_concept?: string;
  condition?: MonitoringCondition;
  evaluation_frequency?: MonitoringFrequency;
  action_objective?: string;
  require_approval_on_trigger?: boolean;
  cooldown_hours?: number;
}

export interface MonitoringAuditFE {
  id: string;
  tenant_id: string;
  role_key: string;
  rule_id: string;
  rule_name: string;
  evaluated_at: string;
  semantic_concept: string;
  result: MonitoringResultCode;
  triggered: boolean;
  triggered_plan_id: string | null;
  failure_reason: string | null;
  current_value: number | null;
  previous_value: number | null;
}

export interface MonitoringStatusFE {
  scheduler_running: boolean;
  total_rules: number;
  enabled_rules: number;
  triggered_rules: number;
  error_rules: number;
  note: string;
}

// ── MOCK DATA — clearly distinguished from real monitoring ────────────────────

const MOCK_MONITORING_RULES: MonitoringRuleFE[] = [
  {
    id: "mock-rule-1",
    tenant_id: "default-tenant",
    role_key: "DIGITAL_MARKETING_MANAGER",
    name: "CTR Drop Alert [SIMULATED]",
    description:
      "SIMULATED — This is mock data. Real monitoring requires the backend scheduler.",
    enabled: true,
    semantic_concept: "campaign_clicks",
    condition: {
      metric_field: "clicks",
      operator: "decreases_by_more_than_pct",
      threshold: 20,
      comparison_window_hours: 168,
      aggregate_fn: "avg",
    },
    evaluation_frequency: "daily",
    action_objective:
      "Investigate the CTR drop and create a task to review underperforming campaigns",
    require_approval_on_trigger: false,
    cooldown_hours: 24,
    last_evaluated_at: new Date(Date.now() - 3_600_000).toISOString(),
    last_triggered_at: null,
    next_evaluation_at: new Date(Date.now() + 82_800_000).toISOString(),
    created_at: new Date(Date.now() - 86_400_000 * 7).toISOString(),
    updated_at: new Date(Date.now() - 86_400_000 * 7).toISOString(),
    status: "idle",
    last_evaluation_result: "condition_false",
    last_error_message: null,
    last_triggered_plan_id: null,
  },
  {
    id: "mock-rule-2",
    tenant_id: "default-tenant",
    role_key: "DIGITAL_MARKETING_MANAGER",
    name: "Spend Threshold Watch [SIMULATED]",
    description:
      "SIMULATED — Real monitoring requires VITE_USE_REAL_API=true and backend running.",
    enabled: true,
    semantic_concept: "campaign_spend",
    condition: {
      metric_field: "spend",
      operator: "exceeds",
      threshold: 10000,
      aggregate_fn: "sum",
    },
    evaluation_frequency: "every_6h",
    action_objective: "Alert on budget overspend and create a budget review task",
    require_approval_on_trigger: true,
    cooldown_hours: 12,
    last_evaluated_at: new Date(Date.now() - 21_600_000).toISOString(),
    last_triggered_at: null,
    next_evaluation_at: new Date(Date.now() + 21_600_000).toISOString(),
    created_at: new Date(Date.now() - 86_400_000 * 3).toISOString(),
    updated_at: new Date(Date.now() - 86_400_000 * 3).toISOString(),
    status: "idle",
    last_evaluation_result: "condition_false",
    last_error_message: null,
    last_triggered_plan_id: null,
  },
];

const MOCK_MONITORING_STATUS: MonitoringStatusFE = {
  scheduler_running: false,
  total_rules: 2,
  enabled_rules: 2,
  triggered_rules: 0,
  error_rules: 0,
  note: "SIMULATED — backend scheduler is not running. Set VITE_USE_REAL_API=true for real monitoring.",
};

// ── API helpers ───────────────────────────────────────────────────────────────


async function monFetch<T>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  return apiFetch<T>(method, path, body);
}

// ── Query keys ────────────────────────────────────────────────────────────────

export const monitoringKeys = {
  rules: (roleKey: string) => ["monitoring-rules", roleKey] as const,
  rule: (ruleId: string) => ["monitoring-rule", ruleId] as const,
  audit: (ruleId: string) => ["monitoring-audit", ruleId] as const,
  status: ["monitoring-status"] as const,
};

// ── Hooks ─────────────────────────────────────────────────────────────────────

/**
 * List all monitoring rules for the given role.
 * Mock mode returns clearly-labelled SIMULATED rules.
 * Real mode queries /api/v1/monitoring/rules.
 */
export function useMonitoringRules(
  roleKey: string = "DIGITAL_MARKETING_MANAGER",
) {
  return useQuery<MonitoringRuleFE[]>({
    queryKey: monitoringKeys.rules(roleKey),
    queryFn: () =>
      USE_REAL_API
        ? monFetch<MonitoringRuleFE[]>(
            "GET",
            `/api/v1/monitoring/rules?role_key=${roleKey}`,
          )
        : Promise.resolve(MOCK_MONITORING_RULES),
    staleTime: 15_000,
    refetchInterval: USE_REAL_API ? 30_000 : false,
  });
}

/**
 * Get the monitoring scheduler status and rule counts.
 * Mock mode clearly states the scheduler is not running.
 */
export function useMonitoringStatus() {
  return useQuery<MonitoringStatusFE>({
    queryKey: monitoringKeys.status,
    queryFn: () =>
      USE_REAL_API
        ? monFetch<MonitoringStatusFE>("GET", "/api/v1/monitoring/status")
        : Promise.resolve(MOCK_MONITORING_STATUS),
    staleTime: 30_000,
  });
}

/**
 * Create a new monitoring rule.
 * Validates the condition structure before sending to backend.
 * Requires real API mode — mock mode rejects with a clear error.
 */
export function useCreateMonitoringRule(
  roleKey: string = "DIGITAL_MARKETING_MANAGER",
) {
  const queryClient = useQueryClient();
  return useMutation<MonitoringRuleFE, Error, MonitoringRuleCreate>({
    mutationFn: (body) => {
      if (!USE_REAL_API) {
        return Promise.reject(
          new Error(
            "Creating monitoring rules requires the real backend (VITE_USE_REAL_API=true). " +
              "Mock mode does not claim to create real monitoring rules.",
          ),
        );
      }
      return monFetch<MonitoringRuleFE>(
        "POST",
        `/api/v1/monitoring/rules?role_key=${roleKey}`,
        body,
      );
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: monitoringKeys.rules(roleKey),
      });
      void queryClient.invalidateQueries({ queryKey: monitoringKeys.status });
    },
  });
}

/** Update an existing monitoring rule. */
export function useUpdateMonitoringRule(
  roleKey: string = "DIGITAL_MARKETING_MANAGER",
) {
  const queryClient = useQueryClient();
  return useMutation<MonitoringRuleFE, Error, { ruleId: string; update: MonitoringRuleUpdate }>({
    mutationFn: ({ ruleId, update }) => {
      if (!USE_REAL_API) {
        return Promise.reject(new Error("Requires VITE_USE_REAL_API=true."));
      }
      return monFetch<MonitoringRuleFE>(
        "PATCH",
        `/api/v1/monitoring/rules/${ruleId}`,
        update,
      );
    },
    onSuccess: (_, { ruleId }) => {
      void queryClient.invalidateQueries({
        queryKey: monitoringKeys.rules(roleKey),
      });
      void queryClient.invalidateQueries({
        queryKey: monitoringKeys.rule(ruleId),
      });
    },
  });
}

/** Delete a monitoring rule. */
export function useDeleteMonitoringRule(
  roleKey: string = "DIGITAL_MARKETING_MANAGER",
) {
  const queryClient = useQueryClient();
  return useMutation<void, Error, string>({
    mutationFn: (ruleId) => {
      if (!USE_REAL_API) {
        return Promise.reject(new Error("Requires VITE_USE_REAL_API=true."));
      }
      return monFetch<void>("DELETE", `/api/v1/monitoring/rules/${ruleId}`);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: monitoringKeys.rules(roleKey),
      });
      void queryClient.invalidateQueries({ queryKey: monitoringKeys.status });
    },
  });
}

/** Enable a monitoring rule. */
export function useEnableMonitoringRule(
  roleKey: string = "DIGITAL_MARKETING_MANAGER",
) {
  const queryClient = useQueryClient();
  return useMutation<MonitoringRuleFE, Error, string>({
    mutationFn: (ruleId) => {
      if (!USE_REAL_API) {
        return Promise.reject(new Error("Requires VITE_USE_REAL_API=true."));
      }
      return monFetch<MonitoringRuleFE>(
        "POST",
        `/api/v1/monitoring/rules/${ruleId}/enable`,
      );
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: monitoringKeys.rules(roleKey),
      });
    },
  });
}

/** Disable a monitoring rule. */
export function useDisableMonitoringRule(
  roleKey: string = "DIGITAL_MARKETING_MANAGER",
) {
  const queryClient = useQueryClient();
  return useMutation<MonitoringRuleFE, Error, string>({
    mutationFn: (ruleId) => {
      if (!USE_REAL_API) {
        return Promise.reject(new Error("Requires VITE_USE_REAL_API=true."));
      }
      return monFetch<MonitoringRuleFE>(
        "POST",
        `/api/v1/monitoring/rules/${ruleId}/disable`,
      );
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: monitoringKeys.rules(roleKey),
      });
    },
  });
}

/** Get the evaluation audit log for a specific monitoring rule. */
export function useMonitoringAudit(ruleId: string | null) {
  return useQuery<MonitoringAuditFE[]>({
    queryKey: monitoringKeys.audit(ruleId ?? ""),
    queryFn: () => {
      if (!ruleId || !USE_REAL_API) return Promise.resolve([]);
      return monFetch<MonitoringAuditFE[]>(
        "GET",
        `/api/v1/monitoring/rules/${ruleId}/audit`,
      );
    },
    enabled: !!ruleId,
    staleTime: 15_000,
  });
}

/** Manually trigger evaluation of a rule (admin action). */
export function useManuallyEvaluateRule(
  roleKey: string = "DIGITAL_MARKETING_MANAGER",
) {
  const queryClient = useQueryClient();
  return useMutation<Record<string, unknown>, Error, string>({
    mutationFn: (ruleId) => {
      if (!USE_REAL_API) {
        return Promise.reject(
          new Error(
            "Manual rule evaluation requires VITE_USE_REAL_API=true. " +
              "This action queries real company data through the controlled access layer.",
          ),
        );
      }
      return monFetch<Record<string, unknown>>(
        "POST",
        `/api/v1/monitoring/evaluate/${ruleId}`,
      );
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: monitoringKeys.rules(roleKey),
      });
      void queryClient.invalidateQueries({ queryKey: monitoringKeys.status });
      // Evaluation may have triggered a plan
      void queryClient.invalidateQueries({ queryKey: ["execution-plans"] });
    },
  });
}

// ── Email Integration ─────────────────────────────────────────────────────────
// Hooks for the External Email Integration Framework.
//
// MOCK MODE (VITE_USE_REAL_API=false):
//   Returns clearly-labelled SIMULATED data.
//   Mutations warn the user that real mode is required.
//   No emails are ever sent in mock mode.
//
// REAL MODE (VITE_USE_REAL_API=true):
//   Calls the FastAPI backend. Passwords are sent once and encrypted server-side.
//   Passwords are NEVER returned after save — only a password_hint is shown.

export type TLSMode = "starttls" | "ssl_tls" | "none";
export type EmailIntegrationStatus =
  | "not_configured"
  | "not_tested"
  | "connected"
  | "failed"
  | "disabled";

export interface EmailIntegrationFE {
  id: string;
  tenant_id: string;
  provider_type: string;
  display_name: string;
  smtp_host: string;
  smtp_port: number;
  username: string;
  password_hint: string;  // "••••••" if set — NEVER the actual password
  tls_mode: string;
  sender_email: string;
  sender_display_name: string;
  status: EmailIntegrationStatus;
  is_enabled: boolean;
  last_tested_at: string | null;
  error_message: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface SMTPConfigCreate {
  display_name?: string;
  smtp_host: string;
  smtp_port: number;
  username: string;
  password: string;   // sent once, encrypted server-side, never returned
  tls_mode: TLSMode;
  sender_email: string;
  sender_display_name?: string;
  created_by?: string;
}

export interface SMTPConfigUpdate {
  display_name?: string;
  smtp_host?: string;
  smtp_port?: number;
  username?: string;
  password?: string;  // optional — if omitted, existing password is kept
  tls_mode?: TLSMode;
  sender_email?: string;
  sender_display_name?: string;
}

export interface EmailConnectionTestResult {
  integration_id: string;
  success: boolean;
  status: EmailIntegrationStatus;
  server_greeting: string | null;
  error_message: string | null;
}

export interface EmailAuditRowFE {
  id: string;
  role_key: string;
  integration_id: string | null;
  recipient_count: number;
  recipient_domains: string;
  subject_length: number;
  body_length: number;
  success: boolean;
  provider_message_id: string | null;
  error_message: string | null;
  attempted_at: string;
}

// ── Mock data ─────────────────────────────────────────────────────────────────

const MOCK_EMAIL_INTEGRATION: EmailIntegrationFE = {
  id: "mock-email-int-1",
  tenant_id: "default-tenant",
  provider_type: "smtp",
  display_name: "Company SMTP [SIMULATED]",
  smtp_host: "smtp.example.com",
  smtp_port: 587,
  username: "noreply@example.com",
  password_hint: "••••••",
  tls_mode: "starttls",
  sender_email: "noreply@example.com",
  sender_display_name: "EAAWP Platform",
  status: "not_tested",
  is_enabled: true,
  last_tested_at: null,
  error_message: null,
  created_by: "admin",
  created_at: new Date(Date.now() - 86_400_000).toISOString(),
  updated_at: new Date(Date.now() - 86_400_000).toISOString(),
};

// ── API helpers ───────────────────────────────────────────────────────────────


async function emailFetch<T>(method: string, path: string, body?: unknown): Promise<T> {
  return apiFetch<T>(method, path, body);
}

// ── Query keys ────────────────────────────────────────────────────────────────

export const emailKeys = {
  integration: ["email-integration"] as const,
  audit: ["email-audit"] as const,
};

// ── Hooks ─────────────────────────────────────────────────────────────────────

/**
 * Fetch the tenant's email integration status.
 * Returns null (404) if not configured — always safe, never includes password.
 */
export function useEmailIntegration() {
  return useQuery<EmailIntegrationFE | null>({
    queryKey: emailKeys.integration,
    queryFn: async () => {
      if (!USE_REAL_API) return MOCK_EMAIL_INTEGRATION;
      try {
        return await emailFetch<EmailIntegrationFE>("GET", "/api/v1/email/integration");
      } catch (err) {
        if (err instanceof Error && err.message.includes("404")) return null;
        throw err;
      }
    },
    staleTime: 30_000,
  });
}

/** Create or replace the SMTP integration. Password is never returned after save. */
export function useCreateEmailIntegration() {
  const queryClient = useQueryClient();
  return useMutation<EmailIntegrationFE, Error, SMTPConfigCreate>({
    mutationFn: (body) => {
      if (!USE_REAL_API)
        return Promise.reject(
          new Error("Configuring SMTP requires VITE_USE_REAL_API=true. Mock mode does not send real emails."),
        );
      return emailFetch<EmailIntegrationFE>("POST", "/api/v1/email/integration", body);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: emailKeys.integration });
    },
  });
}

/** Partially update the SMTP integration. If password is omitted, existing password is kept. */
export function useUpdateEmailIntegration() {
  const queryClient = useQueryClient();
  return useMutation<EmailIntegrationFE, Error, SMTPConfigUpdate>({
    mutationFn: (body) => {
      if (!USE_REAL_API)
        return Promise.reject(new Error("Requires VITE_USE_REAL_API=true."));
      return emailFetch<EmailIntegrationFE>("PATCH", "/api/v1/email/integration", body);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: emailKeys.integration });
    },
  });
}

/** Remove the integration. Audit logs are preserved. */
export function useDeleteEmailIntegration() {
  const queryClient = useQueryClient();
  return useMutation<void, Error, void>({
    mutationFn: () => {
      if (!USE_REAL_API)
        return Promise.reject(new Error("Requires VITE_USE_REAL_API=true."));
      return emailFetch<void>("DELETE", "/api/v1/email/integration");
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: emailKeys.integration });
    },
  });
}

/**
 * Test the SMTP connection without sending an email.
 * Updates integration status. Never returns credentials.
 */
export function useTestEmailIntegration() {
  const queryClient = useQueryClient();
  return useMutation<EmailConnectionTestResult, Error, void>({
    mutationFn: () => {
      if (!USE_REAL_API)
        return Promise.reject(new Error("Connection test requires VITE_USE_REAL_API=true."));
      return emailFetch<EmailConnectionTestResult>("POST", "/api/v1/email/integration/test");
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: emailKeys.integration });
    },
  });
}

/** Enable the integration. */
export function useEnableEmailIntegration() {
  const queryClient = useQueryClient();
  return useMutation<EmailIntegrationFE, Error, void>({
    mutationFn: () => {
      if (!USE_REAL_API)
        return Promise.reject(new Error("Requires VITE_USE_REAL_API=true."));
      return emailFetch<EmailIntegrationFE>("POST", "/api/v1/email/integration/enable");
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: emailKeys.integration });
    },
  });
}

/** Disable the integration. */
export function useDisableEmailIntegration() {
  const queryClient = useQueryClient();
  return useMutation<EmailIntegrationFE, Error, void>({
    mutationFn: () => {
      if (!USE_REAL_API)
        return Promise.reject(new Error("Requires VITE_USE_REAL_API=true."));
      return emailFetch<EmailIntegrationFE>("POST", "/api/v1/email/integration/disable");
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: emailKeys.integration });
    },
  });
}

/**
 * Fetch the email send audit log.
 * Returns safe metadata only — no credentials, no full body.
 */
export function useEmailAuditLog() {
  return useQuery<EmailAuditRowFE[]>({
    queryKey: emailKeys.audit,
    queryFn: () => {
      if (!USE_REAL_API) return Promise.resolve([]);
      return emailFetch<EmailAuditRowFE[]>("GET", "/api/v1/email/audit");
    },
    staleTime: 15_000,
  });
}

// ── Campaign Management ───────────────────────────────────────────────────────

export type CampaignStatus =
  | "draft" | "planned" | "active" | "paused" | "completed" | "cancelled";

export interface KPIDefinition {
  name: string;
  target: number;
  unit: string;
}

export interface CampaignFE {
  id: string;
  tenant_id: string;
  name: string;
  objective: string;
  description: string;
  status: CampaignStatus;
  target_audience: string;
  channel: string;
  budget: number;
  start_date: string | null;
  end_date: string | null;
  kpis: KPIDefinition[];
  metadata: Record<string, unknown>;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface CampaignMetricFE {
  id: string;
  campaign_id: string;
  tenant_id: string;
  metric_name: string;
  metric_value: number;
  metric_date: string;
  source: string;
  metadata: Record<string, unknown>;
  recorded_by: string;
  recorded_at: string;
}

export interface CampaignSummaryFE {
  id: string;
  name: string;
  status: string;
  channel: string;
  objective: string;
  budget: number;
  start_date: string | null;
  end_date: string | null;
  kpi_count: number;
  metric_count: number;
  latest_metrics: Array<{ name: string; value: number; date: string; source: string }>;
}

export interface CampaignCreateBody {
  name: string;
  objective?: string;
  description?: string;
  target_audience?: string;
  channel?: string;
  budget?: number;
  start_date?: string;
  end_date?: string;
  kpis?: KPIDefinition[];
  created_by?: string;
}

export interface CampaignUpdateBody {
  name?: string;
  objective?: string;
  channel?: string;
  budget?: number;
  status?: CampaignStatus;
  target_audience?: string;
  start_date?: string;
  end_date?: string;
}

export interface CampaignMetricCreateBody {
  metric_name: string;
  metric_value: number;
  metric_date: string;
  source?: string;
  metadata?: Record<string, unknown>;
}

// Mock data — clearly labelled
const MOCK_CAMPAIGNS: CampaignFE[] = [
  {
    id: "mock-camp-1",
    tenant_id: "default-tenant",
    name: "Q4 Email Campaign [SIMULATED]",
    objective: "Drive 20% more conversions in Q4",
    description: "",
    status: "active",
    target_audience: "Existing customers, re-engagement",
    channel: "email",
    budget: 8000,
    start_date: "2026-10-01",
    end_date: "2026-12-31",
    kpis: [
      { name: "CTR", target: 0.05, unit: "%" },
      { name: "Conversions", target: 200, unit: "count" },
    ],
    metadata: {},
    created_by: "agent",
    created_at: new Date(Date.now() - 86400000 * 10).toISOString(),
    updated_at: new Date(Date.now() - 86400000 * 2).toISOString(),
  },
  {
    id: "mock-camp-2",
    tenant_id: "default-tenant",
    name: "Social Media Push [SIMULATED]",
    objective: "Increase brand awareness",
    description: "",
    status: "planned",
    target_audience: "18-35 demographics",
    channel: "social",
    budget: 3500,
    start_date: "2026-11-01",
    end_date: "2026-11-30",
    kpis: [{ name: "Impressions", target: 100000, unit: "count" }],
    metadata: {},
    created_by: "agent",
    created_at: new Date(Date.now() - 86400000 * 3).toISOString(),
    updated_at: new Date(Date.now() - 86400000 * 3).toISOString(),
  },
];


async function campFetch<T>(method: string, path: string, body?: unknown): Promise<T> {
  return apiFetch<T>(method, path, body);
}

export const campaignKeys = {
  list: (status?: string) => ["campaigns", status ?? "all"] as const,
  detail: (id: string) => ["campaign", id] as const,
  metrics: (id: string) => ["campaign-metrics", id] as const,
  summary: (id: string) => ["campaign-summary", id] as const,
};

export function useCampaigns(status?: string) {
  return useQuery<CampaignFE[]>({
    queryKey: campaignKeys.list(status),
    queryFn: () =>
      USE_REAL_API
        ? campFetch<CampaignFE[]>("GET", `/api/v1/campaigns${status ? `?status=${status}` : ""}`)
        : Promise.resolve(status ? MOCK_CAMPAIGNS.filter((c) => c.status === status) : MOCK_CAMPAIGNS),
    staleTime: 15_000,
  });
}

export function useCampaign(campaignId: string | null) {
  return useQuery<CampaignFE>({
    queryKey: campaignKeys.detail(campaignId ?? ""),
    queryFn: () => {
      if (!campaignId) return Promise.reject(new Error("No campaign ID"));
      if (!USE_REAL_API) {
        const c = MOCK_CAMPAIGNS.find((x) => x.id === campaignId);
        return c ? Promise.resolve(c) : Promise.reject(new Error("Not found"));
      }
      return campFetch<CampaignFE>("GET", `/api/v1/campaigns/${campaignId}`);
    },
    enabled: !!campaignId,
    staleTime: 15_000,
  });
}

export function useCampaignSummary(campaignId: string | null) {
  return useQuery<CampaignSummaryFE>({
    queryKey: campaignKeys.summary(campaignId ?? ""),
    queryFn: () => {
      if (!campaignId || !USE_REAL_API) return Promise.reject(new Error("Requires real API"));
      return campFetch<CampaignSummaryFE>("GET", `/api/v1/campaigns/${campaignId}/summary`);
    },
    enabled: !!campaignId && USE_REAL_API,
    staleTime: 15_000,
  });
}

export function useCampaignMetrics(campaignId: string | null) {
  return useQuery<CampaignMetricFE[]>({
    queryKey: campaignKeys.metrics(campaignId ?? ""),
    queryFn: () => {
      if (!campaignId || !USE_REAL_API) return Promise.resolve([]);
      return campFetch<CampaignMetricFE[]>("GET", `/api/v1/campaigns/${campaignId}/metrics`);
    },
    enabled: !!campaignId,
    staleTime: 15_000,
  });
}

export function useCreateCampaign() {
  const queryClient = useQueryClient();
  return useMutation<CampaignFE, Error, CampaignCreateBody>({
    mutationFn: (body) => {
      if (!USE_REAL_API) return Promise.reject(new Error("Requires VITE_USE_REAL_API=true."));
      return campFetch<CampaignFE>("POST", "/api/v1/campaigns", body);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["campaigns"] });
    },
  });
}

export function useUpdateCampaign(campaignId: string) {
  const queryClient = useQueryClient();
  return useMutation<CampaignFE, Error, CampaignUpdateBody>({
    mutationFn: (body) => {
      if (!USE_REAL_API) return Promise.reject(new Error("Requires VITE_USE_REAL_API=true."));
      return campFetch<CampaignFE>("PATCH", `/api/v1/campaigns/${campaignId}`, body);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["campaigns"] });
      void queryClient.invalidateQueries({ queryKey: campaignKeys.detail(campaignId) });
    },
  });
}

export function useRecordMetric(campaignId: string) {
  const queryClient = useQueryClient();
  return useMutation<CampaignMetricFE, Error, CampaignMetricCreateBody>({
    mutationFn: (body) => {
      if (!USE_REAL_API) return Promise.reject(new Error("Requires VITE_USE_REAL_API=true."));
      return campFetch<CampaignMetricFE>("POST", `/api/v1/campaigns/${campaignId}/metrics`, body);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: campaignKeys.metrics(campaignId) });
      void queryClient.invalidateQueries({ queryKey: campaignKeys.summary(campaignId) });
    },
  });
}

// ── Performance Intelligence ──────────────────────────────────────────────────

export interface KPIValueFE {
  value: number | null;
  unit: string;
  formula: string;
  is_calculated: boolean;
  missing_inputs: string[];
}

export interface PeriodComparisonFE {
  kpi_name: string;
  current: number | null;
  previous: number | null;
  pct_change: number | null;
  trend: "up" | "down" | "stable" | "unknown";
  is_significant: boolean;
  is_anomaly: boolean;
  anomaly_reason: string;
}

export interface PerformanceInsightFE {
  campaign_id: string;
  campaign_name: string;
  period_from: string | null;
  period_to: string | null;
  kpis: Record<string, KPIValueFE>;
  comparisons: PeriodComparisonFE[];
  strongest_metrics: string[];
  weakest_metrics: string[];
  anomalies: string[];
  data_completeness_pct: number;
  sources: string[];
  recommendations: string[];
  analysis_note: string;
}

export interface CampaignComparisonFE {
  campaigns: Array<{ id: string; name: string; kpi_values: Record<string, number | null>; completeness: number }>;
  kpis_compared: string[];
  ranked_by: string | null;
  ranking: string[];
  insufficient_data: boolean;
  insufficient_reason: string;
  sources: string[];
}


async function perfFetch<T>(method: string, path: string, body?: unknown): Promise<T> {
  return apiFetch<T>(method, path, body);
}

export const performanceKeys = {
  insight: (id: string, from?: string, to?: string) => ["perf-insight", id, from ?? "", to ?? ""] as const,
  comparison: (ids: string[]) => ["perf-compare", ids.join(",")] as const,
};

export function useCampaignPerformance(
  campaignId: string | null,
  dateFrom?: string,
  dateTo?: string,
) {
  return useQuery<PerformanceInsightFE>({
    queryKey: performanceKeys.insight(campaignId ?? "", dateFrom, dateTo),
    queryFn: () => {
      if (!campaignId || !USE_REAL_API) return Promise.reject(new Error("Requires real API"));
      const params = new URLSearchParams();
      if (dateFrom) params.set("date_from", dateFrom);
      if (dateTo) params.set("date_to", dateTo);
      return perfFetch<PerformanceInsightFE>(
        "GET",
        `/api/v1/performance/campaigns/${campaignId}${params.toString() ? `?${params}` : ""}`,
      );
    },
    enabled: !!campaignId && USE_REAL_API,
    staleTime: 30_000,
  });
}

export function useCampaignComparison(
  campaignIds: string[],
  rankBy: string = "ctr",
  dateFrom?: string,
  dateTo?: string,
) {
  return useQuery<CampaignComparisonFE>({
    queryKey: performanceKeys.comparison(campaignIds),
    queryFn: () => {
      if (campaignIds.length < 2 || !USE_REAL_API)
        return Promise.reject(new Error("Need 2+ campaigns and real API"));
      return perfFetch<CampaignComparisonFE>("POST", "/api/v1/performance/compare", {
        campaign_ids: campaignIds,
        rank_by: rankBy,
        date_from: dateFrom,
        date_to: dateTo,
      });
    },
    enabled: campaignIds.length >= 2 && USE_REAL_API,
    staleTime: 30_000,
  });
}

// ── Funnel Intelligence ───────────────────────────────────────────────────────

export interface FunnelStageFE {
  name: string;
  value: number | null;
  source: string;
  period: string;
  missing_reason: string;
}

export interface FunnelConversionRateFE {
  from_stage: string;
  to_stage: string;
  rate_pct: number | null;
  from_value: number | null;
  to_value: number | null;
  missing_reason: string;
}

export interface FunnelMetricsFE {
  stages: FunnelStageFE[];
  conversion_rates: FunnelConversionRateFE[];
  overall_conversion_rate: FunnelConversionRateFE | null;
  revenue: number | null;
  spend: number | null;
  cost_per_lead: number | null;
  cost_per_customer: number | null;
  revenue_per_lead: number | null;
  revenue_per_customer: number | null;
  roas: number | null;
  data_completeness_pct: number;
  sources: string[];
  findings: string[];
  recommendations: string[];
  analysis_note: string;
}


async function funnelFetch<T>(method: string, path: string, body?: unknown): Promise<T> {
  return apiFetch<T>(method, path, body);
}

export const funnelKeys = {
  general: (concepts: string[]) => ["funnel", concepts.join(",")] as const,
  campaign: (id: string) => ["funnel-campaign", id] as const,
};

export function useFunnelAnalysis(concepts?: string[]) {
  return useQuery<FunnelMetricsFE>({
    queryKey: funnelKeys.general(concepts ?? []),
    queryFn: () => {
      if (!USE_REAL_API) return Promise.reject(new Error("Requires real API"));
      return funnelFetch<FunnelMetricsFE>("POST", "/api/v1/funnel/analyze",
        concepts ? { concepts } : {});
    },
    enabled: USE_REAL_API,
    staleTime: 30_000,
  });
}

export function useCampaignFunnel(campaignId: string | null, externalConcepts?: string[]) {
  return useQuery<FunnelMetricsFE>({
    queryKey: funnelKeys.campaign(campaignId ?? ""),
    queryFn: () => {
      if (!campaignId || !USE_REAL_API) return Promise.reject(new Error("Requires real API"));
      return funnelFetch<FunnelMetricsFE>("POST", `/api/v1/funnel/campaign/${campaignId}`,
        externalConcepts ? { external_concepts: externalConcepts } : {});
    },
    enabled: !!campaignId && USE_REAL_API,
    staleTime: 30_000,
  });
}

// ── Marketing Strategy ────────────────────────────────────────────────────────

export interface MarketingObjectiveFE {
  id: string;
  tenant_id: string;
  name: string;
  description: string;
  objective_type: string;
  priority: number;
  status: string;
  target_metric: string;
  target_value: number | null;
  current_value: number | null;
  start_date: string | null;
  target_date: string | null;
  linked_campaign_ids: string[];
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface MarketingPriorityFE {
  title: string;
  category: string;
  severity: string;
  description: string;
  evidence: string[];
  affected_campaigns: string[];
  affected_funnel_stage: string;
  kpi_impact: string;
  confidence: number;
  data_completeness: number;
  recommended_next_step: string;
  required_approval: string;
  priority_score: number;
  sources: string[];
}

export interface StrategicAnalysisFE {
  tenant_id: string;
  generated_at: string;
  current_situation: string;
  top_problems: MarketingPriorityFE[];
  top_opportunities: MarketingPriorityFE[];
  all_priorities: MarketingPriorityFE[];
  active_objectives: Array<Record<string, unknown>>;
  recommended_actions: string[];
  uncertainties: string[];
  data_completeness_pct: number;
  sources: string[];
  rag_sources: string[];
}


async function stratFetch<T>(method: string, path: string, body?: unknown): Promise<T> {
  return apiFetch<T>(method, path, body);
}

export const strategyKeys = {
  objectives: (status?: string) => ["strategy-objectives", status ?? "all"] as const,
  analysis: ["strategy-analysis"] as const,
};

export function useMarketingObjectives(status?: string) {
  return useQuery<MarketingObjectiveFE[]>({
    queryKey: strategyKeys.objectives(status),
    queryFn: () => USE_REAL_API
      ? stratFetch<MarketingObjectiveFE[]>("GET", `/api/v1/strategy/objectives${status ? `?status=${status}` : ""}`)
      : Promise.resolve([]),
    staleTime: 30_000,
  });
}

export function useStrategicAnalysis(campaignInsights?: unknown[], funnelInsights?: unknown[]) {
  return useQuery<StrategicAnalysisFE>({
    queryKey: strategyKeys.analysis,
    queryFn: () => {
      if (!USE_REAL_API) return Promise.reject(new Error("Requires real API"));
      return stratFetch<StrategicAnalysisFE>("POST", "/api/v1/strategy/analyze", {
        campaign_insights: campaignInsights ?? [],
        funnel_insights: funnelInsights ?? [],
      });
    },
    enabled: USE_REAL_API,
    staleTime: 60_000,
  });
}

export function useCreateObjective() {
  const queryClient = useQueryClient();
  return useMutation<MarketingObjectiveFE, Error, Partial<MarketingObjectiveFE>>({
    mutationFn: (body) => {
      if (!USE_REAL_API) return Promise.reject(new Error("Requires VITE_USE_REAL_API=true."));
      return stratFetch<MarketingObjectiveFE>("POST", "/api/v1/strategy/objectives", body);
    },
    onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ["strategy-objectives"] }); },
  });
}

// ── Content Intelligence ──────────────────────────────────────────────────────

export type ContentType = "brief" | "idea" | "draft" | "variant" | "analysis";
export type ContentStatus = "draft" | "review" | "approved" | "rejected" | "archived";

export interface ContentItemFE {
  id: string;
  tenant_id: string;
  content_type: ContentType;
  status: ContentStatus;
  title: string;
  channel: string;
  brief_json: Record<string, unknown>;
  body: string;
  campaign_id: string | null;
  objective_id: string | null;
  parent_id: string | null;
  rag_sources: string[];
  analysis: Record<string, unknown>;
  metadata: Record<string, unknown>;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface GenerateBriefBody {
  objective: string;
  target_audience?: string;
  channel?: string;
  campaign_id?: string;
  campaign_name?: string;
  kpis?: string[];
  tone?: string;
  additional_context?: string;
}

export interface GenerateIdeasBody {
  objective: string;
  channel?: string;
  target_audience?: string;
  n_ideas?: number;
  campaign_id?: string;
}

export interface GenerateDraftBody {
  objective: string;
  channel?: string;
  target_audience?: string;
  tone?: string;
  cta?: string;
  campaign_id?: string;
  max_words?: number;
}

export interface GenerateVariantsBody {
  source_content_id: string;
  n_variants?: number;
  variation_instructions?: string;
}

export interface AnalyzeContentBody {
  content_id: string;
  campaign_objective?: string;
  target_audience?: string;
  cta?: string;
  channel?: string;
}


async function contentFetch<T>(method: string, path: string, body?: unknown): Promise<T> {
  return apiFetch<T>(method, path, body);
}

export const contentKeys = {
  list: (type?: string) => ["content", type ?? "all"] as const,
  item: (id: string) => ["content-item", id] as const,
};

export function useContentItems(contentType?: string, campaignId?: string) {
  return useQuery<ContentItemFE[]>({
    queryKey: contentKeys.list(contentType),
    queryFn: () => {
      if (!USE_REAL_API) return Promise.resolve([]);
      const params = new URLSearchParams();
      if (contentType) params.set("content_type", contentType);
      if (campaignId) params.set("campaign_id", campaignId);
      return contentFetch<ContentItemFE[]>("GET", `/api/v1/content${params.toString() ? `?${params}` : ""}`);
    },
    staleTime: 15_000,
  });
}

export function useGenerateBrief() {
  const queryClient = useQueryClient();
  return useMutation<ContentItemFE, Error, GenerateBriefBody>({
    mutationFn: (body) => {
      if (!USE_REAL_API) return Promise.reject(new Error("Requires VITE_USE_REAL_API=true."));
      return contentFetch<ContentItemFE>("POST", "/api/v1/content/generate/brief", body);
    },
    onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ["content"] }); },
  });
}

export function useGenerateDraft() {
  const queryClient = useQueryClient();
  return useMutation<ContentItemFE, Error, GenerateDraftBody>({
    mutationFn: (body) => {
      if (!USE_REAL_API) return Promise.reject(new Error("Requires VITE_USE_REAL_API=true."));
      return contentFetch<ContentItemFE>("POST", "/api/v1/content/generate/draft", body);
    },
    onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ["content"] }); },
  });
}

export function useGenerateIdeas() {
  const queryClient = useQueryClient();
  return useMutation<ContentItemFE, Error, GenerateIdeasBody>({
    mutationFn: (body) => {
      if (!USE_REAL_API) return Promise.reject(new Error("Requires VITE_USE_REAL_API=true."));
      return contentFetch<ContentItemFE>("POST", "/api/v1/content/generate/ideas", body);
    },
    onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ["content"] }); },
  });
}

export function useAnalyzeContent() {
  const queryClient = useQueryClient();
  return useMutation<ContentItemFE, Error, AnalyzeContentBody>({
    mutationFn: (body) => {
      if (!USE_REAL_API) return Promise.reject(new Error("Requires VITE_USE_REAL_API=true."));
      return contentFetch<ContentItemFE>("POST", "/api/v1/content/analyze", body);
    },
    onSuccess: (data) => {
      void queryClient.invalidateQueries({ queryKey: contentKeys.item(data.id) });
    },
  });
}

// ── Notifications ─────────────────────────────────────────────────────────────

export interface NotificationFE {
  id: string;
  severity: "info" | "warning" | "critical";
  category: string;
  title: string;
  message: string;
  is_read: boolean;
  related_id: string | null;
  related_type: string | null;
  created_at: string;
}


async function notifFetch<T>(method: string, path: string, body?: unknown): Promise<T> {
  return apiFetch<T>(method, path, body);
}

export const notificationKeys = {
  list: (unread: boolean) => ["notifications", unread] as const,
};

export function useNotifications(unreadOnly = false) {
  return useQuery<NotificationFE[]>({
    queryKey: notificationKeys.list(unreadOnly),
    queryFn: () => USE_REAL_API
      ? notifFetch<NotificationFE[]>("GET", `/api/v1/notifications${unreadOnly ? "?unread_only=true" : ""}`)
      : Promise.resolve([]),
    staleTime: 10_000,
    refetchInterval: USE_REAL_API ? 30_000 : false,
  });
}

export function useMarkAllRead() {
  const queryClient = useQueryClient();
  return useMutation<{ marked_read: number }, Error, void>({
    mutationFn: () => {
      if (!USE_REAL_API) return Promise.reject(new Error("Requires real API."));
      return notifFetch<{ marked_read: number }>("POST", "/api/v1/notifications/read-all");
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["notifications"] });
    },
  });
}

// ── Reporting ─────────────────────────────────────────────────────────────────

export interface MarketingSummaryFE {
  report_type: string;
  tenant_id: string;
  period_days: number;
  generated_at: string;
  campaigns: { total: number; active: number; by_status: Record<string, number> };
  metrics_recorded: number;
  metric_names: string[];
  objectives: { total: number; active: number; achieved: number };
  content: { total: number; by_type: Record<string, number>; by_status: Record<string, number> };
  monitoring: { evaluations: number; triggered: number };
  note: string;
}


export function useMarketingSummary(periodDays: number = 7) {
  return useQuery<MarketingSummaryFE>({
    queryKey: ["marketing-summary", periodDays] as const,
    queryFn: () => {
      if (!USE_REAL_API) return Promise.reject(new Error("Requires real API."));
      return apiClient.get<MarketingSummaryFE>(`/api/v1/reports/marketing-summary?period_days=${periodDays}`);
    },
    enabled: USE_REAL_API,
    staleTime: 60_000,
  });
}

// ── Channel Integration ───────────────────────────────────────────────────────

export interface ChannelIntegrationFE {
  id: string;
  tenant_id: string;
  channel_type: string;
  display_name: string;
  provider: string;
  status: string;
  is_enabled: boolean;
  capabilities: string[];
  account_info: Record<string, unknown>;
  last_tested_at: string | null;
  error_message: string | null;
  created_by: string;
  created_at: string;
}


async function chanFetch<T>(method: string, path: string, body?: unknown): Promise<T> {
  return apiFetch<T>(method, path, body);
}

export function useChannelIntegrations() {
  return useQuery<ChannelIntegrationFE[]>({
    queryKey: ["channel-integrations"] as const,
    queryFn: () => USE_REAL_API ? chanFetch<ChannelIntegrationFE[]>("GET", "/api/v1/channels") : Promise.resolve([]),
    staleTime: 15_000,
  });
}

export function useTestChannel() {
  const queryClient = useQueryClient();
  return useMutation<Record<string, unknown>, Error, string>({
    mutationFn: (id) => {
      if (!USE_REAL_API) return Promise.reject(new Error("Requires real API."));
      return chanFetch<Record<string, unknown>>("POST", `/api/v1/channels/${id}/test`);
    },
    onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ["channel-integrations"] }); },
  });
}

// ── Onboarding & AI Workforce ─────────────────────────────────────────────────

export interface OnboardRequest {
  company_name: string;
  industry?: string;
  region?: string;
  employees?: number;
  website?: string;
  description?: string;
  admin_name: string;
  admin_email: string;
  admin_password: string;
}

export interface OnboardResponse {
  company_id: string;
  company_name: string;
  tenant_id: string;
  admin_user_id: string;
  dmm_initialized: boolean;
  message: string;
}

export interface OnboardingStatus {
  tenant_id: string;
  has_company: boolean;
  has_dmm_config: boolean;
  has_ai_employee: boolean;
  has_knowledge: boolean;
  has_data_connection: boolean;
  has_channel: boolean;
  status: "not_configured" | "configuring" | "ready_for_test" | "active" | "paused";
  checklist: Record<string, boolean>;
}

export interface RealCompanyFE {
  id: string;
  name: string;
  industry: string;
  region: string;
  employees: number;
  is_active: boolean;
  created_at: string;
}

const OB_HEADERS = { "Content-Type": "application/json" };

/** Create a brand-new company with admin user and DMM config. */
export function useOnboardCompany() {
  return useMutation<OnboardResponse, Error, OnboardRequest>({
    mutationFn: (body) => {
      if (!USE_REAL_API) {
        return Promise.reject(new Error(
          "Company creation requires VITE_USE_REAL_API=true and a running backend."
        ));
      }
      return apiClient.post<OnboardResponse>("/api/v1/onboarding/company", body);
    },
  });
}

/** Get onboarding/DMM readiness status for a tenant. */
export function useOnboardingStatus(tenantId: string | null) {
  return useQuery<OnboardingStatus>({
    queryKey: ["onboarding-status", tenantId] as const,
    queryFn: () => {
      if (!tenantId || !USE_REAL_API) return Promise.reject(new Error("No tenant."));
      return apiClient.get<OnboardingStatus>(`/api/v1/onboarding/status/${tenantId}`);
    },
    enabled: !!tenantId && USE_REAL_API,
    staleTime: 10_000,
  });
}

/** Activate the DMM AI employee for a tenant. */
export function useActivateDMM() {
  const queryClient = useQueryClient();
  return useMutation<Record<string, unknown>, Error, string>({
    mutationFn: (tenantId) => {
      if (!USE_REAL_API) return Promise.reject(new Error("Requires real API."));
      return apiClient.post<Record<string, unknown>>("/api/v1/onboarding/activate-dmm", { tenant_id: tenantId });
    },
    onSuccess: (_, tenantId) => {
      void queryClient.invalidateQueries({ queryKey: ["onboarding-status", tenantId] });
    },
  });
}

/** List real companies from backend. */
export function useRealCompanies() {
  return useQuery<RealCompanyFE[]>({
    queryKey: ["real-companies"] as const,
    queryFn: () => USE_REAL_API
      ? apiClient.get<RealCompanyFE[]>("/api/v1/companies")
      : Promise.resolve([]),
    staleTime: 30_000,
  });
}

// AI Workforce role definitions (static + extensible)
export interface AIWorkforceRole {
  role_key: string;
  display_name: string;
  description: string;
  status: "active" | "coming_soon";
  icon: string;
}

export const AI_WORKFORCE_ROLES: AIWorkforceRole[] = [
  {
    role_key: "DIGITAL_MARKETING_MANAGER",
    display_name: "Digital Marketing Manager",
    description: "Manages campaigns, generates content, analyzes performance, monitors KPIs, and prepares marketing communications.",
    status: "active",
    icon: "📊",
  },
  {
    role_key: "SALES_DEVELOPMENT_REP",
    display_name: "Sales Development Rep",
    description: "Lead qualification, outreach preparation, pipeline analysis, and sales enablement.",
    status: "coming_soon",
    icon: "🤝",
  },
  {
    role_key: "FINANCIAL_ANALYST",
    display_name: "Financial Analyst",
    description: "Financial reporting, variance analysis, forecasting, and budget monitoring.",
    status: "coming_soon",
    icon: "💰",
  },
  {
    role_key: "HR_BUSINESS_PARTNER",
    display_name: "HR Business Partner",
    description: "HR analytics, workforce planning, policy guidance, and employee lifecycle support.",
    status: "coming_soon",
    icon: "👥",
  },
  {
    role_key: "CUSTOMER_SUCCESS_MANAGER",
    display_name: "Customer Success Manager",
    description: "Customer health monitoring, churn risk detection, and success playbook execution.",
    status: "coming_soon",
    icon: "⭐",
  },
  {
    role_key: "OPERATIONS_ANALYST",
    display_name: "Operations Analyst",
    description: "Process optimization, bottleneck detection, SLA monitoring, and operational reporting.",
    status: "coming_soon",
    icon: "⚙️",
  },
];

// ── Phase 4 — Integration Manager (Google Search Console & future providers) ──
//
// All requests to /api/v1/integration-manager/** are authenticated by the JWT bearer token, so the
// backend can scope the query to the correct tenant.
// Credentials are NEVER read back from the server — only has_credentials (bool)
// and account_info (safe metadata) are returned.
// ─────────────────────────────────────────────────────────────────────────────

const INT_MGR_BASE = "/api/v1/integration-manager";

// ── Types ─────────────────────────────────────────────────────────────────────

export type IntegrationStatus =
  | "not_configured"
  | "not_tested"
  | "connected"
  | "failed"
  | "disabled";

export interface IntegrationOut {
  id: string;
  tenant_id: string;
  provider_type: string;
  display_name: string;
  status: IntegrationStatus;
  is_enabled: boolean;
  has_credentials: boolean;
  account_info: Record<string, unknown>;
  last_tested_at: string | null;
  error_message: string | null;
  legacy_connection_id: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface IntegrationCreate {
  provider_type: string;
  display_name: string;
  credentials: Record<string, unknown>;
  created_by?: string;
}

export interface IntegrationUpdate {
  display_name?: string;
  credentials?: Record<string, unknown>;
  is_enabled?: boolean;
}

export interface IntegrationTestResponse {
  integration_id: string;
  provider_type: string;
  success: boolean;
  status: IntegrationStatus;
  account_info: Record<string, unknown>;
  error_message: string | null;
  tested_at: string;
}

export interface CapabilityGrantOut {
  id: string;
  tenant_id: string;
  integration_id: string;
  role_key: string;
  capability_key: string;
  is_granted: boolean;
  granted_by: string;
  granted_at: string;
}

export interface CapabilityGrantCreate {
  role_key: string;
  capability_key: string;
  is_granted?: boolean;
  granted_by?: string;
}

export interface ProviderCapabilityOut {
  key: string;
  display_name: string;
  description: string;
  category: string;
  risk_level: string;
  requires_schema_entity: boolean;
}

export interface ProviderCatalogueItem {
  provider_type: string;
  display_name: string;
  description: string;
  icon_hint: string;
  required_credential_fields: string[];
  optional_credential_fields: string[];
  capabilities: ProviderCapabilityOut[];
}

export interface OAuthAuthorizeResponse {
  integration_id: string;
  authorization_url: string;
  state_token: string;
  expires_at: string;
}

// ── Helper: typed fetch to int-manager API with tenant header ─────────────────

async function intMgrFetch<T>(
  method: "GET" | "POST" | "PATCH" | "DELETE",
  path: string,
  body?: unknown,
  _tenantId = "default-tenant", // kept for signature compatibility; apiClient reads from localStorage
): Promise<T> {
  return apiFetch<T>(method, path, body);
}

// ── Provider catalogue ────────────────────────────────────────────────────────

export function useIntegrationProviders() {
  return useQuery<ProviderCatalogueItem[]>({
    queryKey: ["integration-providers"] as const,
    queryFn: () =>
      intMgrFetch<ProviderCatalogueItem[]>("GET", `${INT_MGR_BASE}/providers`),
    staleTime: 300_000, // provider list rarely changes
  });
}

// ── Integrations list ─────────────────────────────────────────────────────────

export function useIntegrations(providerType?: string) {
  const path = providerType
    ? `${INT_MGR_BASE}/integrations?provider_type=${encodeURIComponent(providerType)}`
    : `${INT_MGR_BASE}/integrations`;
  return useQuery<IntegrationOut[]>({
    queryKey: ["integrations", providerType ?? "all"] as const,
    queryFn: () => intMgrFetch<IntegrationOut[]>("GET", path),
    staleTime: 15_000,
  });
}

export function useIntegration(integrationId: string | null) {
  return useQuery<IntegrationOut>({
    queryKey: ["integration", integrationId] as const,
    queryFn: () =>
      intMgrFetch<IntegrationOut>("GET", `${INT_MGR_BASE}/integrations/${integrationId}`),
    enabled: !!integrationId,
    staleTime: 15_000,
  });
}

// ── Create integration ────────────────────────────────────────────────────────

export function useCreateIntegration() {
  const qc = useQueryClient();
  return useMutation<IntegrationOut, Error, IntegrationCreate>({
    mutationFn: (body) =>
      intMgrFetch<IntegrationOut>("POST", `${INT_MGR_BASE}/integrations`, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["integrations"] });
    },
  });
}

// ── Update integration ────────────────────────────────────────────────────────

export function useUpdateIntegration(integrationId: string) {
  const qc = useQueryClient();
  return useMutation<IntegrationOut, Error, IntegrationUpdate>({
    mutationFn: (body) =>
      intMgrFetch<IntegrationOut>("PATCH", `${INT_MGR_BASE}/integrations/${integrationId}`, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["integrations"] });
      void qc.invalidateQueries({ queryKey: ["integration", integrationId] });
    },
  });
}

// ── Delete integration ────────────────────────────────────────────────────────

export function useDeleteIntegration() {
  const qc = useQueryClient();
  return useMutation<unknown, Error, string>({
    mutationFn: (integrationId) =>
      intMgrFetch("DELETE", `${INT_MGR_BASE}/integrations/${integrationId}`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["integrations"] });
    },
  });
}

// ── Test integration ──────────────────────────────────────────────────────────

export function useTestIntegration() {
  const qc = useQueryClient();
  return useMutation<IntegrationTestResponse, Error, string>({
    mutationFn: (integrationId) =>
      intMgrFetch<IntegrationTestResponse>(
        "POST",
        `${INT_MGR_BASE}/integrations/${integrationId}/test`,
      ),
    onSuccess: (_data, integrationId) => {
      void qc.invalidateQueries({ queryKey: ["integrations"] });
      void qc.invalidateQueries({ queryKey: ["integration", integrationId] });
    },
  });
}

// ── Capability grants ─────────────────────────────────────────────────────────

export function useCapabilityGrants(integrationId: string | null) {
  return useQuery<CapabilityGrantOut[]>({
    queryKey: ["capability-grants", integrationId] as const,
    queryFn: () =>
      intMgrFetch<CapabilityGrantOut[]>(
        "GET",
        `${INT_MGR_BASE}/integrations/${integrationId}/grants`,
      ),
    enabled: !!integrationId,
    staleTime: 15_000,
  });
}

export function useCreateCapabilityGrant(integrationId: string) {
  const qc = useQueryClient();
  return useMutation<CapabilityGrantOut[], Error, CapabilityGrantCreate[]>({
    mutationFn: (grants) =>
      intMgrFetch<CapabilityGrantOut[]>(
        "POST",
        `${INT_MGR_BASE}/integrations/${integrationId}/grants`,
        { grants },
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["capability-grants", integrationId] });
    },
  });
}

export function useDeleteCapabilityGrant() {
  const qc = useQueryClient();
  return useMutation<unknown, Error, { grantId: string; integrationId: string }>({
    mutationFn: ({ grantId }) =>
      intMgrFetch("DELETE", `${INT_MGR_BASE}/grants/${grantId}`),
    onSuccess: (_data, { integrationId }) => {
      void qc.invalidateQueries({ queryKey: ["capability-grants", integrationId] });
    },
  });
}

// ── OAuth 2.0 authorize (Phase 4 — Google Search Console) ────────────────────
//
// Returns the backend-generated authorization URL.
// The frontend MUST redirect the browser (window.location.href = authorization_url).
// The state_token is embedded in the URL by the backend; the frontend does NOT
// need to handle or store it.

export function useGscAuthorize() {
  return useMutation<OAuthAuthorizeResponse, Error, void>({
    mutationFn: () =>
      apiClient.get<OAuthAuthorizeResponse>("/api/v1/oauth/google/authorize"),
  });
}

// ── OAuth 2.0 — Google Analytics ─────────────────────────────────────────────
// Same Google OAuth client credentials as GSC; different scope and endpoint.

export function useGaAuthorize() {
  return useMutation<OAuthAuthorizeResponse, Error, void>({
    mutationFn: () =>
      apiClient.get<OAuthAuthorizeResponse>("/api/v1/oauth/google/analytics/authorize"),
  });
}

// ── Requests waiting for integration setup ───────────────────────────────────
// A request that needs an integration which is not set up is saved server-side;
// it is resumed (the original text, not a retyped one) once setup is complete.

export interface PendingTaskFE {
  id: string;
  prompt: string;
  role_name: string;
  status: string;
  blocking_state: string;
  ready: boolean;
  next_action: string;
  action_data: Record<string, unknown>;
  message: string;
  created_at?: string | null;
}

const PENDING_TASKS_KEY = ["pending-tasks"] as const;

export function usePendingTasks() {
  return useQuery<PendingTaskFE[]>({
    queryKey: PENDING_TASKS_KEY,
    queryFn: () => apiClient.get<PendingTaskFE[]>("/api/v1/agent/pending-tasks"),
    enabled: USE_REAL_API,
    refetchInterval: 20_000,
  });
}

/** Admin: approve read-only access for the task's AI role, then it can be resumed. */
export function useAuthorizePendingTask() {
  const qc = useQueryClient();
  return useMutation<PendingTaskFE, Error, string>({
    mutationFn: (id) => apiClient.post<PendingTaskFE>(`/api/v1/agent/pending-tasks/${id}/authorize`, {}),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: PENDING_TASKS_KEY }); },
  });
}

/** Admin: choose which property (Search Console site) the task reports on. */
export function useSelectPendingTaskProperty() {
  const qc = useQueryClient();
  return useMutation<PendingTaskFE, Error, { id: string; propertyId: string }>({
    mutationFn: ({ id, propertyId }) =>
      apiClient.post<PendingTaskFE>(`/api/v1/agent/pending-tasks/${id}/select-property`, { property_id: propertyId }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: PENDING_TASKS_KEY }); },
  });
}

export function useResumePendingTask() {
  const qc = useQueryClient();
  return useMutation<AgentExecutionResponse, Error, string>({
    mutationFn: async (id) => {
      try {
        return await apiClient.post<AgentExecutionResponse>(`/api/v1/agent/pending-tasks/${id}/resume`, {});
      } catch (err) {
        // 409 carries the next setup step in `detail.message`; show that, not "status 409".
        const detail = (err as { body?: { detail?: unknown } }).body?.detail;
        if (detail && typeof detail === "object" && "message" in detail) {
          throw new Error(String((detail as { message: unknown }).message));
        }
        throw err;
      }
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: PENDING_TASKS_KEY });
      void qc.invalidateQueries({ queryKey: queryKeys.activity });
    },
  });
}

export function useCancelPendingTask() {
  const qc = useQueryClient();
  return useMutation<PendingTaskFE, Error, string>({
    mutationFn: (id) => apiClient.post<PendingTaskFE>(`/api/v1/agent/pending-tasks/${id}/cancel`, {}),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: PENDING_TASKS_KEY }); },
  });
}

// ── NL Integration hooks ──────────────────────────────────────────────────────

export interface NLIntegrationRequest {
  instruction: string;
  requested_by?: string;
}

export interface IntegrationIntent {
  intent_type: string;
  provider_type: string | null;
  requested_capabilities: string[];
  target_role_key: string | null;
  display_name: string | null;
  reasoning: string;
  confidence: number;
  missing_information: string[];
}

export interface NLConversationResponse {
  conversation_id: string;
  reply: string;
  intent: IntegrationIntent | null;
  next_action: string;
  action_data: Record<string, unknown>;
  available_providers: Array<{ provider_type: string; display_name: string; description: string }>;
}

export function useNLIntegrationChat() {
  return useMutation<NLConversationResponse, Error, { message: string; conversation_id?: string }>({
    mutationFn: (body) =>
      intMgrFetch<NLConversationResponse>("POST", "/api/v1/nl-integration/chat", body),
  });
}

export function useNLIntegrationParse() {
  return useMutation<IntegrationIntent, Error, NLIntegrationRequest>({
    mutationFn: (body) =>
      intMgrFetch<IntegrationIntent>("POST", "/api/v1/nl-integration/parse", body),
  });
}

// ── Employee Builder hooks ────────────────────────────────────────────────────

export interface EmployeeBlueprintProposal {
  id: string;
  tenant_id: string;
  name: string;
  role_key: string;
  purpose: string;
  responsibilities: string[];
  objectives: string[];
  required_capabilities: Array<{
    provider_type: string;
    capability_key: string;
    reason: string;
    is_available: boolean;
    integration_id: string | null;
  }>;
  missing_integrations: Array<{
    provider_type: string;
    display_name: string;
    reason: string;
    required_capabilities: string[];
  }>;
  allowed_tools: string[];
  guarded_tools: string[];
  suggested_schedule: string | null;
  communication_style: string;
  llm_model: string;
  system_persona: string;
  approval_status: "pending" | "approved" | "rejected";
  created_by: string;
  created_at: string;
  reviewed_by: string | null;
  review_note: string | null;
}

export interface EmployeeOut {
  id: string;
  tenant_id: string;
  role_key: string;
  name: string;
  status: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export function useBuildEmployee() {
  const qc = useQueryClient();
  return useMutation<EmployeeBlueprintProposal, Error, { instruction: string; requested_by?: string }>({
    mutationFn: (body) =>
      intMgrFetch<EmployeeBlueprintProposal>("POST", "/api/v1/employees/build", body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["employee-blueprints"] });
    },
  });
}

export function useEmployeeBlueprints() {
  return useQuery<EmployeeBlueprintProposal[]>({
    queryKey: ["employee-blueprints"] as const,
    queryFn: () => intMgrFetch<EmployeeBlueprintProposal[]>("GET", "/api/v1/employees/blueprints"),
    staleTime: 15_000,
  });
}

export function useApproveBlueprint() {
  const qc = useQueryClient();
  return useMutation<EmployeeOut, Error, { proposal_id: string; reviewed_by: string; review_note?: string }>({
    mutationFn: ({ proposal_id, ...body }) =>
      intMgrFetch<EmployeeOut>("POST", `/api/v1/employees/blueprints/${proposal_id}/approve`, {
        decision: "approve",
        ...body,
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["employee-blueprints"] });
      void qc.invalidateQueries({ queryKey: ["employees"] });
    },
  });
}

export function useRejectBlueprint() {
  const qc = useQueryClient();
  return useMutation<EmployeeBlueprintProposal, Error, { proposal_id: string; reviewed_by: string; review_note?: string }>({
    mutationFn: ({ proposal_id, ...body }) =>
      intMgrFetch<EmployeeBlueprintProposal>("POST", `/api/v1/employees/blueprints/${proposal_id}/reject`, {
        decision: "reject",
        ...body,
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["employee-blueprints"] });
    },
  });
}

export function useEmployees() {
  return useQuery<EmployeeOut[]>({
    queryKey: ["employees"] as const,
    queryFn: () => intMgrFetch<EmployeeOut[]>("GET", "/api/v1/employees"),
    staleTime: 15_000,
  });
}

// ── Workflow hooks ────────────────────────────────────────────────────────────

export interface WorkflowStep {
  step_index: number;
  step_type: string;
  description: string;
  tool_name?: string | null;
  action_key?: string | null;
  arguments?: Record<string, unknown>;
  depends_on?: number[];
  requires_approval?: boolean;
  timeout_seconds?: number;
}

export interface WorkflowOut {
  id: string;
  tenant_id: string;
  ai_employee_id: string | null;
  name: string;
  description: string;
  trigger: string;
  schedule_cron: string | null;
  steps: WorkflowStep[];
  is_enabled: boolean;
  status: string;
  last_run_at: string | null;
  last_run_status: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
  role_name?: string | null;
  timezone?: string;
  max_retries?: number;
  retry_delay_minutes?: number;
}

export interface WorkflowCreate {
  name: string;
  description?: string;
  trigger: "manual" | "scheduled" | "event";
  schedule_cron?: string | null;
  steps?: WorkflowStep[];
  ai_employee_id?: string | null;
  is_enabled?: boolean;
  created_by?: string;
  role_name?: string | null;
  timezone?: string;
  max_retries?: number;
  retry_delay_minutes?: number;
}

/** One execution attempt of a workflow (history). Status is the real outcome. */
export interface WorkflowRunFE {
  id: string;
  workflow_id: string;
  trigger: "manual" | "scheduled" | "retry";
  attempt: number;
  status: "queued" | "running" | "completed" | "failed" | "awaiting_approval" | "waiting_setup" | "skipped" | "cancelled";
  plan_id: string | null;
  pending_task_id: string | null;
  detail: string;
  not_before: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
}

export function useWorkflowRuns(workflowId: string, enabled: boolean) {
  return useQuery<WorkflowRunFE[]>({
    queryKey: ["workflow-runs", workflowId] as const,
    queryFn: () => intMgrFetch<WorkflowRunFE[]>("GET", `/api/v1/workflows/${workflowId}/runs`),
    enabled,
    staleTime: 5_000,
  });
}

export function useCancelWorkflowRun(workflowId: string) {
  const qc = useQueryClient();
  return useMutation<WorkflowRunFE, Error, string>({
    mutationFn: (runId) => intMgrFetch<WorkflowRunFE>("POST", `/api/v1/workflows/${workflowId}/runs/${runId}/cancel`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["workflow-runs", workflowId] });
      void qc.invalidateQueries({ queryKey: ["workflows"] });
    },
  });
}

export function useWorkflows() {
  return useQuery<WorkflowOut[]>({
    queryKey: ["workflows"] as const,
    queryFn: () => intMgrFetch<WorkflowOut[]>("GET", "/api/v1/workflows"),
    staleTime: 15_000,
  });
}

export function useCreateWorkflow() {
  const qc = useQueryClient();
  return useMutation<WorkflowOut, Error, WorkflowCreate>({
    mutationFn: (body) => intMgrFetch<WorkflowOut>("POST", "/api/v1/workflows", body),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["workflows"] }); },
  });
}

export function useUpdateWorkflow(workflowId: string) {
  const qc = useQueryClient();
  return useMutation<WorkflowOut, Error, Partial<WorkflowCreate>>({
    mutationFn: (body) => intMgrFetch<WorkflowOut>("PATCH", `/api/v1/workflows/${workflowId}`, body),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["workflows"] }); },
  });
}

/** Update a workflow identified by the mutation variables (useful in row actions). */
export function usePatchWorkflow() {
  const qc = useQueryClient();
  return useMutation<WorkflowOut, Error, { workflowId: string; patch: Partial<WorkflowCreate> }>({
    mutationFn: ({ workflowId, patch }) =>
      intMgrFetch<WorkflowOut>("PATCH", `/api/v1/workflows/${workflowId}`, patch),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["workflows"] }); },
  });
}

export function useDeleteWorkflow() {
  const qc = useQueryClient();
  return useMutation<unknown, Error, string>({
    mutationFn: (id) => intMgrFetch("DELETE", `/api/v1/workflows/${id}`),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["workflows"] }); },
  });
}

export function useTriggerWorkflow() {
  const qc = useQueryClient();
  return useMutation<{ workflow_id: string; status: string; message: string; plan_id: string | null }, Error, string>({
    mutationFn: (id) =>
      intMgrFetch("POST", `/api/v1/workflows/${id}/trigger`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["workflows"] });
      void qc.invalidateQueries({ queryKey: ["workflow-runs"] });
    },
  });
}

// ── Approval Center hooks ─────────────────────────────────────────────────────

export interface ApprovalRequestOut {
  id: string;
  tenant_id: string;
  action: string;
  detail: string;
  status: "pending" | "approved" | "rejected";
  requested_by: string;
  reviewed_by: string | null;
  review_note: string | null;
  created_at: string;
  resolved_at: string | null;
}

export function useApprovalRequests(status?: string) {
  const path = status
    ? `/api/v1/approvals?status=${encodeURIComponent(status)}`
    : "/api/v1/approvals";
  return useQuery<ApprovalRequestOut[]>({
    queryKey: ["approvals", status ?? "all"] as const,
    queryFn: () => intMgrFetch<ApprovalRequestOut[]>("GET", path),
    staleTime: 10_000,
    refetchInterval: 15_000, // poll for new approvals
  });
}

export function useDecideApproval() {
  const qc = useQueryClient();
  return useMutation<
    ApprovalRequestOut,
    Error,
    { approval_id: string; decision: "approved" | "rejected"; reviewed_by: string; review_note?: string }
  >({
    mutationFn: ({ approval_id, ...body }) =>
      intMgrFetch<ApprovalRequestOut>("POST", `/api/v1/approvals/${approval_id}/decide`, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["approvals"] });
    },
  });
}


// ── Admin AI Customization ────────────────────────────────────────────────────

export interface CustomizationOperation {
  type:
    | "CREATE_AI_EMPLOYEE"
    | "UPDATE_AI_EMPLOYEE"
    | "CONNECT_INTEGRATION"
    | "GRANT_CAPABILITY"
    | "REVOKE_CAPABILITY"
    | "CREATE_WORKFLOW"
    | "UPDATE_WORKFLOW"
    | "SET_APPROVAL_POLICY";
  description: string;
  params: Record<string, unknown>;
  requires_confirmation: boolean;
  order: number;
}

export interface CustomizationPlan {
  summary: string;
  operations: CustomizationOperation[];
  missing_information: string[];
  requires_confirmation: boolean;
}

export interface OperationResult {
  type: string;
  description: string;
  status: "success" | "failed" | "skipped";
  detail: string;
  created_id: string | null;
}

export interface AdminCustomizationResult {
  plan_summary: string;
  operations_total: number;
  operations_succeeded: number;
  operations_failed: number;
  results: OperationResult[];
  executed_at: string;
  executed_by: string;
  audit_id: string;
}

export function useGenerateCustomizationPlan() {
  return useMutation<CustomizationPlan, Error, { instruction: string; requested_by?: string }>({
    mutationFn: (body) =>
      intMgrFetch<CustomizationPlan>("POST", "/api/v1/admin/customize/plan", body),
  });
}

export function useExecuteCustomizationPlan() {
  const qc = useQueryClient();
  return useMutation<
    AdminCustomizationResult,
    Error,
    { plan: CustomizationPlan; confirmed_by: string }
  >({
    mutationFn: (body) =>
      intMgrFetch<AdminCustomizationResult>("POST", "/api/v1/admin/customize/execute", body),
    onSuccess: () => {
      // Invalidate related queries after execution
      void qc.invalidateQueries({ queryKey: ["employees"] });
      void qc.invalidateQueries({ queryKey: ["integrations"] });
      void qc.invalidateQueries({ queryKey: ["workflows"] });
    },
  });
}
