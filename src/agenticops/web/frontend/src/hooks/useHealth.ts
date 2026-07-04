import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";

export interface HealthCheck {
  status: string; // "ok" | "error" | "warning"
  latency_ms?: number | null;
  error?: string | null;
  details?: Record<string, unknown> | null;
}

export interface HealthData {
  status: string; // "healthy" | "degraded" | "unhealthy"
  version: string;
  timestamp: string;
  checks: Record<string, HealthCheck>;
}

export function useHealth() {
  return useQuery({
    queryKey: ["health"],
    queryFn: () => apiFetch<HealthData>("/health"),
    refetchInterval: 10_000,
    staleTime: 5_000,
  });
}
