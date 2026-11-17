import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { Activity } from "../lib/activity";

export const ACTIVITY_QUERY_KEY = ["ui-activity"] as const;

/** What agents are doing now (GET /api/ui/activity), within the account scope. Polled: agents work without any UI
 *  event, and a run a person just asked for must show up without a reload. */
export function useActivity(accountId: number | null) {
  return useQuery({
    queryKey: [...ACTIVITY_QUERY_KEY, accountId ?? "all"],
    queryFn: () => apiFetch<Activity>(`/ui/activity${accountId != null ? `?account_id=${accountId}` : ""}`),
    refetchInterval: 10_000,
    staleTime: 5_000,
  });
}
