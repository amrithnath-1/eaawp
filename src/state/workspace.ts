import { useSession } from "@/state/session";
import { useWorkspace } from "@/hooks/use-api";

/** The signed-in person's AI employee workspace (shared query; safe to call from any page inside the shell). */
export function useCurrentWorkspace() {
  const { user } = useSession();
  return useWorkspace(user?.id);
}
