/**
 * EmailDraftPreview — Renders a structured email draft in the chat.
 *
 * Shown when the DMM's response contains a draft_email action result.
 * Parses the structured draft_preview from the agent message and displays
 * a clear email card with To / Subject / Body / Purpose / Sources.
 *
 * SECURITY: Never displays SMTP credentials, connection details, or
 * internal database information.
 */

import { Mail, Users, FileText, Info, Send } from "lucide-react";
import { cn } from "@/lib/utils";

export interface DraftPreviewData {
  draft_id: string;
  recipients: string[];
  subject: string;
  body_preview: string;
  purpose: string;
  evidence_sources: string[];
  status: "draft" | "sent" | "rejected" | "cancelled";
}

/**
 * Parse a draft_preview object from the agent's message text.
 * The DraftEmailAction embeds a structured preview in its result message.
 */
export function parseDraftPreview(messageText: string): DraftPreviewData | null {
  // Look for JSON block with draft_preview marker
  try {
    // The planner result_summary or message may contain draft_preview JSON
    // We look for the structured fields in the message text
    const recipientMatch = messageText.match(/To:\s*([^\n]+)/);
    const subjectMatch = messageText.match(/Subject:\s*([^\n]+)/);
    const bodyMatch = messageText.match(/Body preview:\s*([\s\S]*?)(?=\nPurpose:|$)/);
    const purposeMatch = messageText.match(/Purpose:\s*([^\n]+)/);
    const draftIdMatch = messageText.match(/draft[_\s]?id[:\s]+([a-f0-9-]{36})/i);

    if (!subjectMatch && !recipientMatch) return null;

    return {
      draft_id: draftIdMatch?.[1] ?? "",
      recipients: recipientMatch?.[1]?.split(",").map((r) => r.trim()).filter(Boolean) ?? [],
      subject: subjectMatch?.[1]?.trim() ?? "",
      body_preview: bodyMatch?.[1]?.trim() ?? "",
      purpose: purposeMatch?.[1]?.trim() ?? "",
      evidence_sources: [],
      status: "draft",
    };
  } catch {
    return null;
  }
}

export function EmailDraftPreview({
  draft,
  className,
}: {
  draft: DraftPreviewData;
  className?: string;
}) {
  const isDraft = draft.status === "draft";
  const isSent = draft.status === "sent";
  const isRejected = draft.status === "rejected" || draft.status === "cancelled";

  return (
    <div
      className={cn(
        "mt-2 w-full border bg-surface text-left",
        isDraft && "border-border",
        isSent && "border-success/30",
        isRejected && "border-border opacity-60",
        className,
      )}
    >
      {/* Header */}
      <div
        className={cn(
          "flex items-center justify-between border-b border-border px-3 py-2",
          isDraft && "bg-surface-2",
        )}
      >
        <div className="flex items-center gap-1.5">
          <Mail className="size-3.5 text-primary" strokeWidth={1.5} />
          <span className="font-mono text-[10px] tracking-widest text-muted-foreground">
            EMAIL DRAFT
          </span>
        </div>
        <span
          className={cn(
            "border px-1.5 py-0.5 font-mono text-[9px] tracking-widest",
            isDraft && "border-warning/40 text-warning",
            isSent && "border-success/40 text-success",
            isRejected && "border-border text-muted-foreground",
          )}
        >
          {draft.status.toUpperCase()}
        </span>
      </div>

      {/* Fields */}
      <div className="space-y-0 divide-y divide-border">
        {/* To */}
        {draft.recipients.length > 0 && (
          <div className="flex items-start gap-2 px-3 py-2">
            <Users className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" strokeWidth={1.5} />
            <div className="min-w-0">
              <span className="mr-2 font-mono text-[10px] text-muted-foreground">TO</span>
              <span className="text-[12px]">{draft.recipients.join(", ")}</span>
            </div>
          </div>
        )}

        {/* Subject */}
        {draft.subject && (
          <div className="flex items-start gap-2 px-3 py-2">
            <FileText className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" strokeWidth={1.5} />
            <div className="min-w-0">
              <span className="mr-2 font-mono text-[10px] text-muted-foreground">SUBJECT</span>
              <span className="text-[13px] font-medium">{draft.subject}</span>
            </div>
          </div>
        )}

        {/* Body preview */}
        {draft.body_preview && (
          <div className="px-3 py-2">
            <p className="mb-1 font-mono text-[10px] text-muted-foreground">BODY PREVIEW</p>
            <p className="text-[12px] leading-relaxed text-muted-foreground">
              {draft.body_preview}
              {draft.body_preview.endsWith("...") && (
                <span className="italic"> (truncated)</span>
              )}
            </p>
          </div>
        )}

        {/* Purpose */}
        {draft.purpose && (
          <div className="flex items-start gap-2 px-3 py-2">
            <Info className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" strokeWidth={1.5} />
            <div>
              <span className="mr-2 font-mono text-[10px] text-muted-foreground">PURPOSE</span>
              <span className="text-[12px] text-muted-foreground">{draft.purpose}</span>
            </div>
          </div>
        )}

        {/* Evidence sources */}
        {draft.evidence_sources.length > 0 && (
          <div className="px-3 py-2">
            <p className="mb-1 font-mono text-[10px] text-muted-foreground">EVIDENCE</p>
            <ul className="space-y-0.5">
              {draft.evidence_sources.map((s) => (
                <li key={s} className="font-mono text-[10px] text-primary">
                  ● {s}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {/* Footer note */}
      {isDraft && (
        <div className="border-t border-border px-3 py-1.5">
          <p className="flex items-center gap-1 font-mono text-[10px] text-muted-foreground">
            <Send className="size-3" strokeWidth={1.5} />
            Awaiting human approval before sending · HIGH risk action
          </p>
        </div>
      )}
    </div>
  );
}
