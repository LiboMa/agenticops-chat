import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";

export function useResourceTypeCounts(includeAbsent = false) {
  return useQuery({
    queryKey: ["resourceTypeCounts", includeAbsent],
    queryFn: () =>
      apiFetch<Record<string, number>>(`/resources/type-counts${includeAbsent ? "?include_absent=true" : ""}`),
    staleTime: 60_000,
  });
}
