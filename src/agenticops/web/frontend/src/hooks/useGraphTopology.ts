import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { SerializedGraph, AnomalyReport, ReachabilityResult } from "@/api/types";

export function useVpcGraph(region: string, vpcId: string) {
  return useQuery({
    queryKey: ["vpc-graph", region, vpcId],
    queryFn: () =>
      apiFetch<SerializedGraph>(
        `/graph/vpc/${encodeURIComponent(vpcId)}?region=${encodeURIComponent(region)}`,
      ),
    enabled: false, // manual trigger only
    staleTime: 2 * 60_000,
  });
}

export function useRegionGraph(region: string) {
  return useQuery({
    queryKey: ["region-graph", region],
    queryFn: () =>
      apiFetch<SerializedGraph>(
        `/graph/region?region=${encodeURIComponent(region)}`,
      ),
    enabled: false, // manual trigger only
    staleTime: 2 * 60_000,
  });
}

export function useVpcAnomalies(region: string, vpcId: string) {
  return useQuery({
    queryKey: ["vpc-anomalies", region, vpcId],
    queryFn: () =>
      apiFetch<AnomalyReport>(
        `/graph/vpc/${encodeURIComponent(vpcId)}/anomalies?region=${encodeURIComponent(region)}`,
      ),
    enabled: false,
    staleTime: 2 * 60_000,
  });
}

export function useSubnetReachability(region: string, vpcId: string, subnetId: string) {
  return useQuery({
    queryKey: ["subnet-reachability", region, vpcId, subnetId],
    queryFn: () =>
      apiFetch<ReachabilityResult>(
        `/graph/vpc/${encodeURIComponent(vpcId)}/reachability/${encodeURIComponent(subnetId)}?region=${encodeURIComponent(region)}`,
      ),
    enabled: false,
    staleTime: 2 * 60_000,
  });
}
