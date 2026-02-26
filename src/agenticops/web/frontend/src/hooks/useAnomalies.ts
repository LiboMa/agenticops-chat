import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { Anomaly } from "@/api/types";

interface AnomalyFilters {
  severity?: string;
  status?: string;
  resource_type?: string;
}

export function useAnomalies(filters: AnomalyFilters = {}) {
  const params = new URLSearchParams();
  if (filters.severity) params.set("severity", filters.severity);
  if (filters.status) params.set("status", filters.status);
  if (filters.resource_type) params.set("resource_type", filters.resource_type);
  const qs = params.toString();

  return useQuery({
    queryKey: ["anomalies", filters],
    queryFn: () => apiFetch<Anomaly[]>(`/issues${qs ? `?${qs}` : ""}`),
    staleTime: 30_000,
  });
}
