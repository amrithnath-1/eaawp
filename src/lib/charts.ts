/**
 * Chart contract shared by chat answers (POST /api/v1/agent/execute, saved conversation messages) and the
 * Tool Center. See backend/docs/TOOLHUB_API.md "Charts in chat answers". Every value comes from the server;
 * the UI renders exactly what it is given and never fills or invents data.
 */

export type ChartType = "bar" | "line" | "area" | "pie" | "donut" | "scatter" | "kpi" | "table";

export interface ChartSeries {
  name: string;
  values: (number | null)[];
}

export interface ChartKpi {
  label: string;
  value: number;
  unit: string | null;
}

export interface ChartSpec {
  id: string;
  type: ChartType;
  title: string;
  unit: string | null;
  x_label: string | null;
  y_label: string | null;
  labels: string[];
  series: ChartSeries[];
  kpis: ChartKpi[];
  source: string;
  note: string | null;
}

/**
 * Fixed categorical palette (Okabe–Ito derived) chosen to stay distinguishable for common colour-vision
 * deficiencies and readable on both the dark and the light theme backgrounds.
 */
export const CHART_PALETTE = [
  "#3b8fd9", // blue
  "#e69f00", // orange
  "#2ba67f", // bluish green
  "#d55e00", // vermillion
  "#cc79a7", // reddish purple
  "#8a8f98", // neutral grey
  "#c9b200", // yellow (darkened for light backgrounds)
  "#56b4e9", // sky blue
] as const;

export function chartColor(i: number): string {
  return CHART_PALETTE[i % CHART_PALETTE.length] ?? CHART_PALETTE[0];
}

/** Why a spec cannot be drawn, or null when it is drawable. */
export function chartProblem(spec: ChartSpec | null | undefined): string | null {
  if (!spec || typeof spec !== "object") return "missing chart";
  const labels = Array.isArray(spec.labels) ? spec.labels : null;
  const series = Array.isArray(spec.series) ? spec.series : null;
  const seriesOk = (s: ChartSeries | null | undefined) => !!s && Array.isArray(s.values);
  switch (spec.type) {
    case "kpi":
      return Array.isArray(spec.kpis) && spec.kpis.length > 0 ? null : "no KPI values";
    case "scatter":
      if (!series || series.length < 2 || !seriesOk(series[0]) || !seriesOk(series[1]))
        return "scatter needs x and y series";
      return null;
    case "bar":
    case "line":
    case "area":
    case "pie":
    case "donut":
    case "table":
      if (!labels || labels.length === 0) return "no labels";
      if (!series || series.length === 0 || !series.every(seriesOk)) return "no series";
      if ((spec.type === "pie" || spec.type === "donut") && !seriesOk(series[0]))
        return "no series";
      return null;
    default:
      return "unknown chart type";
  }
}

/** Format a number for display without changing its value (only grouping and trimming float noise). */
export function formatNumber(v: number | null | undefined, unit?: string | null): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const abs = Math.abs(v);
  const digits = Number.isInteger(v) ? 0 : abs >= 100 ? 1 : abs >= 1 ? 2 : 4;
  const s = v.toLocaleString(undefined, { maximumFractionDigits: digits });
  if (!unit) return s;
  return unit === "%" ? `${s}%` : `${s} ${unit}`;
}
