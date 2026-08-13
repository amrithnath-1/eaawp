import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export function Panel({
  title,
  actions,
  children,
  className,
  bodyClassName,
  dense,
}: {
  title?: string;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
  dense?: boolean;
}) {
  return (
    <section className={cn("panel flex min-h-0 flex-col", className)}>
      {title && (
        <header className="flex h-9 shrink-0 items-center justify-between border-b border-border px-3">
          <h2 className="label-xs text-foreground">{title}</h2>
          {actions}
        </header>
      )}
      <div className={cn("min-h-0 flex-1", dense ? "" : "p-3", bodyClassName)}>{children}</div>
    </section>
  );
}

export function StatDot({ tone = "primary" }: { tone?: "primary" | "warning" | "destructive" | "success" | "muted" }) {
  const map = {
    primary: "bg-foreground",
    warning: "bg-border-strong",
    destructive: "bg-destructive",
    success: "bg-foreground",
    muted: "bg-muted-foreground",
  } as const;
  return <span className={cn("inline-block size-1.5 shrink-0 rounded-full", map[tone])} />;
}

export function Meter({ value, tone = "primary" }: { value: number; tone?: "primary" | "accent" | "success" }) {
  const map = { primary: "bg-foreground", accent: "bg-border-strong", success: "bg-foreground" } as const;
  return (
    <div className="h-1 w-full bg-muted">
      <div className={cn("h-full transition-[width] duration-700", map[tone])} style={{ width: `${value}%` }} />
    </div>
  );
}

export function KeyValue({ k, v }: { k: string; v: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-border py-1.5 last:border-0">
      <span className="label-xs">{k}</span>
      <span className="font-mono text-xs text-foreground">{v}</span>
    </div>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3 border-b border-border pb-3">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="mt-0.5 text-xs text-muted-foreground">{subtitle}</p>}
      </div>
      {actions}
    </div>
  );
}
