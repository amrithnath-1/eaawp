/**
 * Project Manager AI employee (ported from Vyuham): data hooks for /api/v1/pm.
 * Every figure comes from the server's deterministic engine; the server applies the access rules
 * (administrators, a project's named managers, team members on their own work).
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { API_BASE_URL, apiClient, apiErrorMessage } from "@/lib/api-client";

const PM = "/api/v1/pm";

// ── types (only the fields the screens use) ───────────────────────────────────
export interface PmMe { is_admin: boolean; employee_id: string | null; employee_name: string | null; manages: string[]; ai: PmAi }
export interface PmAi { configured: boolean; model: string | null; setup: string | null }
export interface PmBands { verified: number; in_progress: number; blocked: number; pending: number }
export interface PmProgress {
  project_id: string; name: string; status: string; priority: string; bands_pct: PmBands; completion_pct: number;
  method: string; deadline: string; days_remaining: number; expected_pct_by_schedule: number; health: string;
  current_milestone: string | null; milestones: Array<{ name: string; done: number; total: number }>;
  objective?: string; stage?: string; stage_label?: string;
  reported_by_manager?: { reported_pct: number; note: string; reported_by: string; created_at: string } | null;
}
export interface PmTask {
  id: string; project_id: string; title: string; description: string; required_skills: Record<string, string>;
  estimated_hours: number; priority: string; deadline_days: number; dependencies: string[]; status: string;
  assigned_to: string | null; owner_name?: string | null; progress_pct: number; blocked: boolean; blocked_reason?: string | null;
  phase?: string | null; milestone?: string | null; acceptance_criteria?: string[];
  why_me?: string | null; suitability_score?: number | null; dependency_status?: Array<{ task_id: string; status: string }>;
}
export interface PmProjectDetail {
  project: { id: string; name: string; business_objective: string; priority: string; deadline_days: number; status: string; manager_usernames: string[]; start_date: string };
  progress: PmProgress; tasks: PmTask[]; critical_path: { path: string[]; total_hours: number };
  stage: string; stage_label: string; can_manage: boolean;
}
export interface PmEmployeeScore {
  employee_id: string; name: string; department: string; designation: string; status: string; email?: string;
  skill_score: number; performance_score: number; availability_score: number; workload_score: number;
  collaboration_score: number; free_capacity_hrs: number; level: string;
}
export interface PmApproval {
  approval_id: string; kind: string; task_id: string; task_title: string; priority: string; previous_owner: string | null;
  recommended_new_owner_id: string | null; recommended_new_owner_name: string | null; suitability_score: number;
  post_utilization_pct: number; explanation: string; status: string; created_at: string; decided_by?: string | null; manager_comments?: string | null;
}
export interface PmSummary {
  total_employees: number; total_tasks: number; workload_gini_index: number; overloaded_count: number; on_leave_count: number;
  team_free_hrs: number; employees: PmEmployeeScore[]; tasks: PmTask[]; pending_approvals: PmApproval[]; decided_approvals: PmApproval[];
  change_requests: PmChangeRequest[]; pending_skill_requests: number; ledger_status: { valid: boolean; entries?: number }; ai: PmAi;
  weights: Record<string, number>;
}
export interface PmChangeRequest { id: string; employee_id: string; kind: string; task_id: string | null; details: string; status: string; created_at: string; note?: string }
export interface PmDocument { id: string; filename: string; version: number; size: number; status: string; error: string | null; is_current: boolean; chunk_count: number; suspicious_count: number; uploaded_by: string; uploaded_at: string | null }
export interface PmAuditEntry { id: string; timestamp: string; actor: string; action: string; entity_id: string; sha256_proof: string }
export interface PmCandidate { employee_id: string; employee_name: string; designation: string; eligible: boolean; suitability_score: number; utilization_after_pct: number; hard_violations?: string[]; warnings?: string[]; factor_breakdown: Record<string, number> }

// ── plumbing ─────────────────────────────────────────────────────────────────
export const pmError = apiErrorMessage;

export function usePm<T>(path: string | null, opts: { refetch?: number } = {}) {
  return useQuery<T>({
    queryKey: ["pm", path] as const, enabled: !!path, retry: false,
    ...(opts.refetch ? { refetchInterval: opts.refetch } : {}),
    queryFn: () => apiClient.get<T>(`${PM}${path}`),
  });
}

type Method = "POST" | "PUT" | "PATCH" | "DELETE";
export function usePmAction<V = void, R = unknown>(method: Method, path: (v: V) => string, body?: (v: V) => unknown) {
  const qc = useQueryClient();
  return useMutation<R, Error, V>({
    mutationFn: (v) => {
      const p = `${PM}${path(v)}`;
      const b = body ? body(v) : {};
      if (method === "DELETE") return apiClient.delete<R>(p);
      if (method === "PUT") return apiClient.put<R>(p, b);
      if (method === "PATCH") return apiClient.patch<R>(p, b);
      return apiClient.post<R>(p, b);
    },
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["pm"] }),
  });
}

/** Multipart upload (documents, résumés, minutes, team import). */
export function usePmUpload<R = unknown>(path: string, field = "files") {
  const qc = useQueryClient();
  return useMutation<R, Error, { files: File[]; extra?: Record<string, string> }>({
    mutationFn: async ({ files, extra }) => {
      const fd = new FormData();
      files.forEach((f) => fd.append(field, f));
      Object.entries(extra ?? {}).forEach(([k, v]) => fd.append(k, v));
      const token = window.localStorage.getItem("eaawp.access_token");
      const res = await fetch(`${API_BASE_URL}${PM}${path}`, { method: "POST", headers: token ? { Authorization: `Bearer ${token}` } : {}, body: fd });
      if (!res.ok) {
        const b = await res.json().catch(() => ({ detail: res.statusText }));
        const d = (b as Record<string, unknown>)["detail"];
        throw new Error(typeof d === "string" ? d : res.statusText);
      }
      return res.json() as Promise<R>;
    },
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["pm"] }),
  });
}

/** CSV exports (authenticated download). */
export async function pmDownload(path: string, filename: string) {
  const token = window.localStorage.getItem("eaawp.access_token");
  const res = await fetch(`${API_BASE_URL}${PM}${path}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (!res.ok) throw new Error("The export could not be downloaded");
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url; a.download = filename; a.click();
  URL.revokeObjectURL(url);
}
