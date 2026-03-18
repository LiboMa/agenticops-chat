import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { PaginatedResources } from "@/api/types";

interface ResourceFilters {
  type?: string;
  region?: string;
  account_id?: number;
  limit?: number;
  offset?: number;
}

export function useResources(filters: ResourceFilters = {}) {
  const params = new URLSearchParams();
  if (filters.type) params.set("type", filters.type);
  if (filters.region) params.set("region", filters.region);
  if (filters.account_id) params.set("account_id", String(filters.account_id));
  if (filters.limit) params.set("limit", String(filters.limit));
  if (filters.offset) params.set("offset", String(filters.offset));
  const qs = params.toString();

  return useQuery({
    queryKey: ["resources", filters],
    queryFn: () => apiFetch<PaginatedResources>(`/resources${qs ? `?${qs}` : ""}`),
    staleTime: 60_000,
  });
}
