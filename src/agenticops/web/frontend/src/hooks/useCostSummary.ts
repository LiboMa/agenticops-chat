import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";

export interface CostTotals {
  input: number;
  output: number;
  cache_read: number;
  cache_write: number;
  total_tokens: number;
  cost_usd: number;
  cache_hit_pct: number;
  call_count: number;
}

export interface CostSeriesEntry {
  bucket: string;
  cost_usd: number;
  total_tokens: number;
  by: Record<string, { cost_usd: number; tokens: number }>;
}

export interface CostBreakdownEntry {
  key: string;
  calls: number;
  input: number;
  output: number;
  cache_read: number;
  cache_write: number;
  tokens: number;
  cache_hit_pct: number;
  cost_usd: number;
}

export interface CostSummaryData {
  totals: CostTotals;
  series: CostSeriesEntry[];
  breakdown: CostBreakdownEntry[];
}

interface CostSummaryParams {
  period?: string;
  bucket?: string;
  groupBy?: string;
  filters?: Record<string, string>;
}

export function useCostSummary(params?: CostSummaryParams) {
  const qs = new URLSearchParams();
  if (params?.period) qs.set("period", params.period);
  if (params?.bucket) qs.set("bucket", params.bucket);
  if (params?.groupBy) qs.set("group_by", params.groupBy);
  if (params?.filters) {
    for (const [k, v] of Object.entries(params.filters)) {
      if (v) qs.set(k, v);
    }
  }
  const query = qs.toString();

  return useQuery({
    queryKey: ["cost-summary", params],
    queryFn: () => apiFetch<CostSummaryData>(`/cost/summary${query ? `?${query}` : ""}`),
    staleTime: 30_000,
  });
}
