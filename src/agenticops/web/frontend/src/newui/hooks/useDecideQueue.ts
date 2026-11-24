import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import { ATTENTION_QUERY_KEY, type AttentionPage } from "@/lib/attention";
import { reasonsParam, type QueueFilter } from "../lib/queue";

const PAGE = 50;

/** «待决»'s queue: GET /api/ui/attention sorted the way the design reads (sort=severity: the most severe first, then
 *  the longest wait; what the reader put off — «later», N14 — at the end of its severity), 50 a page. Polled — agents move work without any UI event — and under the attention key, so
 *  every decision that refreshes the classic top bar's number refreshes this list too. */
export function useDecideQueue({ accountId, filter }: { accountId: number | null; filter: QueueFilter }) {
  return useInfiniteQuery({
    queryKey: [...ATTENTION_QUERY_KEY, "nf-queue", accountId ?? "all", filter],
    initialPageParam: "0",
    queryFn: ({ pageParam }) => {
      const qs = new URLSearchParams({ limit: String(PAGE), cursor: pageParam, sort: "severity", snoozed: "last" });
      if (accountId != null) qs.set("account_id", String(accountId));
      const reason = reasonsParam(filter);
      if (reason) qs.set("reason", reason);
      return apiFetch<AttentionPage>(`/ui/attention?${qs}`);
    },
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    refetchInterval: 30_000,
    staleTime: 10_000,
  });
}

/** The number beside the «待决» tab: how many things wait on you in the account scope, whatever lens is open. */
export function useWaitingCounts(accountId: number | null) {
  return useQuery({
    queryKey: [...ATTENTION_QUERY_KEY, "nf-count", accountId ?? "all"],
    queryFn: () => apiFetch<AttentionPage>(`/ui/attention?limit=1&sort=severity${accountId != null ? `&account_id=${accountId}` : ""}`),
    select: (page) => page.counts ?? null,
    refetchInterval: 30_000,
    staleTime: 10_000,
  });
}
