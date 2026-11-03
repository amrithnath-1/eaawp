/**
 * Chart contract shared by chat answers (POST /api/v1/agent/execute, saved conversation messages) and the
 * Tool Center. See backend/docs/TOOLHUB_API.md "Charts in chat answers". Every value comes from the server;
 * the UI renders exactly what it is given and never fills or invents data.
 */

export type ChartType =
  "bar" | "hbar" | "line" | "area" | "pie" | "donut" | "scatter" | "histogram" | "kpi" | "table";

export const CHART_TYPES: readonly ChartType[] = [
  "bar",
  "hbar",
  "line",
  "area",
  "pie",
  "donut",
  "scatter",
  "histogram",
  "kpi",
  "table",
];

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
  /** Optional one-line explanation shown under the title (absent on older saved charts). */
  description?: string | null;
  unit: string | null;
  x_label: string | null;
  y_label: string | null;
  labels: string[];
  series: ChartSeries[];
  kpis: ChartKpi[];
  /** bar, hbar, area: stack the series instead of grouping them (absent on older saved charts). */
  stacked?: boolean;
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
    case "histogram":
      if (!labels || labels.length === 0) return "no bins";
      if (!series || series.length !== 1 || !seriesOk(series[0]))
        return "histogram needs exactly one series of counts";
      return null;
    case "bar":
    case "hbar":
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

// ── Normalising legacy / model-written chart JSON ─────────────────────────────

type Obj = Record<string, unknown>;

function isObj(v: unknown): v is Obj {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

/** First present (not undefined/null) value among the given keys. */
function pick(o: Obj, ...keys: string[]): unknown {
  for (const k of keys) {
    const v = o[k];
    if (v !== undefined && v !== null) return v;
  }
  return undefined;
}

function str(v: unknown): string | null {
  if (typeof v === "string") return v.trim() ? v.trim() : null;
  if (typeof v === "number" && Number.isFinite(v)) return String(v);
  return null;
}

const NUMERIC_RE = /^[+-]?(\d+\.?\d*|\.\d+)(e[+-]?\d+)?$/i;

/**
 * A finite number from a number or a numeric string ("1,200", "4.5%", "$3.10", " 7 "), else null.
 * Nothing is guessed: "n/a", "", "1.2k", objects, booleans all become null.
 */
export function toNumber(v: unknown): number | null {
  if (typeof v === "number") return Number.isFinite(v) ? v : null;
  if (typeof v !== "string") return null;
  let s = v.trim().replace(/[\s,_]/g, "");
  s = s.replace(/^([+-]?)[$€£¥₹]/, "$1").replace(/%$/, "");
  if (!NUMERIC_RE.test(s)) return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}

const TYPE_ALIASES: Record<string, ChartType> = {
  bar: "bar",
  bars: "bar",
  column: "bar",
  columns: "bar",
  vbar: "bar",
  grouped_bar: "bar",
  groupedbar: "bar",
  stacked_bar: "bar",
  stackedbar: "bar",
  hbar: "hbar",
  barh: "hbar",
  horizontal_bar: "hbar",
  horizontalbar: "hbar",
  horizontal: "hbar",
  line: "line",
  lines: "line",
  timeseries: "line",
  area: "area",
  stacked_area: "area",
  pie: "pie",
  donut: "donut",
  doughnut: "donut",
  scatter: "scatter",
  scatterplot: "scatter",
  scatter_plot: "scatter",
  histogram: "histogram",
  hist: "histogram",
  kpi: "kpi",
  kpis: "kpi",
  metric: "kpi",
  metrics: "kpi",
  table: "table",
};

function normType(v: unknown): ChartType | null {
  if (typeof v !== "string") return null;
  const k = v
    .trim()
    .toLowerCase()
    .replace(/[\s-]+/g, "_");
  return TYPE_ALIASES[k] ?? TYPE_ALIASES[k.replace(/_/g, "")] ?? null;
}

function toValues(v: unknown): (number | null)[] | null {
  return Array.isArray(v) ? v.map(toNumber) : null;
}

function toLabels(v: unknown): string[] | null {
  if (!Array.isArray(v)) return null;
  return v.map((x) => (typeof x === "string" ? x : (str(x) ?? "")));
}

/** True when every non-empty raw value was a string ending in "%" (so the unit is "%", not invented). */
function allPercent(raw: unknown[]): boolean {
  const present = raw.filter((x) => x !== null && x !== undefined && x !== "");
  return present.length > 0 && present.every((x) => typeof x === "string" && /%\s*$/.test(x));
}

function normSeries(v: unknown, i: number): { s: ChartSeries; raw: unknown[] } | null {
  if (Array.isArray(v)) return { s: { name: `Series ${i + 1}`, values: v.map(toNumber) }, raw: v };
  if (!isObj(v)) return null;
  const rawVals = pick(v, "values", "data", "y", "points");
  if (!Array.isArray(rawVals)) return null;
  // Points like [{x, y}] / [{label, value}] inside a series: take the value side.
  const flat = rawVals.map((p) => (isObj(p) ? pick(p, "value", "y", "count", "v") : p));
  const name = str(pick(v, "name", "label", "title", "key")) ?? `Series ${i + 1}`;
  return { s: { name, values: flat.map(toNumber) }, raw: flat };
}

let legacyCounter = 0;

/**
 * Turn an arbitrary parsed object (backend spec, legacy JSON a model wrote, Chart.js-like config) into a
 * ChartSpec, or null when it is not chart-shaped. Values are only converted, never invented: anything that
 * cannot be read as a number becomes null. Run chartProblem() on the result before drawing it.
 */
export function normalizeChartSpec(raw: unknown): ChartSpec | null {
  if (!isObj(raw)) return null;
  // Wrappers: {chart: {...}} / {spec: {...}}
  const inner = pick(raw, "chart", "spec");
  if (isObj(inner) && pick(raw, "type", "chart_type", "chartType") === undefined) {
    return normalizeChartSpec(inner);
  }

  const rawKpis = pick(raw, "kpis", "metrics");
  const explicitType = pick(raw, "type", "chart_type", "chartType", "kind");
  let type = normType(explicitType);
  if (!type && explicitType === undefined && rawKpis !== undefined) type = "kpi";
  if (!type) return null;

  const hasData = [
    "labels",
    "categories",
    "x",
    "series",
    "data",
    "datasets",
    "values",
    "kpis",
    "metrics",
    "rows",
  ].some((k) => raw[k] !== undefined && raw[k] !== null);
  if (!hasData) return null;

  const percentFlags: boolean[] = [];
  let labels = toLabels(pick(raw, "labels", "categories", "x_values", "bins")) ?? null;
  const xRaw = raw["x"];
  if (!labels && Array.isArray(xRaw) && type !== "scatter") labels = toLabels(xRaw);
  let series: ChartSeries[] = [];
  const kpis: ChartKpi[] = [];

  // series: [{name, values|data}] or [[...]] or a single values array
  const rawSeries = pick(raw, "series", "datasets");
  if (Array.isArray(rawSeries)) {
    const looksLikeOneSeries =
      rawSeries.length > 0 && rawSeries.every((x) => !isObj(x) && !Array.isArray(x));
    if (looksLikeOneSeries) {
      series = [{ name: str(raw["y_label"]) ?? "Value", values: rawSeries.map(toNumber) }];
      percentFlags.push(allPercent(rawSeries));
    } else {
      rawSeries.forEach((x, i) => {
        const n = normSeries(x, i);
        if (n) {
          series.push(n.s);
          percentFlags.push(allPercent(n.raw));
        }
      });
    }
  } else if (isObj(rawSeries)) {
    // {"Revenue": [..], "Cost": [..]}
    for (const [name, vals] of Object.entries(rawSeries)) {
      if (Array.isArray(vals)) {
        series.push({ name, values: vals.map(toNumber) });
        percentFlags.push(allPercent(vals));
      }
    }
  }

  // data: [{label, value}] / [{x, y}] / [numbers]
  const rawData = raw["data"];
  if (series.length === 0 && Array.isArray(rawData) && type !== "kpi") {
    if (rawData.every(isObj)) {
      const pts = rawData as Obj[];
      if (type === "scatter" && pts.some((p) => p["x"] !== undefined && p["y"] !== undefined)) {
        series = [
          { name: str(raw["x_label"]) ?? "x", values: pts.map((p) => toNumber(p["x"])) },
          { name: str(raw["y_label"]) ?? "y", values: pts.map((p) => toNumber(p["y"])) },
        ];
        const ls = pts.map((p) => str(pick(p, "label", "name")));
        if (ls.some((l) => l !== null)) labels = ls.map((l, i) => l ?? `#${i + 1}`);
      } else {
        const ls = pts.map(
          (p) => str(pick(p, "label", "name", "category", "x", "bin", "key")) ?? "",
        );
        const vs = pts.map((p) => pick(p, "value", "y", "count", "amount", "total", "v"));
        if (!labels) labels = ls;
        series = [
          { name: str(pick(raw, "series_name", "y_label")) ?? "Value", values: vs.map(toNumber) },
        ];
        percentFlags.push(allPercent(vs));
      }
    } else if (rawData.every((x) => !isObj(x) && !Array.isArray(x))) {
      series = [{ name: str(raw["y_label"]) ?? "Value", values: rawData.map(toNumber) }];
      percentFlags.push(allPercent(rawData));
    }
  }
  const rawValues = raw["values"];
  if (series.length === 0 && Array.isArray(rawValues)) {
    series = [{ name: str(raw["y_label"]) ?? "Value", values: rawValues.map(toNumber) }];
    percentFlags.push(allPercent(rawValues));
  }
  // scatter given as x: [...], y: [...]
  if (type === "scatter" && series.length === 0 && Array.isArray(xRaw) && Array.isArray(raw["y"])) {
    series = [
      { name: str(raw["x_label"]) ?? "x", values: xRaw.map(toNumber) },
      { name: str(raw["y_label"]) ?? "y", values: (raw["y"] as unknown[]).map(toNumber) },
    ];
  }

  // columns: [...], rows: [[label, v1, v2], ...]
  const rawRows = raw["rows"];
  const rawCols = raw["columns"];
  if (
    series.length === 0 &&
    Array.isArray(rawRows) &&
    Array.isArray(rawCols) &&
    rawCols.length >= 2
  ) {
    const rows = rawRows.filter(Array.isArray) as unknown[][];
    if (!labels) labels = rows.map((r) => str(r[0]) ?? "");
    series = rawCols.slice(1).map((c, j) => ({
      name: str(c) ?? `Series ${j + 1}`,
      values: rows.map((r) => toNumber(r[j + 1])),
    }));
  }

  // kpis: [{label, value, unit}] or {"Revenue": 1200}
  if (Array.isArray(rawKpis)) {
    for (const k of rawKpis) {
      if (!isObj(k)) continue;
      const label = str(pick(k, "label", "name", "metric", "title"));
      const rv = pick(k, "value", "v", "amount");
      const value = toNumber(rv);
      if (label === null || value === null) continue; // never invent a KPI value
      let unit = str(k["unit"]);
      if (!unit && typeof rv === "string" && /%\s*$/.test(rv)) unit = "%";
      kpis.push({ label, value, unit });
    }
  } else if (isObj(rawKpis)) {
    for (const [label, rv] of Object.entries(rawKpis)) {
      const value = toNumber(rv);
      if (value === null) continue;
      kpis.push({ label, value, unit: typeof rv === "string" && /%\s*$/.test(rv) ? "%" : null });
    }
  }

  let unit = str(raw["unit"]);
  if (!unit && percentFlags.length > 0 && percentFlags.every(Boolean)) unit = "%";

  const title = str(pick(raw, "title", "name", "caption")) ?? "Chart";
  const description = str(pick(raw, "description", "subtitle"));
  const note = str(pick(raw, "note", "notes", "footnote"));
  const stackedRaw = pick(raw, "stacked", "stack");
  const typeStr = typeof explicitType === "string" ? explicitType.toLowerCase() : "";
  const stacked = stackedRaw === true || typeStr.includes("stacked");
  const id = str(raw["id"]) ?? `legacy-${++legacyCounter}`;

  const spec: ChartSpec = {
    id,
    type,
    title,
    unit,
    x_label: str(pick(raw, "x_label", "xLabel", "x_axis_label", "x_title")),
    y_label: str(pick(raw, "y_label", "yLabel", "y_axis_label", "y_title")),
    labels: labels ?? [],
    series,
    kpis,
    source: str(raw["source"]) ?? "",
    note,
  };
  if (description) spec.description = description;
  if (stacked) spec.stacked = true;
  return spec;
}
