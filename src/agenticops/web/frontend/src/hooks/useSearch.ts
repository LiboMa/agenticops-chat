import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { SearchResponse } from "@/api/types";

export function useSearch(query: string) {
  return useQuery({
    queryKey: ["search", query],
    queryFn: () => apiFetch<SearchResponse>(`/search?q=${encodeURIComponent(query)}`),
    enabled: query.length >= 1,
    staleTime: 5_000,
  });
}
