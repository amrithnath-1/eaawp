/**
 * MessagesPanel - private one-to-one messages between active members of the company.
 * Only the two participants can read a conversation (administrators cannot).
 */
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Loader2, Send, ArrowLeft } from "lucide-react";
import { cn } from "@/lib/utils";
import { useConversations, useMessagePeople, useMessageThread, useSendMessage } from "@/hooks/use-api";

const when = (s: string) => new Date(s).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });

function Thread({ userId, onBack }: { userId: string; onBack: () => void }) {
  const t = useMessageThread(userId);
  const send = useSendMessage(userId);
  const [text, setText] = useState("");
  const end = useRef<HTMLDivElement>(null);
  const count = t.data?.messages.length ?? 0;
  useEffect(() => { end.current?.scrollIntoView?.({ block: "end" }); }, [count]);
  const peer = t.data?.peer;
  return (
    <div className="flex h-[70vh] flex-col border border-border bg-surface" data-testid="thread">
      <div className="flex items-center gap-2 border-b border-border px-3 py-2 text-[13px]">
        <button type="button" aria-label="Back to conversations" className="md:hidden" onClick={onBack}><ArrowLeft className="h-4 w-4" /></button>
        <strong>{peer?.name ?? "…"}</strong>{peer && !peer.active && <span className="font-mono text-[9px] text-muted-foreground">DEACTIVATED</span>}
      </div>
      <ol className="flex-1 space-y-2 overflow-y-auto p-3" aria-label="Messages">
        {t.isLoading && <Loader2 className="h-4 w-4 animate-spin" />}
        {t.data?.messages.length === 0 && <li className="text-[12px] text-muted-foreground">No messages yet. Say hello.</li>}
        {t.data?.messages.map((m) => (
          <li key={m.id} className={cn("max-w-[80%] border px-2.5 py-1.5 text-[13px]", m.from_me ? "ml-auto border-primary/40 bg-primary/10" : "border-border bg-background")}>
            <div className="whitespace-pre-wrap break-words">{m.body}</div>
            <div className="mt-0.5 text-[10px] text-muted-foreground">{when(m.created_at)}</div>
          </li>))}
        <div ref={end} />
      </ol>
      {peer?.active === false ? <p className="border-t border-border p-3 text-[12px] text-muted-foreground">This person is deactivated, so you can't send them messages.</p> : (
        <form className="flex gap-2 border-t border-border p-2" onSubmit={(e) => { e.preventDefault(); const v = text.trim(); if (!v) return; send.mutate(v, { onSuccess: () => setText(""), onError: (er) => toast.error(er.message) }); }}>
          <input value={text} onChange={(e) => setText(e.target.value)} maxLength={2000} aria-label="Message" placeholder="Write a message" className="min-w-0 flex-1 border border-border bg-background px-2 py-1.5 text-[13px]" />
          <button type="submit" disabled={send.isPending || !text.trim()} className="inline-flex items-center gap-1 border border-border bg-primary px-3 py-1.5 text-[12px] text-primary-foreground disabled:opacity-50"><Send className="h-3 w-3" /> Send</button>
        </form>)}
    </div>
  );
}

export function MessagesPanel() {
  const convs = useConversations();
  const people = useMessagePeople();
  const [sel, setSel] = useState<string | null>(null);
  const known = new Set((convs.data ?? []).map((c) => c.user_id));
  const others = (people.data ?? []).filter((p) => !known.has(p.id));
  return (
    <div className="mx-auto max-w-5xl space-y-4 p-4 sm:p-6">
      <header><h1 className="text-lg font-semibold">Messages</h1><p className="text-[12px] text-muted-foreground">Private conversations with people in your company. Only you and the other person can read them.</p></header>
      <div className="grid gap-4 md:grid-cols-[280px_1fr]">
        <nav aria-label="Conversations" className={cn("space-y-3", sel && "hidden md:block")}>
          <ul className="space-y-1">
            {(convs.data ?? []).map((c) => (
              <li key={c.user_id}><button type="button" onClick={() => setSel(c.user_id)} className={cn("block w-full border px-3 py-2 text-left text-[12px]", sel === c.user_id ? "border-primary bg-surface" : "border-border hover:bg-accent")}>
                <div className="flex items-center justify-between gap-2"><span className="truncate font-medium">{c.name}</span>{c.unread > 0 && <span data-testid="unread-chip" className="bg-primary px-1.5 font-mono text-[10px] text-primary-foreground">{c.unread}</span>}</div>
                <div className="truncate text-muted-foreground">{c.last_from_me ? "You: " : ""}{c.last_body}</div>
              </button></li>))}
          </ul>
          {(convs.data ?? []).length === 0 && !convs.isLoading && <p className="text-[12px] text-muted-foreground">No conversations yet.</p>}
          {others.length > 0 && (
            <label className="block text-[11px]">Start a conversation
              <select aria-label="Start a conversation" value="" onChange={(e) => e.target.value && setSel(e.target.value)} className="mt-1 w-full border border-border bg-background px-2 py-1.5 text-[13px]">
                <option value="">Choose a person…</option>{others.map((p) => <option key={p.id} value={p.id}>{p.name} ({p.role})</option>)}
              </select></label>)}
        </nav>
        <section aria-label="Conversation">{sel ? <Thread key={sel} userId={sel} onBack={() => setSel(null)} /> : <p className="hidden text-[13px] text-muted-foreground md:block">Select a conversation or start a new one.</p>}</section>
      </div>
    </div>
  );
}
