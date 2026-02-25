import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { AwsRegion } from "@/api/types";

export function useRegions() {
  return useQuery({
    queryKey: ["regions"],
    queryFn: () => apiFetch<AwsRegion[]>("/regions"),
    staleTime: Infinity,
  });
}
