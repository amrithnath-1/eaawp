import { useTasks } from "@/hooks/use-api";
import { USE_REAL_API } from "@/lib/api-client";

type ApiTask = {
  id: string;
  name: string;
  goal?: string;
  status: string;
  progress?: number;
  department?: string;
  started_at?: string;
  required_action?: string | null;
};

export function ActiveTasks() {
  const { data, isLoading, isError } = useTasks();
  if (!USE_REAL_API) return <StateMessage>Live tasks are unavailable while demo mode is enabled.</StateMessage>;
  if (isLoading) return <StateMessage>Loading company tasks…</StateMessage>;
  if (isError) return <StateMessage>Could not load company tasks. Check the connection and retry.</StateMessage>;
  const tasks = (data ?? []) as unknown as ApiTask[];
  if (tasks.length === 0) return <StateMessage>No company tasks have been created yet.</StateMessage>;

  return (
    <ul className="h-full overflow-y-auto">
      {tasks.map((task) => (
        <li key={task.id} className="border-b border-border px-3 py-2.5 last:border-0">
          <div className="flex items-baseline justify-between gap-2">
            <span className="truncate text-[13px] font-medium">{task.name}</span>
            <span className="font-mono text-[10px] text-muted-foreground">{(task.status || "unknown").replaceAll("_", " ").toUpperCase()}</span>
          </div>
          {task.goal && <p className="mt-1 text-xs text-muted-foreground">{task.goal}</p>}
          <div className="mt-1 font-mono text-[10px] text-muted-foreground">
            {task.department || "Company"}{task.started_at ? ` · ${new Date(task.started_at).toLocaleString()}` : ""}
          </div>
          {task.required_action && <p className="mt-1 text-xs">Needs action: {task.required_action}</p>}
        </li>
      ))}
    </ul>
  );
}

function StateMessage({ children }: { children: string }) {
  return <div className="px-3 py-6 text-center text-xs text-muted-foreground">{children}</div>;
}
