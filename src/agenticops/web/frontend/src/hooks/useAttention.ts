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


/** The workbench's pages (MVP-2.8.0 S2): the decision's reasons, the search, the longest wait first; 50 a page by
 *  cursor. Under the attention key, so every mutation that invalidates the top bar's count refreshes it too. */
export function useInboxPages(params: { accountId?: number | null; reasons: string[] | null; q: string }) {
  const boot = useBootstrap();
  return useInfiniteQuery({
    queryKey: [...ATTENTION_QUERY_KEY, "inbox", params.accountId ?? "all", params.reasons?.join(",") ?? "", params.q],
    initialPageParam: "0",
    queryFn: ({ pageParam }) => {
      const qs = new URLSearchParams({ limit: "50", cursor: pageParam, sort: "waiting_longest" });
      if (params.accountId) qs.set("account_id", String(params.accountId));
      if (params.reasons) qs.set("reason", params.reasons.join(","));
      if (params.q) qs.set("q", params.q);
      return apiFetch<AttentionPage>(`/ui/attention?${qs}`);
    },
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    enabled: !!boot.data?.features.attention,
    refetchInterval: 30_000,
    staleTime: 10_000,
  });
}
