import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { Signal } from "@/api/types";

export function useSignals(filters: { disposition?: string; kind?: string } = {}) {
  const params = new URLSearchParams();
  if (filters.disposition) params.set("disposition", filters.disposition);
  if (filters.kind) params.set("kind", filters.kind);
  params.set("limit", "100");
  const qs = params.toString();
  return useQuery({
    queryKey: ["signals", filters],
    queryFn: () => apiFetch<Signal[]>(`/signals?${qs}`),
    refetchInterval: 15_000,
  });
}

export function usePromoteSignal() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (signalId: number) =>
      apiFetch<{ health_issue_id: number }>(`/signals/${signalId}/promote`, {
        method: "POST",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["signals"] });
      queryClient.invalidateQueries({ queryKey: ["anomalies"] });
    },
  });
}

export function useRcaFeedback(issueId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: { verdict: "correct" | "incorrect"; note?: string }) =>
      apiFetch<{ rca_id: number }>(`/health-issues/${issueId}/rca-feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["anomaly-rca", issueId] });
    },
  });
}
