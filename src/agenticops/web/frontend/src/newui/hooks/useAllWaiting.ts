import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import { ATTENTION_QUERY_KEY, type AttentionItem, type AttentionPage } from "@/lib/attention";

const PAGE = 100, PAGES_MAX = 20;

/** Everything that waits on the signed-in person in the account scope — every page, for «全景», which ties the map
 *  to the queue (which waiting items sit on a ringed resource, which on none). `complete` = false when the list was
 *  cut at 2,000: the map then says so instead of counting short. Under the attention key: a decision refreshes it. */
export function useAllWaiting(accountId: number | null, enabled = true) {
  return useQuery({
    queryKey: [...ATTENTION_QUERY_KEY, "nf-all", accountId ?? "all"],
    queryFn: async (): Promise<{ items: AttentionItem[]; complete: boolean }> => {
      const items: AttentionItem[] = [];
      let cursor: string | null = "0";
      for (let page = 0; cursor !== null && page < PAGES_MAX; page++) {
        const qs = new URLSearchParams({ limit: String(PAGE), cursor, sort: "severity" });
        if (accountId != null) qs.set("account_id", String(accountId));
        const got: AttentionPage = await apiFetch<AttentionPage>(`/ui/attention?${qs}`);
        items.push(...got.items);
        cursor = got.next_cursor;
      }
      return { items, complete: cursor === null };
    },
    enabled,
    refetchInterval: 60_000,
    staleTime: 20_000,
  });
}
