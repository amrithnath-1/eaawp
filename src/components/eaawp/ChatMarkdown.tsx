/**
 * Renders an AI employee's answer as Markdown (headings, lists, tables, code, links).
 * Raw HTML in the text is NOT rendered (react-markdown's default), so a model or a document cannot inject markup.
 * Links open in a new tab without passing the opener.
 */
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { cn } from "@/lib/utils";
import { chartProblem, normalizeChartSpec, type ChartSpec } from "@/lib/charts";
import { ChartFallback, ChatChart } from "@/components/eaawp/ChatChart";

/** Languages whose fenced blocks may hold legacy chart JSON (a bare ``` block has no language). */
const CHART_LANGS = new Set(["json", "chart"]);

interface HastLike {
  type?: string;
  tagName?: string;
  value?: string;
  properties?: { className?: unknown };
  children?: HastLike[];
}

function hastText(n: HastLike | undefined): string {
  if (!n) return "";
  if (n.type === "text") return n.value ?? "";
  return (n.children ?? []).map(hastText).join("");
}

/**
 * Legacy safety net: older saved answers sometimes carry a chart as a JSON code block. When the block is
 * complete, parseable JSON that is chart-shaped, return the specs to draw; otherwise null (render as code).
 */
function legacyChartsFromCodeBlock(node: unknown): ChartSpec[] | null {
  const pre = node as HastLike | undefined;
  const code = pre?.children?.find((c) => c.type === "element" && c.tagName === "code");
  if (!code) return null;
  const cls = code.properties?.className;
  const classes = Array.isArray(cls)
    ? cls.map(String)
    : typeof cls === "string"
      ? cls.split(/\s+/)
      : [];
  const lang = classes
    .find((c) => c.startsWith("language-"))
    ?.slice("language-".length)
    .toLowerCase();
  if (lang !== undefined && !CHART_LANGS.has(lang)) return null;
  const text = hastText(code).trim();
  if (!text.startsWith("{") && !text.startsWith("[")) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    return null; // incomplete or invalid JSON stays a code block
  }
  const items = Array.isArray(parsed) ? parsed : [parsed];
  if (items.length === 0) return null;
  const specs = items.map(normalizeChartSpec);
  if (specs.some((s) => s === null)) return null;
  return specs as ChartSpec[];
}

function LegacyCharts({ specs }: { specs: ChartSpec[] }) {
  return (
    <div className="my-2 flex w-full min-w-0 flex-col gap-2">
      {specs.map((raw, i) => {
        // Drawn from an older answer's text: the server never verified these numbers, so say so.
        const s: ChartSpec = {
          ...raw,
          note: raw.note ?? "Drawn from the text of an earlier answer; not verified against tool results.",
        };
        const problem = chartProblem(s);
        return problem ? (
          <ChartFallback key={i} spec={s} reason={problem} />
        ) : (
          <ChatChart key={i} spec={s} />
        );
      })}
    </div>
  );
}

const components: Components = {
  h1: ({ children }) => (
    <h3 className="mt-3 mb-1 text-[15px] font-semibold first:mt-0">{children}</h3>
  ),
  h2: ({ children }) => (
    <h3 className="mt-3 mb-1 text-[14px] font-semibold first:mt-0">{children}</h3>
  ),
  h3: ({ children }) => (
    <h4 className="mt-2.5 mb-1 text-[13px] font-semibold first:mt-0">{children}</h4>
  ),
  h4: ({ children }) => (
    <h4 className="mt-2 mb-1 text-[13px] font-semibold first:mt-0">{children}</h4>
  ),
  p: ({ children }) => <p className="my-1.5 first:mt-0 last:mb-0">{children}</p>,
  ul: ({ children }) => <ul className="my-1.5 list-disc space-y-0.5 pl-5">{children}</ul>,
  ol: ({ children }) => <ol className="my-1.5 list-decimal space-y-0.5 pl-5">{children}</ol>,
  li: ({ children }) => <li className="pl-0.5">{children}</li>,
  a: ({ href, children }) => (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="underline underline-offset-2 hover:text-primary"
    >
      {children}
    </a>
  ),
  strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
  blockquote: ({ children }) => (
    <blockquote className="my-2 border-l-2 border-border-strong pl-3 text-muted-foreground">
      {children}
    </blockquote>
  ),
  code: ({ className, children }) => (
    <code className={cn("rounded-sm bg-muted px-1 py-0.5 font-mono text-[12px]", className)}>
      {children}
    </code>
  ),
  pre: ({ node, children }) => {
    const specs = legacyChartsFromCodeBlock(node);
    if (specs) return <LegacyCharts specs={specs} />;
    return (
      <pre className="my-2 overflow-x-auto border border-border bg-muted/60 p-2 font-mono text-[12px] [&>code]:bg-transparent [&>code]:p-0">
        {children}
      </pre>
    );
  },
  table: ({ children }) => (
    <div className="my-2 max-w-full overflow-x-auto">
      <table className="w-full border-collapse text-[12px]">{children}</table>
    </div>
  ),
  th: ({ children }) => (
    <th className="border border-border bg-muted/50 px-2 py-1 text-left font-semibold">
      {children}
    </th>
  ),
  td: ({ children }) => <td className="border border-border px-2 py-1 align-top">{children}</td>,
  hr: () => <hr className="my-3 border-border" />,
};

export function ChatMarkdown({ text, className }: { text: string; className?: string }) {
  return (
    <div className={cn("min-w-0 break-words text-[13px] leading-relaxed", className)}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {text}
      </ReactMarkdown>
    </div>
  );
}
