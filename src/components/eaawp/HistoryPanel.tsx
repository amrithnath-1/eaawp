/**
 * History: the signed-in person's own saved conversations with their AI employees (server-side, private).
 * Opening one goes to the Cabin with `?c=<id>`; a conversation with another AI employee opens read-only there.
 */
import { useState } from "react";
import { useNavigate, useSearch } from "@tanstack/react-router";
import { Check, Loader2, MessageSquarePlus, Pencil, Search, Trash2, X } from "lucide-react";
import { toast } from "sonner";
import { useCurrentWorkspace } from "@/state/workspace";
import { USE_REAL_API, apiErrorMessage } from "@/lib/api-client";
import {
  useConversations,
  useDeleteConversation,
  useRenameConversation,
  type ConversationSummary,
} from "@/hooks/use-conversations";
import { cn } from "@/lib/utils";

function when(iso: string): string {
  const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : `${iso}Z`);
  const diff = (Date.now() - d.getTime()) / 1000;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} h ago`;
  return d.toLocaleDateString([], {
    day: "numeric",
    month: "short",
    year: d.getFullYear() === new Date().getFullYear() ? undefined : "numeric",
  });
}

function Row({
  c,
  active,
  current,
}: {
  c: ConversationSummary;
  active: boolean;
  current: string | undefined;
}) {
  const navigate = useNavigate();
  const rename = useRenameConversation();
  const remove = useDeleteConversation();
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(c.title);
  const [confirm, setConfirm] = useState(false);
  const otherRole = !!current && c.role_key !== current;

  function save() {
    const t = title.trim();
    if (!t || t === c.title) {
      setEditing(false);
      setTitle(c.title);
      return;
    }
    rename.mutate(
      { id: c.id, title: t },
      {
        onSuccess: () => setEditing(false),
        onError: (e) => toast.error(apiErrorMessage(e)),
      },
    );
  }

  return (
    <li className={cn("group border-b border-border", active && "bg-foreground/5")}>
      {editing ? (
        <form
          className="flex items-center gap-1 px-3 py-2"
          onSubmit={(e) => {
            e.preventDefault();
            save();
          }}
        >
          <input
            autoFocus
            value={title}
            maxLength={200}
            aria-label="Conversation title"
            onChange={(e) => setTitle(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") {
                setEditing(false);
                setTitle(c.title);
              }
            }}
            className="h-7 min-w-0 flex-1 border border-input bg-background px-2 text-[12px] outline-none focus:border-ring"
          />
          <button
            type="submit"
            aria-label="Save title"
            className="grid size-7 place-items-center border border-border hover:bg-foreground/5"
          >
            {rename.isPending ? (
              <Loader2 className="size-3 animate-spin" />
            ) : (
              <Check className="size-3" />
            )}
          </button>
          <button
            type="button"
            aria-label="Cancel rename"
            onClick={() => {
              setEditing(false);
              setTitle(c.title);
            }}
            className="grid size-7 place-items-center border border-border hover:bg-foreground/5"
          >
            <X className="size-3" />
          </button>
        </form>
      ) : (
        <div className="flex items-start gap-1 px-3 py-2">
          <button
            onClick={() => void navigate({ to: "/cabin", search: { c: c.id } })}
            className="min-w-0 flex-1 text-left"
            aria-current={active ? "true" : undefined}
          >
            <p className="truncate text-[12px] text-foreground">{c.title}</p>
            <p className="mt-0.5 flex flex-wrap items-center gap-x-1.5 font-mono text-[9px] tracking-[0.08em] text-muted-foreground">
              <span className={cn(otherRole && "text-warning")}>{c.role_name.toUpperCase()}</span>
              <span>· {when(c.updated_at)}</span>
              <span>· {c.message_count} msg</span>
            </p>
          </button>
          <div className="flex shrink-0 gap-0.5 opacity-60 group-hover:opacity-100 group-focus-within:opacity-100">
            <button
              aria-label={`Rename ${c.title}`}
              onClick={() => setEditing(true)}
              className="grid size-6 place-items-center hover:bg-foreground/10"
            >
              <Pencil className="size-3" />
            </button>
            {confirm ? (
              <button
                aria-label="Confirm delete"
                onClick={() =>
                  remove.mutate(c.id, {
                    onSuccess: () => {
                      toast.success("Conversation deleted.");
                      if (active) void navigate({ to: "/cabin", search: { new: true } });
                    },
                    onError: (e) => toast.error(apiErrorMessage(e)),
                  })
                }
                className="h-6 border border-destructive/60 px-1.5 font-mono text-[9px] text-destructive hover:bg-destructive/10"
              >
                DELETE?
              </button>
            ) : (
              <button
                aria-label={`Delete ${c.title}`}
                onClick={() => setConfirm(true)}
                onBlur={() => setTimeout(() => setConfirm(false), 200)}
                className="grid size-6 place-items-center hover:bg-foreground/10"
              >
                <Trash2 className="size-3" />
              </button>
            )}
          </div>
        </div>
      )}
    </li>
  );
}

export function HistoryPanel() {
  const navigate = useNavigate();
  const ws = useCurrentWorkspace().data;
  const current = ws?.selected?.role_key;
  const search = useSearch({ strict: false }) as { c?: string };
  const [scope, setScope] = useState<"role" | "all">("role");
  const [q, setQ] = useState("");
  const { data, isLoading, isError, error, refetch, isFetching } = useConversations(
    scope === "role" ? (current ?? null) : null,
    q,
  );

  if (!USE_REAL_API) {
    return <p className="p-4 text-[12px] text-muted-foreground">History needs the live API.</p>;
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="shrink-0 space-y-2 border-b border-border p-3">
        <button
          onClick={() => void navigate({ to: "/cabin", search: { new: true } })}
          className="flex w-full items-center justify-center gap-1.5 border border-border py-1.5 font-mono text-[10px] tracking-[0.12em] hover:bg-foreground/5"
        >
          <MessageSquarePlus className="size-3.5" /> NEW CONVERSATION
        </button>
        <label className="flex items-center gap-1.5 border border-input bg-background px-2">
          <Search className="size-3 text-muted-foreground" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search conversations…"
            aria-label="Search conversations"
            className="h-7 min-w-0 flex-1 bg-transparent text-[12px] outline-none"
          />
          {isFetching && <Loader2 className="size-3 animate-spin text-muted-foreground" />}
        </label>
        <div className="flex gap-1" role="group" aria-label="Which conversations">
          {(["role", "all"] as const).map((s) => (
            <button
              key={s}
              aria-pressed={scope === s}
              onClick={() => setScope(s)}
              className={cn(
                "flex-1 border px-2 py-1 font-mono text-[9px] tracking-[0.1em]",
                scope === s
                  ? "border-foreground/40 text-foreground"
                  : "border-border text-muted-foreground hover:text-foreground",
              )}
            >
              {s === "role"
                ? (ws?.selected?.name ?? "THIS AI EMPLOYEE").toUpperCase()
                : "ALL AI EMPLOYEES"}
            </button>
          ))}
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {isLoading ? (
          <p className="flex items-center gap-2 p-4 text-[12px] text-muted-foreground">
            <Loader2 className="size-3 animate-spin" /> Loading conversations…
          </p>
        ) : isError ? (
          <div className="p-4 text-[12px] text-destructive">
            Could not load your history: {apiErrorMessage(error)}{" "}
            <button onClick={() => void refetch()} className="underline">
              Try again
            </button>
          </div>
        ) : !data?.items.length ? (
          <p className="p-4 text-[12px] text-muted-foreground">
            {q.trim()
              ? "No conversations match your search."
              : "No saved conversations yet. Your chats with this AI employee are saved here automatically and only you can see them."}
          </p>
        ) : (
          <ul aria-label="Saved conversations">
            {data.items.map((c) => (
              <Row key={c.id} c={c} active={search.c === c.id} current={current} />
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
