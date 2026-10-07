import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { ConnectorStatus } from "@/api/types";

/** Pull connectors with their newest runs; polls faster while one is running. */
export function useConnectors(limit = 5) {
  return useQuery({
    queryKey: ["connectors", limit],
    queryFn: () => apiFetch<{ connectors: ConnectorStatus[] }>(`/connectors?limit=${limit}`),
    refetchInterval: (q) => (q.state.data?.connectors.some((c) => c.running) ? 5_000 : 30_000),
  });
}

/** Run every target of a connector now; 202 — the runs land in GET /api/connectors. */
export function useRunConnector() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) =>
      apiFetch<{ connector: string; status: string }>(`/connectors/${encodeURIComponent(name)}/run`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["connectors"] }),
  });
}
