import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";

export function useResourceTypeCounts() {
  return useQuery({
    queryKey: ["resourceTypeCounts"],
    queryFn: () => apiFetch<Record<string, number>>("/resources/type-counts"),
    staleTime: 60_000,
  });
}
