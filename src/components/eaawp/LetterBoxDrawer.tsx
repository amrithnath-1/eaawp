import { X } from "lucide-react";
import { MailBox } from "./MailBox";

/** Letter Box — the AI's communication inbox/outbox, opened from the header. */
export function LetterBoxDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-start">
      <div className="absolute inset-0 bg-background/70" onClick={onClose} />
      <aside className="relative flex h-full w-full max-w-[520px] flex-col border-r border-border bg-surface">
        <header className="flex h-12 shrink-0 items-center justify-between border-b border-border px-4">
          <div>
            <span className="label-xs text-foreground">Letter box</span>
            <p className="mt-0.5 text-[11px] text-muted-foreground">
              Incoming and outgoing agent communication · sending follows company policy
            </p>
          </div>
          <button onClick={onClose} aria-label="Close letter box">
            <X className="size-4 text-muted-foreground hover:text-foreground" />
          </button>
        </header>
        <div className="min-h-0 flex-1">
          <MailBox />
        </div>
      </aside>
    </div>
  );
}
