import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { VpcTopology } from "@/api/types";

export function useVpcTopology(region: string, vpcId: string) {
  return useQuery({
    queryKey: ["vpc-topology", region, vpcId],
    queryFn: () =>
      apiFetch<VpcTopology>(
        `/network/vpc-topology?region=${encodeURIComponent(region)}&vpc_id=${encodeURIComponent(vpcId)}`,
      ),
    enabled: false, // manual trigger only
    staleTime: 2 * 60_000,
  });
}
