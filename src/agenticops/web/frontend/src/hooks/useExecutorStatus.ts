import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";

interface ExecutorStatus {
  enabled: boolean;
  running: boolean;
  active_executions: number;
  poll_interval: number;
  auto_resolve: boolean;
}

export function useExecutorStatus() {
  return useQuery({
    queryKey: ["executor-status"],
    queryFn: () => apiFetch<ExecutorStatus>("/executor/status"),
    staleTime: 15_000,
    retry: 1,
  });
}
