import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { PlanStats } from "@/api/types";
import { toQuery, type Period } from "@/lib/plans";

export function usePlanStats(opts: { period: Period; kind: "all" | "fix" | "change"; bucket?: "day" | "week" }) {
  const params = { ...opts, bucket: opts.bucket ?? "day" };
  return useQuery({
    queryKey: ["plan-stats", params],
    queryFn: () => apiFetch<PlanStats>(`/plans/stats${toQuery(params)}`),
    staleTime: 30_000,
  });
}
