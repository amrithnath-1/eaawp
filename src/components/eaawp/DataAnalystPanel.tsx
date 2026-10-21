/**
 * DataAnalystPanel - upload a CSV/XLSX, ask questions in plain language, see computed tables and charts.
 *
 * Every number comes from the backend's deterministic engine; the AI only chooses what to calculate.
 * Administrators upload, delete and restrict datasets; every member can analyse the unrestricted ones.
 */
import { useRef, useState } from "react";
import { toast } from "sonner";
import { Loader2, Upload, Trash2, Lock, Unlock, Save, Download, Database, SendHorizonal } from "lucide-react";
import { Bar, BarChart, CartesianGrid, Line, LineChart, Pie, PieChart, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, Cell } from "recharts";
import { cn } from "@/lib/utils";
import { useSession } from "@/state/session";
import {
  useDatasets, useDataset, useUploadDataset, useDeleteDataset, useRestrictDataset, useAnalyzeDataset,
  useAnalysisReports, useSaveAnalysisReport, useDeleteAnalysisReport, downloadReportCsv,
  type AnalysisResultFE, type AnalysisFE,
} from "@/hooks/use-api";

const PALETTE = ["#6aa7ff", "#7bd88f", "#ffb454", "#ff7b72", "#c297ff", "#5fd3d3"];

function ResultTable({ r }: { r: AnalysisResultFE }) {
  return (
    <div className="max-h-72 overflow-auto border border-border">
      <table className="w-full text-left text-[12px]">
        <thead className="sticky top-0 bg-surface font-mono text-[10px] tracking-[0.06em] text-muted-foreground">
          <tr>{r.columns.map((c) => <th key={c} className="px-2 py-1.5 font-normal">{c}</th>)}</tr>
        </thead>
        <tbody>
          {r.rows.map((row, i) => (
            <tr key={i} className="border-t border-border">
              {row.map((v, j) => <td key={j} className="px-2 py-1 tabular-nums">{v === null ? "-" : String(v)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ResultChart({ r }: { r: AnalysisResultFE }) {
  const type = r.chart?.type ?? "none";
  if (type === "none" || r.rows.length === 0) return null;
  const xi = Math.max(0, r.columns.indexOf(r.chart.x ?? r.columns[0]!));
  const yi = Math.max(0, r.columns.indexOf(r.chart.y ?? r.columns[1] ?? r.columns[0]!));
  const data = r.rows.map((row) => ({ x: row[xi] ?? "", y: typeof row[yi] === "number" ? row[yi] : Number(row[yi]) || 0 }));
  const axis = { stroke: "currentColor", fontSize: 11, tickLine: false } as const;
  return (
    <div className="h-64 w-full text-muted-foreground" role="img" aria-label={`${type} chart of ${r.columns[yi]} by ${r.columns[xi]}`}>
      <ResponsiveContainer>
        {type === "line" ? (
          <LineChart data={data}><CartesianGrid strokeOpacity={0.15} /><XAxis dataKey="x" {...axis} /><YAxis {...axis} /><Tooltip />
            <Line isAnimationActive={false} dataKey="y" stroke={PALETTE[0]} dot={false} strokeWidth={2} /></LineChart>
        ) : type === "pie" ? (
          <PieChart><Tooltip /><Pie isAnimationActive={false} data={data} dataKey="y" nameKey="x" outerRadius={90}>{data.map((_, i) => <Cell key={i} fill={PALETTE[i % PALETTE.length]} />)}</Pie></PieChart>
        ) : type === "scatter" ? (
          <ScatterChart><CartesianGrid strokeOpacity={0.15} /><XAxis dataKey="x" type="number" {...axis} /><YAxis dataKey="y" {...axis} /><Tooltip />
            <Scatter isAnimationActive={false} data={data.map((d) => ({ x: Number(d.x), y: d.y }))} fill={PALETTE[0]} /></ScatterChart>
        ) : (
          <BarChart data={data}><CartesianGrid strokeOpacity={0.15} /><XAxis dataKey="x" {...axis} /><YAxis {...axis} /><Tooltip />
            <Bar isAnimationActive={false} dataKey="y" fill={PALETTE[0]} /></BarChart>
        )}
      </ResponsiveContainer>
    </div>
  );
}

function AnalysisView({ a }: { a: AnalysisFE }) {
  return (
    <div className="space-y-3">
      <p className="whitespace-pre-line text-[13px] leading-relaxed">{a.narrative}</p>
      <p className="font-mono text-[10px] text-muted-foreground">
        {a.narrative_source === "llm" ? "SUMMARY WRITTEN BY AI, NUMBERS CHECKED AGAINST THE RESULT" : "SUMMARY GENERATED FROM THE RESULT"}
      </p>
      <ResultChart r={a} />
      <ResultTable r={a} />
      {a.notes.map((n) => <p key={n} className="text-[11px] text-muted-foreground">{n}</p>)}
    </div>
  );
}

export function DataAnalystPanel() {
  const { user } = useSession();
  const isAdmin = user?.role === "Company Admin" || user?.role === "AI Administrator";
  const datasets = useDatasets();
  const [selected, setSelected] = useState<string | null>(null);
  const activeId = selected ?? datasets.data?.[0]?.id ?? null;
  const detail = useDataset(activeId);
  const upload = useUploadDataset();
  const del = useDeleteDataset();
  const restrict = useRestrictDataset();
  const analyze = useAnalyzeDataset(activeId ?? "");
  const reports = useAnalysisReports();
  const save = useSaveAnalysisReport();
  const delReport = useDeleteAnalysisReport();
  const fileRef = useRef<HTMLInputElement>(null);
  const [question, setQuestion] = useState("");
  const [asked, setAsked] = useState("");
  const [result, setResult] = useState<AnalysisFE | null>(null);
  const [title, setTitle] = useState("");

  const onFile = (f: File | undefined) => {
    if (!f) return;
    const fd = new FormData();
    fd.append("file", f);
    upload.mutate(fd, {
      onSuccess: (d) => { toast.success(`Uploaded ${d.name} (${d.row_count.toLocaleString()} rows)`); setSelected(d.id); setResult(null); },
      onError: (e) => toast.error(e.message),
    });
    if (fileRef.current) fileRef.current.value = "";
  };

  const ask = () => {
    const q = question.trim();
    if (!q || !activeId) return;
    setAsked(q);
    analyze.mutate({ question: q }, {
      onSuccess: (r) => { setResult(r); setTitle(q.slice(0, 80)); },
      onError: (e) => toast.error(e.message),
    });
  };

  const d = detail.data;
  return (
    <div className="mx-auto max-w-6xl space-y-6 p-4 md:p-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold">Data Analyst</h1>
          <p className="text-[12px] text-muted-foreground">Upload a spreadsheet, then ask questions. Every figure is calculated, never guessed.</p>
        </div>
        {isAdmin && (
          <>
            <input ref={fileRef} type="file" accept=".csv,.xlsx,.tsv,.txt" className="hidden" data-testid="dataset-file" onChange={(e) => onFile(e.target.files?.[0])} />
            <button type="button" onClick={() => fileRef.current?.click()} disabled={upload.isPending}
              className="inline-flex items-center gap-2 border border-border bg-surface px-3 py-2 text-[12px] hover:bg-accent disabled:opacity-50">
              {upload.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />} Upload CSV or Excel
            </button>
          </>
        )}
      </header>

      <div className="grid gap-6 md:grid-cols-[240px_1fr]">
        <aside className="space-y-2" aria-label="Datasets">
          {datasets.isLoading && <p className="text-[12px] text-muted-foreground">Loading...</p>}
          {datasets.data?.length === 0 && (
            <p className="border border-dashed border-border p-3 text-[12px] text-muted-foreground">
              {isAdmin ? "No datasets yet. Upload a CSV or Excel file to begin (max 5 MB, 50,000 rows)." : "No datasets are available yet. Ask an administrator to upload one."}
            </p>
          )}
          {datasets.data?.map((ds) => (
            <button key={ds.id} type="button" onClick={() => { setSelected(ds.id); setResult(null); }}
              className={cn("flex w-full items-start gap-2 border px-3 py-2 text-left", ds.id === activeId ? "border-primary bg-surface" : "border-border hover:bg-accent")}>
              <Database className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
              <span className="min-w-0">
                <span className="block truncate text-[13px] font-medium">{ds.name}</span>
                <span className="block text-[11px] text-muted-foreground">{ds.row_count.toLocaleString()} rows - {ds.columns.length} columns{ds.is_restricted ? " - restricted" : ""}</span>
              </span>
            </button>
          ))}
        </aside>

        <main className="min-w-0 space-y-6">
          {!d ? (
            <p className="text-[13px] text-muted-foreground">Select a dataset.</p>
          ) : (
            <>
              <section className="space-y-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h2 className="text-[14px] font-medium">{d.name}</h2>
                  {isAdmin && (
                    <div className="flex gap-2">
                      <button type="button" className="inline-flex items-center gap-1 border border-border px-2 py-1 text-[11px] hover:bg-accent"
                        onClick={() => restrict.mutate({ id: d.id, is_restricted: !d.is_restricted }, { onError: (e) => toast.error(e.message) })}>
                        {d.is_restricted ? <Unlock className="h-3 w-3" /> : <Lock className="h-3 w-3" />} {d.is_restricted ? "Make available to everyone" : "Restrict to administrators"}
                      </button>
                      <button type="button" className="inline-flex items-center gap-1 border border-border px-2 py-1 text-[11px] text-destructive hover:bg-accent"
                        onClick={() => { if (window.confirm(`Delete dataset "${d.name}"? Saved reports are kept.`)) del.mutate(d.id, { onSuccess: () => { setSelected(null); setResult(null); }, onError: (e) => toast.error(e.message) }); }}>
                        <Trash2 className="h-3 w-3" /> Delete
                      </button>
                    </div>
                  )}
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {d.columns.map((c) => (
                    <span key={c.name} title={`${c.distinct} distinct values, e.g. ${c.sample.join(", ")}`} className="border border-border px-1.5 py-0.5 font-mono text-[10px]">
                      {c.name} <span className="text-muted-foreground">{c.type}</span>
                    </span>
                  ))}
                </div>
                <ResultTable r={{ columns: d.columns.map((c) => c.name), rows: d.preview, row_count: d.preview.length, chart: { type: "none" }, source: "", notes: [], spec: {} }} />
                <p className="text-[11px] text-muted-foreground">Showing the first {d.preview.length} rows.</p>
              </section>

              <section className="space-y-3">
                <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); ask(); }}>
                  <input value={question} onChange={(e) => setQuestion(e.target.value)} maxLength={1000} aria-label="Ask a question about this dataset"
                    placeholder="e.g. Total revenue by region, or monthly trend of units" className="min-w-0 flex-1 border border-border bg-background px-3 py-2 text-[13px]" />
                  <button type="submit" disabled={analyze.isPending || !question.trim()} className="inline-flex items-center gap-2 border border-border bg-surface px-3 py-2 text-[12px] hover:bg-accent disabled:opacity-50">
                    {analyze.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <SendHorizonal className="h-4 w-4" />} Analyse
                  </button>
                </form>
                {result && (
                  <div className="space-y-3 border border-border bg-surface p-4" data-testid="analysis-result">
                    <AnalysisView a={result} />
                    <div className="flex flex-wrap items-center gap-2 border-t border-border pt-3">
                      <input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} aria-label="Report title" className="min-w-0 flex-1 border border-border bg-background px-2 py-1 text-[12px]" />
                      <button type="button" disabled={save.isPending || !title.trim()} className="inline-flex items-center gap-1 border border-border px-2 py-1 text-[12px] hover:bg-accent disabled:opacity-50"
                        onClick={() => save.mutate({ dataset_id: d.id, title: title.trim(), question: asked, spec: result.spec }, { onSuccess: () => toast.success("Report saved"), onError: (e) => toast.error(e.message) })}>
                        <Save className="h-3 w-3" /> Save report
                      </button>
                    </div>
                  </div>
                )}
              </section>
            </>
          )}

          <section className="space-y-2" aria-label="Saved reports">
            <h2 className="text-[14px] font-medium">Saved reports</h2>
            {reports.data?.length === 0 && <p className="text-[12px] text-muted-foreground">Nothing saved yet.</p>}
            {reports.data?.map((rep) => (
              <details key={rep.id} className="border border-border bg-surface">
                <summary className="flex cursor-pointer flex-wrap items-center justify-between gap-2 px-3 py-2 text-[13px]">
                  <span>{rep.title} <span className="text-[11px] text-muted-foreground">- {rep.dataset_name}{rep.dataset_id === null ? " (dataset deleted)" : ""}</span></span>
                  <span className="text-[11px] text-muted-foreground">{new Date(rep.created_at).toLocaleString()}</span>
                </summary>
                <div className="space-y-3 border-t border-border p-3">
                  <AnalysisView a={{ ...rep.result, narrative: rep.narrative, narrative_source: rep.narrative_source as "llm" | "template" }} />
                  <div className="flex gap-2">
                    <button type="button" className="inline-flex items-center gap-1 border border-border px-2 py-1 text-[11px] hover:bg-accent"
                      onClick={() => void downloadReportCsv(rep.id).catch((e: Error) => toast.error(e.message))}><Download className="h-3 w-3" /> Export CSV</button>
                    <button type="button" className="inline-flex items-center gap-1 border border-border px-2 py-1 text-[11px] text-destructive hover:bg-accent"
                      onClick={() => delReport.mutate(rep.id, { onError: (e) => toast.error(e.message) })}><Trash2 className="h-3 w-3" /> Delete</button>
                  </div>
                </div>
              </details>
            ))}
          </section>
        </main>
      </div>
    </div>
  );
}
