import { useEffect, useRef, useState } from "react";
import { useNavigate } from "@tanstack/react-router";
import type { AgentStatus } from "@/services/types";
import { blobPath } from "./blob";
import { cn } from "@/lib/utils";

const ENERGY: Record<AgentStatus, number> = {
  IDLE: 0.15,
  MONITORING: 0.3,
  SCHEDULED: 0.25,
  ANALYZING: 0.6,
  EXECUTING: 0.75,
  COMMUNICATING: 0.7,
  WAITING_FOR_APPROVAL: 0.22,
  ERROR: 0.9,
};

/**
 * The circulating amoeba IS the Meeting Room control.
 * Monochrome, subtle, continuously alive.
 */
export function AmoebaButton({
  status,
  size = 34,
  label,
  className,
}: {
  status: AgentStatus;
  size?: number;
  label?: string;
  className?: string;
}) {
  const [t, setT] = useState(0);
  const raf = useRef<number>(0);
  const navigate = useNavigate();

  useEffect(() => {
    let start = 0;
    const loop = (ts: number) => {
      if (!start) start = ts;
      setT((ts - start) / 1000);
      raf.current = requestAnimationFrame(loop);
    };
    raf.current = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf.current);
  }, []);

  const energy = ENERGY[status];
  const C = 50;

  return (
    <button
      type="button"
      title="Open Meeting Room"
      aria-label={`Open Meeting Room — agent ${status.replace(/_/g, " ").toLowerCase()}`}
      onClick={() => navigate({ to: "/meeting" })}
      className={cn("group relative shrink-0 outline-none", className)}
    >
      <svg viewBox="0 0 100 100" style={{ width: size, height: size }} className="block">
        <path
          d={blobPath(C, C, 34, t * 0.55, energy * 0.7)}
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          className="text-border-strong opacity-70"
        />
        <path
          d={blobPath(C, C, 27, t * 0.85 + 1.4, energy)}
          fill="none"
          stroke="currentColor"
          strokeWidth="2.2"
          className="text-foreground opacity-90 transition-opacity group-hover:opacity-100"
        />
        <circle
          cx={C + 24}
          cy={C - 22}
          r={4 + Math.sin(t * 2.2) * (0.6 + energy)}
          fill="currentColor"
          className="text-muted-foreground"
        />
      </svg>
      <span className="pointer-events-none absolute right-0 top-full z-50 mt-1.5 hidden whitespace-nowrap border border-border bg-popover px-2 py-1 font-mono text-[10px] tracking-[0.12em] text-popover-foreground group-hover:block">
        {label ?? "OPEN MEETING ROOM"}
      </span>
    </button>
  );
}
