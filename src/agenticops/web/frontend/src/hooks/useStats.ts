import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { Stats } from "@/api/types";

export function useStats() {
  return useQuery({
    queryKey: ["stats"],
    queryFn: () => apiFetch<Stats>("/stats"),
    staleTime: 5_000,
    refetchInterval: 10_000,
  });
}
