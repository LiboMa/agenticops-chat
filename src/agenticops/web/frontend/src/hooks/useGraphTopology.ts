import { useQuery, useMutation } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { SerializedGraph, AnomalyReport, ReachabilityResult, SPOFReport, CapacityRiskReport, DependencyChainResult, ChangeSimulationResult } from "@/api/types";

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

export function useMultiRegionGraph(regions: string[]) {
  const regionsParam = regions.join(",");
  return useQuery({
    queryKey: ["multi-region-graph", regionsParam],
    queryFn: () =>
      apiFetch<SerializedGraph>(
        `/graph/multi-region?regions=${encodeURIComponent(regionsParam)}`,
      ),
    enabled: false, // manual trigger only
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

/* ------------------------------------------------------------------ */
/*  SRE Analysis hooks                                                 */
/* ------------------------------------------------------------------ */

export function useEnrichedVpcGraph(region: string, vpcId: string) {
  return useQuery({
    queryKey: ["enriched-vpc-graph", region, vpcId],
    queryFn: () =>
      apiFetch<SerializedGraph>(
        `/graph/vpc/${encodeURIComponent(vpcId)}/enriched?region=${encodeURIComponent(region)}`,
      ),
    enabled: false,
    staleTime: 2 * 60_000,
  });
}

export function useSPOFAnalysis(region: string, vpcId: string) {
  return useQuery({
    queryKey: ["spof-analysis", region, vpcId],
    queryFn: () =>
      apiFetch<SPOFReport>(
        `/graph/vpc/${encodeURIComponent(vpcId)}/spof?region=${encodeURIComponent(region)}`,
      ),
    enabled: false,
    staleTime: 2 * 60_000,
  });
}

export function useCapacityRisk(region: string, vpcId: string, threshold: number = 0.8) {
  return useQuery({
    queryKey: ["capacity-risk", region, vpcId, threshold],
    queryFn: () =>
      apiFetch<CapacityRiskReport>(
        `/graph/vpc/${encodeURIComponent(vpcId)}/capacity-risk?region=${encodeURIComponent(region)}&threshold=${threshold}`,
      ),
    enabled: false,
    staleTime: 2 * 60_000,
  });
}

export function useDependencyChain(region: string, vpcId: string) {
  return useMutation({
    mutationFn: (faultNodeId: string) =>
      apiFetch<DependencyChainResult>(
        `/graph/vpc/${encodeURIComponent(vpcId)}/dependency-chain?fault_node_id=${encodeURIComponent(faultNodeId)}&region=${encodeURIComponent(region)}`,
        { method: "POST" },
      ),
  });
}

export function useChangeSimulation(region: string, vpcId: string) {
  return useMutation({
    mutationFn: ({ edgeSource, edgeTarget }: { edgeSource: string; edgeTarget: string }) =>
      apiFetch<ChangeSimulationResult>(
        `/graph/vpc/${encodeURIComponent(vpcId)}/change-simulation?edge_source=${encodeURIComponent(edgeSource)}&edge_target=${encodeURIComponent(edgeTarget)}&region=${encodeURIComponent(region)}`,
        { method: "POST" },
      ),
  });
}
