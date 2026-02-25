import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { Anomaly } from "@/api/types";

export function useAnomaly(id: number) {
  return useQuery({
    queryKey: ["anomaly", id],
    queryFn: () => apiFetch<Anomaly>(`/anomalies/${id}`),
    staleTime: 5 * 60_000,
  });
}
