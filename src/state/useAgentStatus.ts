import { useEffect, useState } from "react";
import type { AgentStatus } from "@/services/types";
import { USE_REAL_API } from "@/lib/api-client";

const CYCLE: { status: AgentStatus; ms: number }[] = [
  { status: "MONITORING", ms: 7000 },
  { status: "ANALYZING", ms: 6000 },
  { status: "COMMUNICATING", ms: 6000 },
  { status: "EXECUTING", ms: 6000 },
  { status: "WAITING_FOR_APPROVAL", ms: 8000 },
];

export const STATUS_LABEL: Record<AgentStatus, string> = {
  MONITORING: "Monitoring",
  ANALYZING: "Analyzing",
  EXECUTING: "Executing",
  COMMUNICATING: "Communicating",
  WAITING_FOR_APPROVAL: "Needs approval",
  SCHEDULED: "Scheduled",
  IDLE: "Idle",
  ERROR: "Error",
};

/** Only animate the sample lifecycle in demo mode; live mode stays truthful until a run reports status. */
export function useAgentStatus() {
  const [index, setIndex] = useState(0);

  useEffect(() => {
    if (USE_REAL_API) return;
    const t = setTimeout(() => setIndex((i) => (i + 1) % CYCLE.length), (CYCLE[index]?.ms ?? 6000));
    return () => clearTimeout(t);
  }, [index]);

  const status = USE_REAL_API ? "IDLE" : CYCLE[index]?.status ?? "MONITORING";
  return { status, label: STATUS_LABEL[status] };
}
