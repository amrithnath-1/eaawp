import { useEffect, useRef, useState } from "react";
import { Bell } from "lucide-react";
import { Link } from "@tanstack/react-router";
import { USE_REAL_API } from "@/lib/api-client";
import { useMarkAllRead, useMarkNotificationRead, useNotifications, useUnreadNotificationCount } from "@/hooks/use-api";
import { cn } from "@/lib/utils";

/** Header bell: real unread count and the person's own notifications (no permanent dot). */
export function NotificationBell() {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const count = useUnreadNotificationCount();
  const list = useNotifications(false);
  const markOne = useMarkNotificationRead();
  const markAll = useMarkAllRead();
  const unread = count.data?.unread ?? 0;

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDown); document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey); };
  }, [open]);

  if (!USE_REAL_API) return null;
  const items = (list.data ?? []).slice(0, 15);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="relative grid size-9 place-items-center md:size-7"
        aria-label={unread ? `Notifications, ${unread} unread` : "Notifications"}
        aria-expanded={open}
        data-testid="notification-bell"
      >
        <Bell className="size-4 text-muted-foreground hover:text-foreground" strokeWidth={1.5} />
        {unread > 0 && (
          <span data-testid="notification-badge" className="absolute -right-1 -top-1 grid min-w-3.5 place-items-center rounded-full bg-foreground px-1 font-mono text-[9px] leading-[14px] text-background">
            {unread > 99 ? "99+" : unread}
          </span>
        )}
      </button>
      {open && (
        <div role="dialog" aria-label="Notifications" data-testid="notification-panel"
             className="fixed right-2 top-12 z-50 w-[min(22rem,calc(100vw-1rem))] border border-border bg-background shadow-lg md:absolute md:right-0 md:top-9">
          <div className="flex items-center justify-between border-b border-border px-3 py-2">
            <span className="label-xs">Notifications</span>
            <div className="flex items-center gap-3">
              <button type="button" disabled={unread === 0 || markAll.isPending} onClick={() => markAll.mutate()}
                      className="font-mono text-[10px] tracking-[0.12em] text-muted-foreground hover:text-foreground disabled:opacity-40">MARK ALL READ</button>
              <Link to="/settings" onClick={() => setOpen(false)} className="font-mono text-[10px] tracking-[0.12em] text-muted-foreground hover:text-foreground">SETTINGS</Link>
            </div>
          </div>
          <ul className="max-h-[60vh] overflow-y-auto">
            {items.length === 0 && <li className="px-3 py-6 text-center text-xs text-muted-foreground">No notifications yet.</li>}
            {items.map((n) => (
              <li key={n.id} className={cn("border-b border-border px-3 py-2 last:border-b-0", !n.is_read && "bg-surface")}>
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className={cn("truncate text-[13px]", !n.is_read && "font-medium")}>{n.title}</div>
                    {n.message && <div className="mt-0.5 line-clamp-2 text-[11px] text-muted-foreground">{n.message}</div>}
                    <div className="mt-1 font-mono text-[10px] text-muted-foreground">{new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(n.created_at) ? n.created_at : `${n.created_at}Z`).toLocaleString()}</div>
                  </div>
                  {!n.is_read && (
                    <button type="button" onClick={() => markOne.mutate(n.id)} className="shrink-0 font-mono text-[10px] tracking-[0.12em] text-muted-foreground hover:text-foreground">READ</button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
