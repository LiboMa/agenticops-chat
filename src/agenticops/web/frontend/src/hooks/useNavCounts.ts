import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { NavCounts } from "@/api/types";
import { useBootstrap } from "@/hooks/useBootstrap";
import { useAccountScope } from "@/components/layout/AccountScope";
import { ATTENTION_QUERY_KEY } from "@/lib/attention";

/** The sidebar's and the top bar's numbers (MVP-2.8.0 direction A), one request every 30 s — under the attention
 *  key, so every mutation that refreshes the to-do list refreshes these too. Follows the top bar's account scope. */
export function useNavCounts() {
  const boot = useBootstrap();
  const { accountId } = useAccountScope();
  return useQuery({
    queryKey: [...ATTENTION_QUERY_KEY, "nav-counts", accountId ?? "all"],
    queryFn: () => apiFetch<NavCounts>(`/ui/nav-counts${accountId ? `?account_id=${accountId}` : ""}`),
    enabled: !!boot.data?.user,
    refetchInterval: 30_000,
    staleTime: 10_000,
  });
}
