/**
 * History (saved AI employee conversations), the selected AI employee's real tool status, and the approved company
 * profile. All data comes from the backend; nothing here is mocked or counted on the client.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient, USE_REAL_API } from "@/lib/api-client";

// ── Conversations ─────────────────────────────────────────────────────────────

export interface ConversationSummary {
  id: string;
  title: string;
  role_key: string;
  role_name: string;
  created_at: string;
  updated_at: string;
  message_count: number;
}

export interface IntegrationActionMeta {
  next_action: string;
  action_data: Record<string, unknown> & { provider_type?: string; integration_id?: string };
}

export interface ConversationMessage {
  id: string;
  sender: "user" | "assistant";
  content: string;
  created_at: string;
  plan_id: string | null;
  sources?: string[];
  plan_status?: string | null;
  step_summaries?: string[];
  requires_approval?: boolean;
  pending_task_id?: string | null;
  integration_action?: IntegrationActionMeta;
  error?: boolean;
}

export interface ConversationDetail {
  id: string;
  title: string;
  role_key: string;
  role_name: string;
  created_at: string;
  updated_at: string;
  messages: ConversationMessage[];
  has_more: boolean;
}

export const conversationKeys = {
  all: ["conversations"] as const,
  list: (roleKey: string | null, q: string) =>
    ["conversations", "list", roleKey ?? "all", q] as const,
  detail: (id: string) => ["conversations", "detail", id] as const,
};

export function useConversations(roleKey: string | null, q: string) {
  return useQuery({
    queryKey: conversationKeys.list(roleKey, q),
    enabled: USE_REAL_API,
    placeholderData: keepPreviousData,
    queryFn: ({ signal }) => {
      const params = new URLSearchParams({ limit: "50" });
      if (roleKey) params.set("role_key", roleKey);
      if (q.trim()) params.set("q", q.trim());
      return apiClient.get<{ items: ConversationSummary[]; has_more: boolean }>(
        `/api/v1/conversations?${params}`,
        signal,
      );
    },
    staleTime: 10_000,
  });
}

export function useConversation(id: string | null) {
  return useQuery({
    queryKey: conversationKeys.detail(id ?? ""),
    enabled: USE_REAL_API && !!id,
    queryFn: ({ signal }) =>
      apiClient.get<ConversationDetail>(`/api/v1/conversations/${id}?limit=60`, signal),
    staleTime: 5_000,
  });
}

/** Older messages of a conversation, loaded on request (the first page is the newest one). */
export function fetchOlderMessages(id: string, before: string) {
  return apiClient.get<ConversationDetail>(
    `/api/v1/conversations/${id}?limit=60&before=${encodeURIComponent(before)}`,
  );
}

export function useRenameConversation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, title }: { id: string; title: string }) =>
      apiClient.patch<{ id: string; title: string }>(`/api/v1/conversations/${id}`, { title }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: conversationKeys.all }),
  });
}

export function useDeleteConversation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiClient.delete<void>(`/api/v1/conversations/${id}`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: conversationKeys.all }),
  });
}

// ── Tool status of the selected AI employee ──────────────────────────────────

export type ToolState =
  | "available"
  | "requires_approval"
  | "disabled"
  | "not_implemented"
  | "integration_not_connected"
  | "integration_disabled"
  | "blocked_high_risk"
  | "capability_missing";

export interface ToolEntry {
  key: string;
  name: string;
  source: "built_in" | "integration";
  kind: "read" | "action";
  description: string;
  status: ToolState;
  status_label: string;
  risk_level?: string | null;
  integration?: {
    id: string;
    provider_type: string;
    name: string;
    status: string;
    enabled: boolean;
  };
}

export interface WorkspaceTools {
  role_key: string | null;
  role_name?: string;
  tools: ToolEntry[];
  counts: {
    total?: number;
    available?: number;
    requires_approval?: number;
    blocked?: number;
    integration_available?: number;
  };
  approvals: { pending?: number; can_decide?: boolean };
  operations: {
    window_days?: number;
    scope?: "company" | "mine";
    running?: number;
    awaiting_approval?: number;
    completed?: number;
    failed?: number;
    cancelled?: number;
  };
}

export function useWorkspaceTools(roleKey: string | null | undefined) {
  return useQuery({
    queryKey: ["workspace-tools", roleKey ?? "none"] as const,
    enabled: USE_REAL_API && !!roleKey,
    queryFn: ({ signal }) => apiClient.get<WorkspaceTools>("/api/v1/workspace/tools", signal),
    staleTime: 15_000,
    refetchInterval: 30_000,
  });
}

// ── Approved company profile ──────────────────────────────────────────────────

export interface ServiceEntry {
  name: string;
  description: string;
  audience: string;
}

export interface CompanyProfile {
  brand_name: string;
  legal_or_long_name: string;
  tagline: string;
  website: string;
  summary: string;
  location_and_service_area: string;
  services: ServiceEntry[];
  target_audiences: string[];
  brand_voice: string;
  approved_claims: string[];
  forbidden_claims: string[];
  marketing_objectives: string[];
  kpis: string[];
  policies: string;
}

export interface CompanyProfileState {
  profile: CompanyProfile;
  updated_at: string | null;
  updated_by: string | null;
  is_empty: boolean;
}

export function useCompanyProfile() {
  return useQuery({
    queryKey: ["company-profile"] as const,
    enabled: USE_REAL_API,
    queryFn: ({ signal }) => apiClient.get<CompanyProfileState>("/api/v1/company-profile", signal),
  });
}

export function useSaveCompanyProfile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (profile: CompanyProfile) =>
      apiClient.put<CompanyProfileState>("/api/v1/company-profile", profile),
    onSuccess: (data) => qc.setQueryData(["company-profile"], data),
  });
}

// ── Activity / Tasks / Insights of the selected AI employee ──────────────────

export interface FeedItem {
  id: string;
  at: string | null;
  kind: string;
  status: string;
  title: string;
  detail: string;
  sources?: string[];
}

export interface Feed {
  role_key: string | null;
  scope?: "company" | "mine";
  items: FeedItem[];
}

export function useWorkspaceFeed(kind: "activity" | "tasks" | "insights") {
  return useQuery({
    queryKey: ["workspace-feed", kind] as const,
    enabled: USE_REAL_API,
    queryFn: ({ signal }) => apiClient.get<Feed>(`/api/v1/workspace/feed/${kind}`, signal),
    staleTime: 10_000,
    refetchInterval: 30_000,
  });
}
