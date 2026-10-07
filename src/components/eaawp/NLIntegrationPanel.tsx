/**
 * NLIntegrationPanel — Natural Language Integration Setup
 *
 * Lets users connect integrations by describing what they want in plain English.
 * "Connect Google Search Console" → OAuth → capabilities → grant to employee.
 *
 * The LLM parses intent on the backend. The frontend only shows the response
 * and acts on next_action hints (redirect, show form, confirm grant).
 *
 * Credentials are NEVER handled by this component — OAuth flows redirect
 * the browser through the backend callback.
 */
import React, { useState, useRef, useEffect } from "react";
import { toast } from "sonner";
import {
  Send, Loader2, CheckCircle, XCircle, ExternalLink,
  ShieldCheck, Globe, Plug, RefreshCw, Zap,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  useNLIntegrationChat,
  useIntegrations,
  useTestIntegration,
  useGscAuthorize,
  useGaAuthorize,
  type NLConversationResponse,
} from "@/hooks/use-api";
import { AdminProviderConfigPanel } from "./AdminProviderConfigPanel";

interface Message {
  role: "user" | "assistant";
  content: string;
  next_action?: "NONE" | "REDIRECT_TO_OAUTH" | "SHOW_CAPABILITIES" | "REQUEST_CREDENTIALS" | "CONFIRM_GRANT" | "SHOW_STATUS" | "CLARIFY" | "OPEN_GITHUB_FORM" | "OPEN_MCP_FORM" | "OPEN_FACEBOOK_FORM" | "CONFIGURATION_REQUIRED" | "UNAVAILABLE";
  action_data?: Record<string, unknown>;
  timestamp: Date;
}

const QUICK_PROMPTS = [
  "Connect Google Search Console",
  "Connect Google Analytics",
  "Connect GitHub",
  "Connect an MCP server",
  "What integrations are available?",
  "Show me connected integrations",
];

export function NLIntegrationPanel({ onOpenTab }: { onOpenTab?: (tab: "github" | "mcp") => void }) {
  const [messages, setMessages] = useState<Message[]>([
    {
      role: "assistant",
      content:
        "Hi! I can help you connect integrations. Try saying:\n" +
        "• \"Connect Google Search Console\"\n" +
        "• \"Connect Google Analytics\"\n" +
        "• \"What integrations are available?\"\n\n" +
        "Credentials are handled securely — I will never ask for passwords or tokens.",
      timestamp: new Date(),
    },
  ]);
  const [input, setInput] = useState("");
  const [conversationId, setConversationId] = useState<string | undefined>();
  const bottomRef = useRef<HTMLDivElement>(null);

  const chatMutation = useNLIntegrationChat();
  const { data: integrations = [] } = useIntegrations();
  const testMutation = useTestIntegration();
  const gscAuth = useGscAuthorize();
  const gaAuth = useGaAuthorize();

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function send(text: string) {
    const trimmed = text.trim();
    if (!trimmed) return;

    setMessages((prev) => [...prev, { role: "user", content: trimmed, timestamp: new Date() }]);
    setInput("");

    chatMutation.mutate(
      { message: trimmed, ...(conversationId !== undefined ? { conversation_id: conversationId } : {}) },
      {
        onSuccess: (data: NLConversationResponse) => {
          setConversationId(data.conversation_id);
          setMessages((prev) => [
            ...prev,
            {
              role: "assistant" as const,
              content: data.reply,
              ...(data.next_action
                ? { next_action: data.next_action as NonNullable<Message["next_action"]> }
                : {}),
              action_data: data.action_data,
              timestamp: new Date(),
            },
          ]);
        },
        onError: (err) => {
          setMessages((prev) => [
            ...prev,
            {
              role: "assistant",
              content: `Error: ${err.message}`,
              timestamp: new Date(),
            },
          ]);
        },
      }
    );
  }

  function handleAction(action: string, data: Record<string, unknown>) {
    if (action === "REDIRECT_TO_OAUTH") {
      const provider = (data["provider_type"] as string | undefined) ?? "";
      if (provider === "google_search_console") {
        gscAuth.mutate(undefined, {
          onSuccess: (r) => { window.location.href = r.authorization_url; },
          onError: (e) => toast.error(e.message),
        });
      } else if (provider === "google_analytics") {
        gaAuth.mutate(undefined, {
          onSuccess: (r) => { window.location.href = r.authorization_url; },
          onError: (e) => toast.error(e.message),
        });
      } else {
        toast.info(`OAuth for ${provider} — use the Integration Manager to connect.`);
      }
    }
  }

  function renderMessageAction(msg: Message): React.ReactNode {
    if (msg.role !== "assistant") return null;
    const action = msg.next_action;
    const data = msg.action_data;
    if (!action || action === "NONE") return null;

    if (action === "REDIRECT_TO_OAUTH" && data) {
      return (
        <button
          onClick={() => handleAction(action, data)}
          className="mt-1.5 inline-flex items-center gap-1.5 border border-foreground/20 bg-foreground/5 px-2.5 py-1 font-mono text-[10px] tracking-[0.08em] hover:bg-foreground/10"
        >
          <ExternalLink className="size-3" />
          CONNECT WITH GOOGLE
        </button>
      );
    }

    if (action === "OPEN_GITHUB_FORM" || action === "OPEN_MCP_FORM") {
      const label = action === "OPEN_GITHUB_FORM" ? "GITHUB" : "MCP SERVER";
      const tab = action === "OPEN_GITHUB_FORM" ? "github" as const : "mcp" as const;
      return (
        <button
          onClick={() => onOpenTab?.(tab)}
          className="mt-1.5 inline-flex items-center gap-1.5 border border-foreground/20 bg-foreground/5 px-2.5 py-1 font-mono text-[10px] tracking-[0.08em] hover:bg-foreground/10"
        >
          <ExternalLink className="size-3" />
          {`OPEN ${label} SETUP`}
        </button>
      );
    }

    if (action === "CONFIGURATION_REQUIRED" && data?.["provider_type"]) {
      const providerType = String(data["provider_type"]);
      const displayName = data["provider_display_name"]
        ? String(data["provider_display_name"])
        : providerType;
      return (
        <div className="mt-2">
          <AdminProviderConfigPanel
            providerType={providerType}
            providerDisplayName={displayName}
            onConfigured={() => {
              const lastUserMsg = [...messages].reverse().find((m) => m.role === "user");
              if (lastUserMsg) {
                void send(lastUserMsg.content);
              }
            }}
          />
        </div>
      );
    }

    return null;
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="border-b border-border p-3">
        <p className="font-mono text-[10px] tracking-[0.14em] text-muted-foreground">
          NATURAL LANGUAGE INTEGRATION SETUP
        </p>
        <p className="text-[12px] text-muted-foreground mt-0.5">
          Describe what you want to connect. Credentials are never handled here.
        </p>
        {/* Connected summary */}
        {integrations.length > 0 && (
          <div className="flex flex-wrap gap-1 mt-2">
            {integrations.map((i) => (
              <span
                key={i.id}
                className={cn(
                  "inline-flex items-center gap-1 border px-1.5 py-0.5 font-mono text-[9px] tracking-[0.06em]",
                  i.status === "connected"
                    ? "border-success/40 text-success"
                    : "border-border text-muted-foreground"
                )}
              >
                {i.status === "connected" ? (
                  <CheckCircle className="size-2" />
                ) : (
                  <XCircle className="size-2" />
                )}
                {i.display_name}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-3 space-y-3">
        {messages.map((msg, i) => (
          <div
            key={i}
            className={cn(
              "max-w-[90%] rounded-none",
              msg.role === "user" ? "ml-auto" : "mr-auto"
            )}
          >
            <div
              className={cn(
                "border p-2.5 text-[12px] whitespace-pre-wrap",
                msg.role === "user"
                  ? "border-foreground/20 bg-foreground/5 text-foreground"
                  : "border-border bg-surface text-foreground"
              )}
            >
              {msg.content}
            </div>
            {/* Action buttons — rendered by helper to avoid TypeScript strict narrowing issues */}
            {renderMessageAction(msg)}
            <div className="mt-0.5 font-mono text-[9px] text-muted-foreground/50">
              {msg.timestamp.toLocaleTimeString()}
            </div>
          </div>
        ))}
        {chatMutation.isPending && (
          <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
            <Loader2 className="size-3 animate-spin" /> Thinking...
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Quick prompts */}
      <div className="border-t border-border px-3 py-2 flex flex-wrap gap-1">
        {QUICK_PROMPTS.map((p) => (
          <button
            key={p}
            onClick={() => void send(p)}
            className="border border-border/50 px-2 py-0.5 font-mono text-[9px] tracking-[0.06em] text-muted-foreground hover:border-foreground/30 hover:text-foreground"
          >
            {p}
          </button>
        ))}
      </div>

      {/* Input */}
      <div className="border-t border-border p-2 flex gap-2">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(input); } }}
          placeholder="Describe what you want to connect..."
          className="flex-1 h-8 border border-input bg-background px-2 text-[12px] outline-none focus:border-ring"
          disabled={chatMutation.isPending}
        />
        <button
          onClick={() => void send(input)}
          disabled={chatMutation.isPending || !input.trim()}
          className="h-8 w-8 border border-foreground/20 flex items-center justify-center hover:bg-foreground/5 disabled:opacity-40"
        >
          {chatMutation.isPending ? (
            <Loader2 className="size-3.5 animate-spin" />
          ) : (
            <Send className="size-3.5" />
          )}
        </button>
      </div>
    </div>
  );
}

export default NLIntegrationPanel;
