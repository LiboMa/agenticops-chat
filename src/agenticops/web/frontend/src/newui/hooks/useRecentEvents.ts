import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { RecentEvents } from "../lib/pulse";

/** What happened in the last 24 hours (GET /api/ui/events, N15): the top bar's band and the map's replay read the
 *  same answer. Read again every minute. */
export function useRecentEvents(accountId: number | null) {
  return useQuery({
    queryKey: ["ui-events", accountId ?? "all"],
    queryFn: () => apiFetch<RecentEvents>(`/ui/events?hours=24${accountId != null ? `&account_id=${accountId}` : ""}`),
    refetchInterval: 60_000,
    staleTime: 30_000,
  });
}
