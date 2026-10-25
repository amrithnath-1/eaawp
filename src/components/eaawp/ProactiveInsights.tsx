import { FeedList } from "./FeedList";

/** Completed answers that were built on data a tool actually read, with their sources. */
export function ProactiveInsights() {
  return (
    <FeedList
      kind="insights"
      noun="insights"
      empty="No data-backed analysis yet. Insights appear here when an answer was built on data a tool read."
    />
  );
}
