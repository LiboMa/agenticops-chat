import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import { useBootstrap } from "@/hooks/useBootstrap";
import { ATTENTION_QUERY_KEY, type AttentionPage } from "@/lib/attention";

/** The work that waits on you (GET /api/ui/attention). Polled: agents move work without any UI event. */
export function useAttention() {
  const boot = useBootstrap();
  return useQuery({
    queryKey: [...ATTENTION_QUERY_KEY],
    queryFn: () => apiFetch<AttentionPage>("/ui/attention?limit=100"),
    enabled: !!boot.data?.features.attention,
    refetchInterval: 30_000,
    staleTime: 10_000,
  });
}
