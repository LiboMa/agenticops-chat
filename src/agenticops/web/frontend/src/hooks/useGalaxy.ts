import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { GalaxyStatus, GalaxyOverview, GalaxyExpand, GalaxyGraph } from "@/api/types";

export function useGalaxyStatus() {
  return useQuery({
    queryKey: ["galaxy-status"],
    queryFn: () => apiFetch<GalaxyStatus>("/galaxy/status"),
    refetchInterval: (q) =>
      q.state.data?.build?.status === "running" ? 5_000 : 60_000,
  });
}

export function useGalaxyGraph() {
  return useQuery({
    queryKey: ["galaxy-graph"],
    queryFn: () => apiFetch<GalaxyGraph>("/galaxy/graph"),
    staleTime: 60_000,
  });
}

export function useGalaxyOverview() {
  return useQuery({
    queryKey: ["galaxy-overview"],
    queryFn: () => apiFetch<GalaxyOverview>("/galaxy/overview"),
    staleTime: 30_000,
  });
}

export function useGalaxyExpand(group: string | null, types: string[], worstOnly: boolean) {
  const params = new URLSearchParams();
  if (group) params.set("group", group);
  if (types.length) params.set("types", types.join(","));
  params.set("health", worstOnly ? "worst" : "all");
  return useQuery({
    queryKey: ["galaxy-expand", group, types.join(","), worstOnly],
    queryFn: () => apiFetch<GalaxyExpand>(`/galaxy/expand?${params.toString()}`),
    enabled: !!group,
  });
}

export function useGalaxyRebuild() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (full: boolean) =>
      apiFetch<{ build_id: number }>(`/galaxy/rebuild?full=${full}`, { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["galaxy-status"] });
      qc.invalidateQueries({ queryKey: ["galaxy-overview"] });
      qc.invalidateQueries({ queryKey: ["galaxy-expand"] });
    },
  });
}
