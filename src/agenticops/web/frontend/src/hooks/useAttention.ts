import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import { useBootstrap } from "@/hooks/useBootstrap";
import { ATTENTION_QUERY_KEY, type AttentionPage } from "@/lib/attention";

/** The work that waits on you (GET /api/ui/attention), within the account scope when one is set (MVP-2.7.0 S4).
 *  Polled: agents move work without any UI event. */
export function useAttention(accountId?: number | null) {
  const boot = useBootstrap();
  return useQuery({
    queryKey: [...ATTENTION_QUERY_KEY, accountId ?? "all"],
    queryFn: () => apiFetch<AttentionPage>(`/ui/attention?limit=100${accountId ? `&account_id=${accountId}` : ""}`),
    enabled: !!boot.data?.features.attention,
    refetchInterval: 30_000,
    staleTime: 10_000,
  });
}


/** «问题 · 在等我» (MVP-2.8.0, the to-do workbench merged into Issues): everything waiting on you, grouped by the
 *  decision it needs (sort=decision: pages only append to the last group), 50 a page by cursor. Under the attention
 *  key, so every mutation that invalidates the top bar's count refreshes it too. */
export function useWaitingPages(params: { accountId?: number | null; q: string }) {
  const boot = useBootstrap();
  return useInfiniteQuery({
    queryKey: [...ATTENTION_QUERY_KEY, "waiting", params.accountId ?? "all", params.q],
    initialPageParam: "0",
    queryFn: ({ pageParam }) => {
      const qs = new URLSearchParams({ limit: "50", cursor: pageParam, sort: "decision" });
      if (params.accountId) qs.set("account_id", String(params.accountId));
      if (params.q) qs.set("q", params.q);
      return apiFetch<AttentionPage>(`/ui/attention?${qs}`);
    },
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    enabled: !!boot.data?.features.attention,
    refetchInterval: 30_000,
    staleTime: 10_000,
  });
}
