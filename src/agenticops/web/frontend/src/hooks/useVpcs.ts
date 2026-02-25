import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { VpcListResponse } from "@/api/types";

export function useVpcs(region: string) {
  return useQuery({
    queryKey: ["vpcs", region],
    queryFn: () =>
      apiFetch<VpcListResponse>(`/network/vpcs?region=${encodeURIComponent(region)}`),
    enabled: false, // manual trigger only
    staleTime: 60_000,
  });
}
