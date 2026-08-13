import { createFileRoute } from "@tanstack/react-router";
import { Link } from "@tanstack/react-router";
import { AppShell } from "@/components/eaawp/AppShell";
import { AgentOrganism } from "@/components/eaawp/AgentOrganism";
import { ActivityStream } from "@/components/eaawp/ActivityStream";
import { ActiveTasks } from "@/components/eaawp/ActiveTasks";
import { ProactiveInsights } from "@/components/eaawp/ProactiveInsights";
import { MailBox } from "@/components/eaawp/MailBox";
import { KeyValue, Panel } from "@/components/eaawp/Panel";
import { knowledgeService } from "@/services";
import { useAgentStatus } from "@/state/useAgentStatus";

export const Route = createFileRoute("/workspace")({
  component: WorkspacePage,
});

function WorkspacePage() {
  const { status, label } = useAgentStatus();
  const k = knowledgeService.status();

  return (
    <AppShell>
      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="min-w-0 border-b border-border xl:border-b-0 xl:border-r">
          <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_300px]">
            <div className="grid-canvas relative border-b border-border lg:border-b-0 lg:border-r">
              <AgentOrganism status={status} withNetwork height={300} />
              <div className="absolute left-3 top-3">
                <div className="label-xs">AI environment</div>
                <div className="mt-1 font-mono text-[11px] text-primary">{label.toUpperCase()}</div>
              </div>
              <Link
                to="/meeting"
                className="absolute bottom-3 right-3 border border-border bg-surface px-2 py-1 font-mono text-[10px] tracking-[0.14em] text-muted-foreground hover:text-foreground"
              >
                OPEN MEETING ROOM
              </Link>
            </div>

            <Panel title="Knowledge status" dense className="border-b border-border lg:border-b-0">
              <div className="px-3 py-2">
                <KeyValue k="Documents indexed" v={k.documentsIndexed.toLocaleString()} />
                <KeyValue k="Knowledge sources" v={k.knowledgeSources} />
                <KeyValue k="Last synchronized" v={k.lastSync} />
                <KeyValue k="Knowledge updates" v={k.pendingUpdates} />
                <Link to="/library" className="mt-3 block font-mono text-[10px] tracking-[0.14em] text-primary">
                  OPEN LIBRARY →
                </Link>
              </div>
            </Panel>
          </div>

          <div className="grid grid-cols-1 border-t border-border lg:grid-cols-2">
            <Panel title="AI activity" dense className="max-h-[340px] border-b border-border lg:border-b-0 lg:border-r">
              <ActivityStream />
            </Panel>
            <Panel title="Active tasks" dense className="max-h-[340px]">
              <ActiveTasks />
            </Panel>
          </div>

          <Panel title="Mail / letter box" dense className="h-[300px] border-t border-border">
            <MailBox />
          </Panel>
        </div>

        <Panel
          title="Proactive insights"
          dense
          className="min-h-[400px] xl:h-[calc(100vh-3.5rem)]"
          actions={<span className="font-mono text-[10px] text-accent">UNPROMPTED</span>}
        >
          <ProactiveInsights />
        </Panel>
      </div>
    </AppShell>
  );
}
