import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { RcaLocationStats } from "@/api/types";

/** Top-1 of the judged RCA locations and the issue anchoring rate over the last `days` days. */
export function useRcaLocationStats(days: number) {
  return useQuery({
    queryKey: ["rca-location-stats", days],
    queryFn: () => apiFetch<RcaLocationStats>(`/rca/location-stats?days=${days}`),
    staleTime: 60_000,
  });
}
