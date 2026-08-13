import { useEffect, useMemo, useRef, useState } from "react";
import { departments } from "@/services/mockData";
import type { AgentStatus, DepartmentKey } from "@/services/types";

interface Props {
  status: AgentStatus;
  /** show department endpoints around the organism */
  withNetwork?: boolean;
  activeDepartment?: DepartmentKey | null;
  onSelectDepartment?: (key: DepartmentKey) => void;
  height?: number;
  compact?: boolean;
}

const ENERGY: Record<AgentStatus, number> = {
  IDLE: 0.25,
  MONITORING: 0.45,
  SCHEDULED: 0.4,
  ANALYZING: 0.85,
  EXECUTING: 1,
  COMMUNICATING: 0.9,
  WAITING_FOR_APPROVAL: 0.35,
  ERROR: 1.1,
};

function blobPath(cx: number, cy: number, r: number, t: number, energy: number, points = 9) {
  const pts: [number, number][] = [];
  for (let i = 0; i < points; i++) {
    const a = (i / points) * Math.PI * 2;
    const wobble =
      Math.sin(a * 3 + t * 0.9) * 0.07 +
      Math.sin(a * 5 - t * 1.4) * 0.045 +
      Math.cos(a * 2 + t * 0.55) * 0.05;
    const rr = r * (1 + wobble * (0.55 + energy));
    pts.push([cx + Math.cos(a) * rr, cy + Math.sin(a) * rr * 0.92]);
  }
  let d = "";
  for (let i = 0; i < pts.length; i++) {
    const p0 = pts[(i - 1 + pts.length) % pts.length]!;
    const p1 = pts[i]!;
    const p2 = pts[(i + 1) % pts.length]!;
    const p3 = pts[(i + 2) % pts.length]!;
    if (i === 0) d += `M ${p1[0].toFixed(2)} ${p1[1].toFixed(2)}`;
    const c1x = p1[0] + (p2[0] - p0[0]) / 6;
    const c1y = p1[1] + (p2[1] - p0[1]) / 6;
    const c2x = p2[0] - (p3[0] - p1[0]) / 6;
    const c2y = p2[1] - (p3[1] - p1[1]) / 6;
    d += ` C ${c1x.toFixed(2)} ${c1y.toFixed(2)}, ${c2x.toFixed(2)} ${c2y.toFixed(2)}, ${p2[0].toFixed(2)} ${p2[1].toFixed(2)}`;
  }
  return `${d} Z`;
}

export function AgentOrganism({
  status,
  withNetwork = false,
  activeDepartment = null,
  onSelectDepartment,
  height = 320,
  compact = false,
}: Props) {
  const [t, setT] = useState(0);
  const raf = useRef<number>(0);

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
  const W = 640;
  const H = 380;
  const cx = W / 2;
  const cy = H / 2;
  const baseR = withNetwork ? 78 : 96;

  const nodes = useMemo(
    () =>
      departments.map((d, i) => {
        const a = (i / departments.length) * Math.PI * 2 - Math.PI / 2;
        const rx = withNetwork ? 250 : 210;
        const ry = withNetwork ? 148 : 128;
        return { ...d, x: cx + Math.cos(a) * rx, y: cy + Math.sin(a) * ry };
      }),
    [cx, cy, withNetwork],
  );

  const talking = status === "COMMUNICATING" || status === "EXECUTING" || status === "ANALYZING";

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      style={{ height }}
      className="w-full select-none"
      role="img"
      aria-label="AI workspace activity visualization"
    >
      <defs>
        <radialGradient id="org-core" cx="42%" cy="38%">
          <stop offset="0%" stopColor="var(--color-foreground)" stopOpacity="0.22" />
          <stop offset="55%" stopColor="var(--color-foreground)" stopOpacity="0.07" />
          <stop offset="100%" stopColor="var(--color-foreground)" stopOpacity="0.02" />
        </radialGradient>
        <filter id="org-blur">
          <feGaussianBlur stdDeviation="9" />
        </filter>
      </defs>

      {/* membranes */}
      <path
        d={blobPath(cx, cy, baseR * 1.55, t * 0.5, energy * 0.6)}
        fill="none"
        stroke="var(--color-border-strong)"
        strokeDasharray="2 6"
        strokeWidth="1"
        opacity={0.7}
      />
      <path
        d={blobPath(cx, cy, baseR * 1.22, t * 0.75 + 1.5, energy * 0.8)}
        fill="none"
        stroke="var(--color-foreground)"
        strokeWidth="1"
        opacity={0.28 + energy * 0.25}
      />
      <path d={blobPath(cx, cy, baseR, t, energy)} fill="url(#org-core)" filter="url(#org-blur)" />
      <path
        d={blobPath(cx, cy, baseR, t, energy)}
        fill="none"
        stroke={status === "ERROR" ? "var(--color-foreground)" : "var(--color-foreground)"}
        strokeWidth="1.5"
      />

      {/* nucleus */}
      <circle
        cx={cx}
        cy={cy}
        r={5 + Math.sin(t * 2.2) * (1 + energy)}
        fill={status === "ERROR" ? "var(--color-foreground)" : "var(--color-foreground)"}
      />
      {!compact && (
        <text
          x={cx}
          y={cy + 26}
          textAnchor="middle"
          className="fill-muted-foreground"
          style={{ fontSize: 9, letterSpacing: "0.18em", fontFamily: "var(--font-mono)" }}
        >
          {status.replace(/_/g, " ")}
        </text>
      )}

      {withNetwork &&
        nodes.map((n, i) => {
          const active = activeDepartment === n.key;
          const flowing = talking && (active || n.linkStrength > 0.6);
          const pulse = (t * (0.35 + n.linkStrength * 0.5) + i * 0.31) % 1;
          const px = cx + (n.x - cx) * pulse;
          const py = cy + (n.y - cy) * pulse;
          return (
            <g
              key={n.key}
              onClick={() => onSelectDepartment?.(n.key)}
              style={{ cursor: onSelectDepartment ? "pointer" : "default" }}
            >
              <path
                d={`M ${cx} ${cy} Q ${(cx + n.x) / 2 + Math.sin(t + i) * 14} ${(cy + n.y) / 2 + Math.cos(t + i) * 14} ${n.x} ${n.y}`}
                fill="none"
                stroke={active ? "var(--color-foreground)" : "var(--color-border-strong)"}
                strokeWidth={active ? 1.4 : 1}
                opacity={active ? 0.9 : 0.35 + n.linkStrength * 0.3}
              />
              {flowing && (
                <circle cx={px} cy={py} r={2} fill={active ? "var(--color-foreground)" : "var(--color-foreground)"} opacity={0.9} />
              )}
              <circle
                cx={n.x}
                cy={n.y}
                r={active ? 7 : 5}
                fill="var(--color-surface)"
                stroke={active ? "var(--color-foreground)" : "var(--color-border-strong)"}
                strokeWidth="1.5"
              />
              <text
                x={n.x}
                y={n.y - 13}
                textAnchor="middle"
                className={active ? "fill-foreground" : "fill-muted-foreground"}
                style={{ fontSize: 9.5, letterSpacing: "0.12em", fontFamily: "var(--font-mono)", textTransform: "uppercase" }}
              >
                {n.name}
              </text>
            </g>
          );
        })}
    </svg>
  );
}
