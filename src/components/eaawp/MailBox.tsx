import { useState } from "react";
import { Mic, Paperclip, SendHorizonal } from "lucide-react";
import { toast } from "sonner";
import { mailService } from "@/services";
import type { MailMessage } from "@/services/types";
import { cn } from "@/lib/utils";

const MODES = ["auto", "approval", "restricted"] as const;
const MODE_LABEL = { auto: "AUTO SEND", approval: "HUMAN APPROVAL", restricted: "RESTRICTED" } as const;

export function MailBox() {
  const [thread, setThread] = useState<MailMessage[]>(() => mailService.thread());
  const [text, setText] = useState("");
  const [mode, setMode] = useState<(typeof MODES)[number]>("approval");

  async function send() {
    if (!text.trim()) return;
    const msg = await mailService.send(text.trim());
    setThread((t) => [...t, msg]);
    setText("");
    setTimeout(() => {
      setThread((t) => [
        ...t,
        {
          id: `ai-${Date.now()}`,
          from: "ai",
          text:
            mode === "auto"
              ? "Instruction accepted. Executing under Level 3 autonomy and logging to the audit trail."
              : "Instruction accepted. Draft prepared — awaiting your approval before any external action.",
          time: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
          delivery: mode,
        },
      ]);
    }, 900);
  }

  return (
    <div className="flex h-full flex-col">
      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto px-3 py-2">
        {thread.map((m) => (
          <div
            key={m.id}
            className={cn(
              "border-l-2 pl-2.5",
              m.from === "ai" ? "border-primary" : "border-border-strong",
            )}
          >
            <div className="flex items-baseline gap-2 font-mono text-[10px] text-muted-foreground">
              <span className={m.from === "ai" ? "text-primary" : "text-foreground"}>
                {m.from === "ai" ? "AI" : "YOU"}
              </span>
              <span>{m.time}</span>
              {m.delivery && <span className="text-accent">{MODE_LABEL[m.delivery]}</span>}
            </div>
            <p className="mt-0.5 text-[13px] leading-snug">{m.text}</p>
          </div>
        ))}
      </div>

      <div className="shrink-0 border-t border-border">
        <div className="flex items-center gap-2 px-3 py-1.5">
          <span className="label-xs">Delivery policy</span>
          <div className="flex">
            {MODES.map((m) => (
              <button
                key={m}
                onClick={() => setMode(m)}
                className={cn(
                  "border px-2 py-0.5 font-mono text-[10px] tracking-[0.1em]",
                  mode === m ? "border-primary text-primary" : "border-border text-muted-foreground",
                )}
              >
                {MODE_LABEL[m]}
              </button>
            ))}
          </div>
        </div>
        <div className="flex items-end gap-2 border-t border-border px-3 py-2">
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void send();
              }
            }}
            rows={2}
            placeholder="Send something to your AI — instruction, document or question…"
            className="min-h-[38px] flex-1 resize-none bg-transparent text-[13px] outline-none placeholder:text-muted-foreground"
          />
          <button onClick={() => toast("Attach file — connect storage service")} aria-label="Attach file">
            <Paperclip className="size-4 text-muted-foreground hover:text-foreground" />
          </button>
          <button onClick={() => toast("Voice capture — connect speech service")} aria-label="Record voice">
            <Mic className="size-4 text-muted-foreground hover:text-foreground" />
          </button>
          <button
            onClick={() => void send()}
            className="flex items-center gap-1 border border-primary px-2.5 py-1.5 font-mono text-[10px] tracking-[0.14em] text-primary hover:bg-primary/10"
          >
            SEND <SendHorizonal className="size-3" />
          </button>
        </div>
      </div>
    </div>
  );
}
