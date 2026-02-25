import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { RegionTopology } from "@/api/types";

export function useRegionTopology(region: string) {
  return useQuery({
    queryKey: ["region-topology", region],
    queryFn: () =>
      apiFetch<RegionTopology>(
        `/network/region-topology?region=${encodeURIComponent(region)}`,
      ),
    enabled: false, // manual trigger only
    staleTime: 2 * 60_000,
  });
}
