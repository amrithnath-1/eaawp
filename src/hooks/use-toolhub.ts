/**
 * Tool Center (administrators only). Contract: backend/docs/TOOLHUB_API.md.
 * Every value comes from the backend; nothing here is mocked. Queries only run against the real API.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient, USE_REAL_API } from "@/lib/api-client";

// ── Types ────────────────────────────────────────────────────────────────────

export type ToolSource = "mcp" | "generated";
export type ToolStatus = "active" | "removed" | "deactivated" | "rejected";
export type RiskClass =
  | "read_only"
  | "internal_compute"
  | "internal_modify"
  | "external_comm"
  | "financial"
  | "security_sensitive";
export type ToolPolicy = "automatic" | "governed" | "approval" | "explicit_approval" | "blocked";
export type ToolValidation = "discovered" | "active" | "rejected" | "superseded" | "none";

export interface RegistryMetrics {
  total: number | null;
  success_rate: number | null;
  avg_ms: number | null;
  degraded: boolean | null;
  last_failure: string | null;
}

export interface RegistryTool {
  id: string;
  key: string;
  name: string;
  description: string;
  source: ToolSource;
  server: string | null;
  integration_id: string | null;
  version: number;
  status: ToolStatus;
  risk_class: RiskClass;
  policy: ToolPolicy;
  roles: string[];
  role_names: string[];
  validation: ToolValidation;
  updated_at: string;
  last_seen_at: string | null;
  metrics: RegistryMetrics;
}

export interface RegistryResponse {
  tools: RegistryTool[];
  roles: Record<string, string>;
}

export type ExecutionStatus = "success" | "failed" | "blocked";
export type ErrorCategory =
  | "timeout"
  | "auth"
  | "permission"
  | "rate_limit"
  | "unavailable"
  | "not_found"
  | "invalid_args"
  | "schema_mismatch"
  | "malformed_output"
  | "policy_blocked"
  | "execution_error";

export interface ToolExecution {
  id: string;
  tool_key: string;
  tool_label: string;
  source: "builtin" | "integration" | "mcp" | "generated" | "internet" | "action" | "meta";
  role: string;
  plan_id: string | null;
  status: ExecutionStatus;
  error_category: ErrorCategory | null;
  error: string | null;
  duration_ms: number;
  retries: number;
  recovery: string | null;
  input: string;
  output: string;
  started_at: string;
}

export interface CapabilityRequest {
  at: string;
  actor: string;
  need: string;
  role: string;
  decision: "reuse" | "build";
  candidates: string[];
}

export interface ValidationCheck {
  check: string;
  passed: boolean;
  detail: string;
}

export interface ValidationAttempt {
  attempt: number;
  passed: boolean;
  report: ValidationCheck[];
}

export interface GeneratedToolVersion {
  version: number;
  status: "active" | "superseded" | "rolled_back" | "rejected";
  purpose: string;
  created_at: string;
  created_by: string;
  code: string;
  input_schema: Record<string, unknown>;
  output_schema: Record<string, unknown>;
  dependencies: string[];
  attempts: ValidationAttempt[];
}

export interface GeneratedTool {
  id: string;
  key: string;
  name: string;
  description: string;
  status: "active" | "deactivated" | "rejected";
  current_version: number;
  created_by: string;
  created_at: string;
  versions: GeneratedToolVersion[];
}

export interface BuilderResponse {
  requests: CapabilityRequest[];
  tools: GeneratedTool[];
}

export interface McpDiscovery {
  at: string;
  tool_count: number;
  error: string | null;
  duration_ms: number;
  added: string[];
  removed: string[];
  changed: string[];
}

export interface McpServerHealth {
  integration_id: string;
  name: string;
  status: string;
  enabled: boolean;
  last_checked: string | null;
  error: string | null;
  discoveries: number;
  failed_discoveries: number;
  last_discovery: McpDiscovery | null;
}

export interface ToolHealth {
  tool_key: string;
  label: string;
  total: number;
  success: number;
  failed: number;
  success_rate: number;
  avg_ms: number;
  timeouts: number;
  retries: number;
  degraded: boolean;
  errors: Record<string, number>;
  last_success: string | null;
  last_failure: string | null;
  last_error: string | null;
}

export interface TrendDay {
  day: string;
  success: number;
  failed: number;
  avg_ms: number;
}

export interface RecoveryAttempt {
  tool_key: string;
  at: string;
  status: string;
  retries: number;
  recovery: string;
  error_category: string;
}

export interface HealthResponse {
  servers: McpServerHealth[];
  tools: ToolHealth[];
  trend: TrendDay[];
  recoveries: RecoveryAttempt[];
}

export type AuditKind =
  | "discovered"
  | "schema_changed"
  | "removed"
  | "generated"
  | "validated"
  | "rejected"
  | "registered"
  | "granted"
  | "revoked"
  | "deactivated"
  | "activated"
  | "rolled_back"
  | "capability_request";

export interface ToolAuditEvent {
  id: string;
  at: string;
  kind: AuditKind;
  actor: string;
  tool_id: string | null;
  detail: string;
}

// ── Queries ──────────────────────────────────────────────────────────────────

const BASE = "/api/v1/toolhub";

export const toolhubKeys = {
  all: ["toolhub"] as const,
  registry: () => ["toolhub", "registry"] as const,
  executions: (status: string, tool: string) => ["toolhub", "executions", status, tool] as const,
  builder: () => ["toolhub", "builder"] as const,
  health: () => ["toolhub", "health"] as const,
  audit: () => ["toolhub", "audit"] as const,
};

export function useToolRegistry(enabled = true) {
  return useQuery({
    queryKey: toolhubKeys.registry(),
    enabled: USE_REAL_API && enabled,
    queryFn: ({ signal }) => apiClient.get<RegistryResponse>(`${BASE}/registry`, signal),
    staleTime: 15_000,
  });
}

export function useToolExecutions(filters: { status: string; tool: string }, enabled = true) {
  return useQuery({
    queryKey: toolhubKeys.executions(filters.status, filters.tool),
    enabled: USE_REAL_API && enabled,
    queryFn: ({ signal }) => {
      const params = new URLSearchParams({ limit: "100" });
      if (filters.status) params.set("status", filters.status);
      if (filters.tool) params.set("tool", filters.tool);
      return apiClient.get<{ executions: ToolExecution[] }>(`${BASE}/executions?${params}`, signal);
    },
    staleTime: 10_000,
  });
}

export function useToolBuilder(enabled = true) {
  return useQuery({
    queryKey: toolhubKeys.builder(),
    enabled: USE_REAL_API && enabled,
    queryFn: ({ signal }) => apiClient.get<BuilderResponse>(`${BASE}/builder`, signal),
    staleTime: 15_000,
  });
}

export function useToolHealth(enabled = true) {
  return useQuery({
    queryKey: toolhubKeys.health(),
    enabled: USE_REAL_API && enabled,
    queryFn: ({ signal }) => apiClient.get<HealthResponse>(`${BASE}/health`, signal),
    staleTime: 15_000,
  });
}

export function useToolAudit(enabled = true) {
  return useQuery({
    queryKey: toolhubKeys.audit(),
    enabled: USE_REAL_API && enabled,
    queryFn: ({ signal }) =>
      apiClient.get<{ events: ToolAuditEvent[] }>(`${BASE}/audit?limit=200`, signal),
    staleTime: 15_000,
  });
}

// ── Actions ──────────────────────────────────────────────────────────────────

function useToolhubMutation<V, R = { ok: boolean }>(fn: (v: V) => Promise<R>) {
  const qc = useQueryClient();
  return useMutation<R, Error, V>({
    mutationFn: fn,
    onSuccess: () => void qc.invalidateQueries({ queryKey: toolhubKeys.all }),
  });
}

export function useGrantTool() {
  return useToolhubMutation(({ id, role_key }: { id: string; role_key: string }) =>
    apiClient.post<{ ok: boolean }>(`${BASE}/tools/${id}/grant`, { role_key }),
  );
}

export function useRevokeTool() {
  return useToolhubMutation(({ id, role_key }: { id: string; role_key: string }) =>
    apiClient.post<{ ok: boolean }>(`${BASE}/tools/${id}/revoke`, { role_key }),
  );
}

export function useSetToolActive() {
  return useToolhubMutation(({ id, active }: { id: string; active: boolean }) =>
    apiClient.post<{ ok: boolean }>(
      `${BASE}/tools/${id}/${active ? "activate" : "deactivate"}`,
      {},
    ),
  );
}

export function useRollbackTool() {
  return useToolhubMutation(({ id, version }: { id: string; version: number }) =>
    apiClient.post<{ ok: boolean }>(`${BASE}/tools/${id}/rollback`, { version }),
  );
}

export function useRefreshMcp() {
  return useToolhubMutation((integrationId: string) =>
    apiClient.post<{ tool_count: number; refreshed: boolean }>(
      `${BASE}/mcp/${integrationId}/refresh`,
      {},
    ),
  );
}
