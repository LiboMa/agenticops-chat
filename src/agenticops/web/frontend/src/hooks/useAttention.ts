import { useQuery } from "@tanstack/react-query";
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
