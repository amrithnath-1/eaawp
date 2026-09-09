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
import { apiClient, USE_REAL_API } from "@/lib/api-client";
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
        ? apiClient.get<LibraryItem[]>("/api/v1/library")
        : Promise.resolve(knowledgeService.items()),
    staleTime: 60_000,
  });
}

export function useKnowledgeStatus() {
  return useQuery<KnowledgeStatus>({
    queryKey: queryKeys.knowledgeStatus,
    queryFn: () =>
      USE_REAL_API
        ? apiClient.get<KnowledgeStatus>("/api/v1/library/status")
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
        ? apiClient.get<RecentItem[]>("/api/v1/recents")
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
        ? apiClient.get<MailMessage[]>("/api/v1/mail")
        : Promise.resolve(mailService.thread()),
    staleTime: 10_000,
  });
}

// ── Chat / agent execute ──────────────────────────────────────────────────────

interface AgentExecutionRequest {
  user_prompt: string;
  session_id?: string;
}

interface AgentExecutionResponse {
  message: string;
  tool_calls?: Array<{ name: string; args: Record<string, unknown> }>;
  sources?: string[];
  requires_approval?: boolean;
  session_id: string;
}

/**
 * Mutation for sending a prompt to the agent.
 * When VITE_USE_REAL_API=false, the mutation resolves immediately with a
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
                `In production this calls the FastAPI backend at ${import.meta.env.VITE_API_BASE_URL}/api/v1/agent/execute. ` +
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
