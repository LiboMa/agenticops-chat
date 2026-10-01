import { useEffect, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { GalaxyBuildInfo, GalaxyStatus, GalaxyGraph } from "@/api/types";
import { buildLanded } from "@/lib/galaxy";

/** Build status; when a build completes (a rebuild, the hourly schedule or a rule-only refresh) the drawn graphs refetch. */
export function useGalaxyStatus() {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["galaxy-status"],
    queryFn: () => apiFetch<GalaxyStatus>("/galaxy/status"),
    refetchInterval: (q) =>
      q.state.data?.build?.status === "running" ? 5_000 : 60_000,
  });
  const prev = useRef<GalaxyBuildInfo | null | undefined>(undefined);
  useEffect(() => {
    if (!q.data) return;
    if (buildLanded(prev.current, q.data.build)) {
      qc.invalidateQueries({ queryKey: ["galaxy-graph"] });
      qc.invalidateQueries({ queryKey: ["graph-focus"] });
    }
    prev.current = q.data.build;
  }, [q.data, qc]);
  return q;
}

export function useGalaxyGraph() {
  return useQuery({
    queryKey: ["galaxy-graph"],
    queryFn: () => apiFetch<GalaxyGraph>("/galaxy/graph"),
    staleTime: 60_000,
  });
}

export function useGalaxyRebuild() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (full: boolean) =>
      apiFetch<{ build_id: number }>(`/galaxy/rebuild?full=${full}`, { method: "POST" }),
    // the status refetch sees the new build land, and useGalaxyStatus refreshes the graphs
    onSuccess: () => qc.invalidateQueries({ queryKey: ["galaxy-status"] }),
  });
}
