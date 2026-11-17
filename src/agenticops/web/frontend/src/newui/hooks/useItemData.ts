import { useEffect, useRef } from "react";
import { useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { RCAResult } from "@/api/types";
import { parseItem } from "@/lib/inbox";

/** The issue's newest diagnosis as a page that DECIDES on it reads it: asked for again whenever the brief mounts,
 *  never taken from a cache. The classic hook keeps a diagnosis for five minutes; after «diagnose again» that was the
 *  old one — shown while the verdict went to the new one (final review). Same key as the classic hook, so whatever
 *  refreshes one refreshes the other. */
export function useFreshRca(issueId: number) {
  return useQuery({
    queryKey: ["anomaly-rca", issueId],
    queryFn: () => apiFetch<RCAResult | null>(`/issues/${issueId}/rca`),
    enabled: issueId > 0,
    staleTime: 0,
    refetchOnMount: "always",
  });
}

/** Everything a brief reads about one work item, marked stale: the diagnosis, the runs, the timeline, the plans —
 *  or the change. The queue row is refreshed every 30 s; what hangs off it is re-read when the row's page opens or
 *  the agent working on it ends. */
export function refreshItem(qc: QueryClient, item: string): void {
  const target = parseItem(item);
  if (!target) return;
  const keys = target.kind === "issue"
    ? [["anomaly-rca", target.id], ["issue-executions", target.id], ["issue-timeline", target.id], ["anomaly", target.id], ["fix-plans"], ["fix-plan"]]
    : [["change", target.id]];
  for (const queryKey of keys) qc.invalidateQueries({ queryKey });
}

/** Re-reads the item's data when its brief comes onto the page (a brief is a new component per item and per
 *  situation), and again when `lane` — the agent at work on it — goes away: it has just left a new diagnosis or a
 *  new plan. */
export function useItemRefresh(item: string, lane: unknown): void {
  const qc = useQueryClient();
  useEffect(() => { refreshItem(qc, item); }, [qc, item]);
  const had = useRef(!!lane);
  useEffect(() => {
    if (had.current && !lane) refreshItem(qc, item);
    had.current = !!lane;
  }, [qc, item, lane]);
}
