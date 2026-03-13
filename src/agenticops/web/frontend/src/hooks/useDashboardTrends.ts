import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { DashboardTrends } from "@/api/types";

export function useDashboardTrends(days: number = 7) {
  return useQuery({
    queryKey: ["dashboardTrends", days],
    queryFn: () => apiFetch<DashboardTrends>(`/dashboard/trends?days=${days}`),
    staleTime: 60_000,
  });
}
