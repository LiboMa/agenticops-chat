import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { RCAResult } from "@/api/types";

export function useAnomalyRca(anomalyId: number) {
  return useQuery({
    queryKey: ["anomaly-rca", anomalyId],
    queryFn: () => apiFetch<RCAResult | null>(`/anomalies/${anomalyId}/rca`),
    staleTime: 5 * 60_000,
  });
}
