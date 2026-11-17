import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import { ATTENTION_QUERY_KEY, type AttentionItem, type AttentionPage } from "@/lib/attention";

/** Whether one item is on the signed-in person's own list (GET /api/ui/attention?item=I12), and as what — whatever
 *  the account scope: an item that waits on you waits on you in every scope. null = it does not wait on you.
 *  Under the attention key, so every decision refreshes it. */
export function useMyItem(item: string | null) {
  return useQuery({
    queryKey: [...ATTENTION_QUERY_KEY, "nf-item", item],
    queryFn: async (): Promise<AttentionItem | null> =>
      (await apiFetch<AttentionPage>(`/ui/attention?limit=1&item=${encodeURIComponent(item ?? "")}`)).items.find((i) => i.id === item) ?? null,
    enabled: !!item,
    refetchInterval: 30_000,
    staleTime: 10_000,
  });
}
