import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { PlanStats } from "@/api/types";
import type { Period } from "@/lib/plans";

export function usePlanStats(opts: { period: Period; kind: "all" | "fix" | "change"; bucket?: "day" | "week" }) {
  const qs = `period=${opts.period}&kind=${opts.kind}&bucket=${opts.bucket ?? "day"}`;
  return useQuery({ queryKey: ["plan-stats", opts], queryFn: () => apiFetch<PlanStats>(`/plans/stats?${qs}`), staleTime: 30_000 });
}
