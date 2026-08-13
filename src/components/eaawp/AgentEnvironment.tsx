import { useNavigate } from "@tanstack/react-router";
import { AgentOrganism } from "./AgentOrganism";
import { useAgentStatus } from "@/state/useAgentStatus";
import { cn } from "@/lib/utils";

/**
 * Free-floating AI environment layer (organism + department network).
 * No card, no rectangular container — it floats over the intelligence area
 * and is itself the Meeting Room entry point.
 */
export function AgentEnvironment({
  height = 230,
  withNetwork = true,
  className,
}: {
  height?: number;
  withNetwork?: boolean;
  className?: string;
}) {
  const { status, label } = useAgentStatus();
  const navigate = useNavigate();

  return (
    <div className={cn("pointer-events-none select-none", className)}>
      <button
        type="button"
        onClick={() => navigate({ to: "/meeting" })}
        title="Open Meeting Room"
        aria-label={`Open Meeting Room — agent ${label.toLowerCase()}`}
        className="group pointer-events-auto relative block w-full bg-transparent text-left outline-none"
      >
        <div className="flex items-center justify-end gap-1.5 px-3 pt-2 font-mono text-[10px] tracking-[0.14em] text-muted-foreground">
          <span className="inline-block size-1.5 rounded-full bg-foreground" />
          {label.toUpperCase()}
        </div>

        <AgentOrganism status={status} withNetwork={withNetwork} height={height} />

        <span className="pointer-events-none absolute inset-x-0 bottom-0 hidden justify-center group-hover:flex">
          <span className="border border-border bg-popover px-2 py-1 font-mono text-[10px] tracking-[0.12em] text-popover-foreground">
            OPEN MEETING ROOM
          </span>
        </span>
      </button>
    </div>
  );
}
