import { FeedList } from "./FeedList";

/** Waiting and scheduled work: approvals, saved setup requests, scheduled workflows and delegated meeting tasks. */
export function ActiveTasks() {
  return (
    <FeedList
      kind="tasks"
      noun="tasks"
      empty="Nothing is waiting or scheduled for this AI employee."
    />
  );
}
