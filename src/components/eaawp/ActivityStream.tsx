import { FeedList } from "./FeedList";

/** Runs of the selected AI employee: what was asked, for whom, and how it ended. */
export function ActivityStream() {
  return (
    <FeedList
      kind="activity"
      noun="activity"
      empty="This AI employee has not run any requests yet."
    />
  );
}
