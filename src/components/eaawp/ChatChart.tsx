/**
 * Renders one server-provided ChartSpec (see backend/docs/TOOLHUB_API.md "Charts in chat answers").
 * Values are drawn exactly as given: null stays a gap, nothing is interpolated, filled or invented.
 */
import { Component, useMemo, useRef, useState, type ReactNode } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Download, Table2 } from "lucide-react";
import { toast } from "sonner";
import { chartColor, chartProblem, formatNumber, type ChartSpec } from "@/lib/charts";
import { cn } from "@/lib/utils";

const AXIS_TICK = {
  fill: "var(--muted-foreground)",
  fontSize: 10,
  fontFamily: "var(--font-mono, monospace)",
} as const;
const AXIS_LABEL_STYLE = {
  fill: "var(--muted-foreground)",
  fontSize: 10,
  fontFamily: "var(--font-mono, monospace)",
} as const;
const TOOLTIP_STYLE = {
  background: "var(--surface)",
  border: "1px solid var(--border)",
  borderRadius: 2,
  fontSize: 11,
  color: "var(--foreground)",
} as const;
const TOOLTIP_LABEL_STYLE = {
  color: "var(--foreground)",
  fontWeight: 600,
  marginBottom: 2,
} as const;
const LEGEND_STYLE = { fontSize: 11, color: "var(--muted-foreground)" } as const;

/** A value from the server, or null when it is missing / not a finite number (drawn as a gap). */
function num(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function compact(v: number): string {
  const abs = Math.abs(v);
  if (abs >= 1e9) return `${+(v / 1e9).toFixed(1)}B`;
  if (abs >= 1e6) return `${+(v / 1e6).toFixed(1)}M`;
  if (abs >= 1e4) return `${+(v / 1e3).toFixed(1)}k`;
  return `${+v.toFixed(abs < 1 && abs > 0 ? 3 : 2)}`;
}

function axisLabel(label: string | null | undefined, unit: string | null | undefined): string {
  const l = (label ?? "").trim();
  const u = (unit ?? "").trim();
  if (l && u) return l.includes(u) ? l : `${l} (${u})`; // "CTR (%)" already names its unit
  return l || (u ? `(${u})` : "");
}

function safeFileName(title: string): string {
  const s = title
    .replace(/[\\/:*?"<>|]+/g, "")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 120);
  return s || "chart";
}

// ── PNG export ────────────────────────────────────────────────────────────────

const STYLE_PROPS = [
  "fill",
  "fill-opacity",
  "stroke",
  "stroke-width",
  "stroke-opacity",
  "stroke-dasharray",
  "opacity",
  "font-size",
  "font-family",
  "font-weight",
  "text-anchor",
  "dominant-baseline",
  "visibility",
] as const;

/** Copy the computed (variable-resolved) presentation styles onto the clone so it renders standalone. */
function inlineStyles(source: Element, target: Element) {
  const cs = window.getComputedStyle(source);
  const style: string[] = [];
  for (const p of STYLE_PROPS) {
    const v = cs.getPropertyValue(p);
    if (v) style.push(`${p}:${v}`);
  }
  (target as SVGElement).setAttribute("style", style.join(";"));
  const sc = source.children;
  const tc = target.children;
  for (let i = 0; i < sc.length && i < tc.length; i++) {
    const s = sc[i];
    const t = tc[i];
    if (s && t) inlineStyles(s, t);
  }
}

async function exportPng(
  container: HTMLElement,
  spec: ChartSpec,
  legend: { name: string; color: string }[],
) {
  const svg = container.querySelector<SVGSVGElement>(".recharts-wrapper > svg");
  if (!svg) throw new Error("No drawn chart to export.");
  const { width, height } = svg.getBoundingClientRect();
  const clone = svg.cloneNode(true) as SVGSVGElement;
  inlineStyles(svg, clone);
  clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  clone.setAttribute("width", String(width));
  clone.setAttribute("height", String(height));
  const xml = new XMLSerializer().serializeToString(clone);
  const url = URL.createObjectURL(new Blob([xml], { type: "image/svg+xml;charset=utf-8" }));
  try {
    const img = await new Promise<HTMLImageElement>((resolve, reject) => {
      const i = new Image();
      i.onload = () => resolve(i);
      i.onerror = () => reject(new Error("The chart image could not be prepared."));
      i.src = url;
    });
    const light = document.documentElement.classList.contains("light");
    const bg = light ? "#ffffff" : "#1b1b1b";
    const fg = light ? "#1f1f1f" : "#f2f2f2";
    const muted = light ? "#5f5f5f" : "#a8a8a8";
    const scale = 2;
    const pad = 16;
    const titleH = 30;
    const legendRows: { name: string; color: string }[][] = [];
    // Measure legend layout with a scratch context.
    const measure = document.createElement("canvas").getContext("2d");
    if (!measure) throw new Error("Canvas is not available in this browser.");
    measure.font = "11px sans-serif";
    let row: { name: string; color: string }[] = [];
    let rowW = 0;
    for (const item of legend) {
      const w = measure.measureText(item.name).width + 26;
      if (row.length > 0 && rowW + w > width) {
        legendRows.push(row);
        row = [];
        rowW = 0;
      }
      row.push(item);
      rowW += w;
    }
    if (row.length) legendRows.push(row);
    const legendH = legendRows.length * 18 + (legendRows.length ? 6 : 0);
    const footer = [spec.source ? `Source: ${spec.source}` : "", spec.note ?? ""].filter(Boolean);
    const footerH = footer.length * 16 + (footer.length ? 6 : 0);
    const W = width + pad * 2;
    const H = pad + titleH + height + legendH + footerH + pad;

    const canvas = document.createElement("canvas");
    canvas.width = Math.ceil(W * scale);
    canvas.height = Math.ceil(H * scale);
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("Canvas is not available in this browser.");
    ctx.scale(scale, scale);
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, W, H);
    ctx.fillStyle = fg;
    ctx.font = "600 14px sans-serif";
    ctx.textBaseline = "top";
    ctx.fillText(spec.title, pad, pad, width);
    ctx.drawImage(img, pad, pad + titleH, width, height);
    let y = pad + titleH + height + 4;
    ctx.font = "11px sans-serif";
    for (const r of legendRows) {
      let x = pad;
      for (const item of r) {
        ctx.fillStyle = item.color;
        ctx.fillRect(x, y + 2, 10, 10);
        ctx.fillStyle = muted;
        ctx.fillText(item.name, x + 14, y + 1);
        x += measure.measureText(item.name).width + 26;
      }
      y += 18;
    }
    if (legendRows.length) y += 6;
    ctx.fillStyle = muted;
    ctx.font = "10px monospace";
    for (const line of footer) {
      ctx.fillText(line, pad, y, width);
      y += 16;
    }

    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/png"));
    if (!blob) throw new Error("The PNG could not be created.");
    const href = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = href;
    a.download = `${safeFileName(spec.title)}.png`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.setTimeout(() => URL.revokeObjectURL(href), 1000);
  } finally {
    URL.revokeObjectURL(url);
  }
}

// ── Error boundary so one bad spec never breaks the chat ─────────────────────

class ChartBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  override state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  override render() {
    return this.state.failed ? <ChartFailed /> : this.props.children;
  }
}

function ChartFailed({
  title,
  reason,
}: {
  title?: string | undefined;
  reason?: string | undefined;
}) {
  return (
    <div
      role="note"
      className="mt-2 w-full border border-border px-3 py-2 font-mono text-[10px] tracking-[0.08em] text-muted-foreground"
    >
      {title ? <span className="text-foreground">{title} · </span> : null}
      Chart could not be drawn{reason ? ` (${reason})` : ""}.
    </div>
  );
}

// ── Data table (exact numbers) ───────────────────────────────────────────────

function DataTable({ spec }: { spec: ChartSpec }) {
  const unit = spec.unit;
  if (spec.type === "kpi") {
    return (
      <table className="w-full border-collapse text-[11px]">
        <thead>
          <tr className="bg-surface-2">
            <th className="label-xs border-b border-border px-2 py-1 text-left">Metric</th>
            <th className="label-xs border-b border-border px-2 py-1 text-right">Value</th>
          </tr>
        </thead>
        <tbody>
          {spec.kpis.map((k, i) => (
            <tr key={`${k.label}-${i}`} className="border-b border-border last:border-0">
              <td className="px-2 py-1">{k.label}</td>
              <td className="px-2 py-1 text-right font-mono">
                {formatNumber(num(k.value), k.unit)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  }
  const series = spec.series;
  const rowLabel = spec.type === "scatter" ? "Point" : spec.x_label || "Label";
  const rowCount =
    spec.type === "scatter"
      ? Math.max(spec.labels.length, series[0]?.values.length ?? 0, series[1]?.values.length ?? 0)
      : spec.labels.length;
  return (
    <table className="w-full border-collapse text-[11px]">
      <thead>
        <tr className="bg-surface-2">
          <th className="label-xs border-b border-border px-2 py-1 text-left">{rowLabel}</th>
          {series.map((s, i) => (
            <th
              key={`${s.name}-${i}`}
              className="label-xs border-b border-border px-2 py-1 text-right"
            >
              {s.name}
              {unit && spec.type !== "scatter" ? ` (${unit})` : ""}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {Array.from({ length: rowCount }, (_, r) => (
          <tr key={r} className="border-b border-border last:border-0">
            <td className="break-words px-2 py-1">{spec.labels[r] ?? `#${r + 1}`}</td>
            {series.map((s, i) => (
              <td key={i} className="px-2 py-1 text-right font-mono">
                {formatNumber(num(s.values[r]))}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// ── The chart itself ─────────────────────────────────────────────────────────

function KpiCards({ spec }: { spec: ChartSpec }) {
  return (
    <div className="grid grid-cols-1 gap-2 min-[360px]:grid-cols-2 sm:grid-cols-3">
      {spec.kpis.map((k, i) => (
        <div key={`${k.label}-${i}`} className="min-w-0 border border-border bg-surface px-3 py-2">
          <div className="label-xs truncate" title={k.label}>
            {k.label}
          </div>
          <div className="mt-1 break-words text-lg font-semibold tabular-nums">
            {formatNumber(num(k.value), k.unit)}
          </div>
        </div>
      ))}
    </div>
  );
}

function ChartBody({ spec }: { spec: ChartSpec }) {
  const unit = spec.unit;
  const multi = spec.series.length > 1;
  const yLabel = axisLabel(spec.y_label, unit);
  const xLabel = axisLabel(spec.x_label, null);
  const fmt = (v: unknown) => formatNumber(num(v), unit);

  const rows = useMemo(
    () =>
      spec.labels.map((label, i) => {
        const row: Record<string, string | number | null> = { __label: label };
        spec.series.forEach((s, si) => {
          row[`s${si}`] = num(s.values[i]);
        });
        return row;
      }),
    [spec],
  );
  const longLabels = spec.labels.length > 6 && spec.labels.some((l) => String(l).length > 8);
  const xAxis = (
    <XAxis
      dataKey="__label"
      tick={AXIS_TICK}
      stroke="var(--border)"
      interval="preserveStartEnd"
      minTickGap={8}
      angle={longLabels ? -30 : 0}
      textAnchor={longLabels ? "end" : "middle"}
      height={(longLabels ? 56 : 30) + (xLabel ? 14 : 0)}
      {...(xLabel
        ? { label: { value: xLabel, position: "insideBottom", offset: 0, style: AXIS_LABEL_STYLE } }
        : {})}
    />
  );
  const yAxis = (
    <YAxis
      tick={AXIS_TICK}
      stroke="var(--border)"
      width={yLabel ? 62 : 48}
      tickFormatter={(v: number) => compact(v)}
      {...(yLabel
        ? {
            label: {
              value: yLabel,
              angle: -90,
              position: "insideLeft",
              style: { ...AXIS_LABEL_STYLE, textAnchor: "middle" },
            },
          }
        : {})}
    />
  );
  const grid = <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />;
  const tooltip = (
    <Tooltip
      formatter={(v: unknown) => fmt(v)}
      contentStyle={TOOLTIP_STYLE}
      labelStyle={TOOLTIP_LABEL_STYLE}
      itemStyle={{ padding: 0 }}
      cursor={{ fill: "var(--muted)", fillOpacity: 0.3 }}
    />
  );
  const legend = multi ? <Legend wrapperStyle={LEGEND_STYLE} iconSize={9} /> : null;
  const margin = { top: 8, right: 12, bottom: 4, left: 0 };

  if (spec.type === "bar") {
    return (
      <ResponsiveContainer width="100%" height={280}>
        <BarChart data={rows} margin={margin}>
          {grid}
          {xAxis}
          {yAxis}
          {tooltip}
          {legend}
          {spec.series.map((s, i) => (
            <Bar
              key={i}
              dataKey={`s${i}`}
              name={s.name}
              fill={chartColor(i)}
              isAnimationActive={false}
              maxBarSize={48}
            />
          ))}
        </BarChart>
      </ResponsiveContainer>
    );
  }
  if (spec.type === "line") {
    return (
      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={rows} margin={margin}>
          {grid}
          {xAxis}
          {yAxis}
          {tooltip}
          {legend}
          {spec.series.map((s, i) => (
            <Line
              key={i}
              type="linear"
              dataKey={`s${i}`}
              name={s.name}
              stroke={chartColor(i)}
              strokeWidth={2}
              dot={{ r: 2.5, fill: chartColor(i) }}
              activeDot={{ r: 4 }}
              connectNulls={false}
              isAnimationActive={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    );
  }
  if (spec.type === "area") {
    return (
      <ResponsiveContainer width="100%" height={280}>
        <AreaChart data={rows} margin={margin}>
          {grid}
          {xAxis}
          {yAxis}
          {tooltip}
          {legend}
          {spec.series.map((s, i) => (
            <Area
              key={i}
              type="linear"
              dataKey={`s${i}`}
              name={s.name}
              stroke={chartColor(i)}
              fill={chartColor(i)}
              fillOpacity={0.18}
              strokeWidth={2}
              connectNulls={false}
              isAnimationActive={false}
            />
          ))}
        </AreaChart>
      </ResponsiveContainer>
    );
  }
  if (spec.type === "pie" || spec.type === "donut") {
    const s0 = spec.series[0];
    const slices = spec.labels
      .map((label, i) => ({ name: label, value: num(s0?.values[i]), color: chartColor(i) }))
      .filter(
        (d): d is { name: string; value: number; color: string } => d.value !== null && d.value > 0,
      );
    const hidden = spec.labels.length - slices.length;
    if (slices.length === 0) return <ChartFailed reason="no positive values to draw" />;
    return (
      <>
        <ResponsiveContainer width="100%" height={280}>
          <PieChart margin={{ top: 4, right: 4, bottom: 4, left: 4 }}>
            <Tooltip
              formatter={(v: unknown) => fmt(v)}
              contentStyle={TOOLTIP_STYLE}
              labelStyle={TOOLTIP_LABEL_STYLE}
              itemStyle={{ color: "var(--foreground)" }}
            />
            <Legend wrapperStyle={LEGEND_STYLE} iconSize={9} />
            <Pie
              data={slices}
              dataKey="value"
              nameKey="name"
              isAnimationActive={false}
              innerRadius={spec.type === "donut" ? "50%" : 0}
              outerRadius="78%"
              stroke="var(--background)"
              strokeWidth={1}
            >
              {slices.map((d) => (
                <Cell key={d.name} fill={d.color} />
              ))}
            </Pie>
          </PieChart>
        </ResponsiveContainer>
        {hidden > 0 && (
          <p className="mt-1 font-mono text-[10px] text-muted-foreground">
            {hidden} {hidden === 1 ? "value is" : "values are"} empty or not positive and not drawn
            as a slice. Open TABLE for every value.
          </p>
        )}
      </>
    );
  }
  if (spec.type === "scatter") {
    const [sx, sy] = spec.series;
    const n = Math.max(spec.labels.length, sx?.values.length ?? 0);
    const points: { x: number; y: number; name: string }[] = [];
    for (let i = 0; i < n; i++) {
      const x = num(sx?.values[i]);
      const y = num(sy?.values[i]);
      if (x !== null && y !== null) points.push({ x, y, name: spec.labels[i] ?? `#${i + 1}` });
    }
    if (points.length === 0) return <ChartFailed reason="no complete x/y pairs" />;
    const xl = axisLabel(spec.x_label ?? sx?.name ?? null, null);
    const yl = axisLabel(spec.y_label ?? sy?.name ?? null, unit);
    return (
      <ResponsiveContainer width="100%" height={280}>
        <ScatterChart margin={{ top: 8, right: 12, bottom: 4, left: 0 }}>
          <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
          <XAxis
            type="number"
            dataKey="x"
            name={sx?.name ?? "x"}
            tick={AXIS_TICK}
            stroke="var(--border)"
            tickFormatter={(v: number) => compact(v)}
            height={xl ? 44 : 30}
            {...(xl
              ? {
                  label: {
                    value: xl,
                    position: "insideBottom",
                    offset: 0,
                    style: AXIS_LABEL_STYLE,
                  },
                }
              : {})}
          />
          <YAxis
            type="number"
            dataKey="y"
            name={sy?.name ?? "y"}
            tick={AXIS_TICK}
            stroke="var(--border)"
            width={yl ? 62 : 48}
            tickFormatter={(v: number) => compact(v)}
            {...(yl
              ? {
                  label: {
                    value: yl,
                    angle: -90,
                    position: "insideLeft",
                    style: { ...AXIS_LABEL_STYLE, textAnchor: "middle" },
                  },
                }
              : {})}
          />
          <Tooltip
            cursor={{ strokeDasharray: "3 3", stroke: "var(--border)" }}
            content={({ active, payload }) => {
              const p =
                active && payload?.[0]
                  ? (payload[0].payload as { x: number; y: number; name: string })
                  : null;
              if (!p) return null;
              return (
                <div style={TOOLTIP_STYLE} className="px-2 py-1">
                  <div style={TOOLTIP_LABEL_STYLE}>{p.name}</div>
                  <div>
                    {sx?.name ?? "x"}: {formatNumber(p.x)}
                  </div>
                  <div>
                    {sy?.name ?? "y"}: {formatNumber(p.y, unit)}
                  </div>
                </div>
              );
            }}
          />
          <Scatter data={points} fill={chartColor(0)} isAnimationActive={false} />
        </ScatterChart>
      </ResponsiveContainer>
    );
  }
  return null;
}

export function ChatChart({ spec }: { spec: ChartSpec }) {
  const problem = chartProblem(spec);
  const [showTable, setShowTable] = useState(false);
  const [exporting, setExporting] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  if (problem)
    return (
      <ChartFailed
        title={typeof spec?.title === "string" ? spec.title : undefined}
        reason={problem}
      />
    );

  const drawsSvg = spec.type !== "kpi" && spec.type !== "table";
  const legendItems =
    spec.type === "pie" || spec.type === "donut"
      ? spec.labels.map((l, i) => ({ name: l, color: chartColor(i) }))
      : spec.type === "scatter"
        ? []
        : spec.series.length > 1
          ? spec.series.map((s, i) => ({ name: s.name, color: chartColor(i) }))
          : [];

  async function onPng() {
    if (!ref.current) return;
    setExporting(true);
    try {
      await exportPng(ref.current, spec, legendItems);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "The chart could not be exported.");
    } finally {
      setExporting(false);
    }
  }

  return (
    <figure
      data-testid="chat-chart"
      className="mt-2 w-full min-w-0 border border-border bg-surface/40 p-3"
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <figcaption className="min-w-0 break-words text-[13px] font-medium">
          {spec.title}
        </figcaption>
        {spec.type !== "table" && (
          <div className="flex shrink-0 gap-1.5">
            <button
              type="button"
              onClick={() => setShowTable((v) => !v)}
              aria-pressed={showTable}
              className={cn(
                "inline-flex items-center gap-1 border px-2 py-0.5 font-mono text-[10px] tracking-[0.12em]",
                showTable
                  ? "border-foreground text-foreground"
                  : "border-border text-muted-foreground hover:text-foreground",
              )}
            >
              <Table2 className="size-3" /> TABLE
            </button>
            {drawsSvg && (
              <button
                type="button"
                onClick={() => void onPng()}
                disabled={exporting || showTable}
                title={
                  showTable ? "Switch back to the chart to export it" : "Download the chart as PNG"
                }
                className="inline-flex items-center gap-1 border border-border px-2 py-0.5 font-mono text-[10px] tracking-[0.12em] text-muted-foreground hover:text-foreground disabled:opacity-40"
              >
                <Download className="size-3" /> {exporting ? "…" : "PNG"}
              </button>
            )}
          </div>
        )}
      </div>

      <div ref={ref} className="mt-2 min-w-0">
        {spec.type === "table" || showTable ? (
          <div className="max-h-80 overflow-auto border border-border">
            <DataTable spec={spec} />
          </div>
        ) : spec.type === "kpi" ? (
          <KpiCards spec={spec} />
        ) : (
          <ChartBoundary>
            <ChartBody spec={spec} />
          </ChartBoundary>
        )}
      </div>

      {spec.source && (
        <p className="mt-2 break-words font-mono text-[10px] text-muted-foreground">
          SOURCE · {spec.source}
        </p>
      )}
      {spec.note && (
        <p className="mt-1 break-words text-[11px] text-muted-foreground">{spec.note}</p>
      )}
    </figure>
  );
}

export function ChatCharts({ charts }: { charts: ChartSpec[] | null | undefined }) {
  if (!Array.isArray(charts) || charts.length === 0) return null;
  return (
    <div className="flex w-full min-w-0 flex-col gap-2" aria-label="Charts">
      {charts.map((c, i) => (
        <ChartBoundary key={c?.id ?? i}>
          <ChatChart spec={c} />
        </ChartBoundary>
      ))}
    </div>
  );
}
