import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { IssueScope } from "@/lib/issueScope";

/** How many issues each Cases quick view holds (GET /api/health-issues/view-counts, MVP-2.8.0 S2), under the queue's
 *  scope and account. The key starts with "anomalies" so every issue invalidation refreshes it. */
export function useIssueViewCounts(scope: IssueScope | undefined, accountId?: number) {
  return useQuery({
    queryKey: ["anomalies", "view-counts", scope ?? "all", accountId ?? "all"],
    queryFn: () => {
      const qs = new URLSearchParams({ scope: scope ?? "all" });
      if (accountId) qs.set("account_id", String(accountId));
      // the server's issue views (its «mine» = the issue rows of «在等我», whose number comes from nav-counts)
      return apiFetch<Record<"all" | "mine" | "failed" | "long_wait", number>>(`/health-issues/view-counts?${qs}`);
    },
    staleTime: 30_000,
    refetchInterval: 30_000,
  });
}
