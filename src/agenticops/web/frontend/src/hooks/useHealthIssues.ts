import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { HealthIssue } from "@/api/types";
import type { IssueScope } from "@/lib/issueScope";

/** GET /api/health-issues filters (MVP-2.7.0 S4) — all applied on the server; status and severity are comma lists. */
export interface HealthIssueFilters {
  scope?: IssueScope;
  status?: string;
  severity?: string;
  q?: string;
  sort?: "newest" | "oldest" | "severity";
  account_id?: number;
  limit?: number;
}

export function healthIssuesQuery(filters: HealthIssueFilters): string {
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(filters)) {
    if (v !== undefined && v !== null && v !== "") params.set(k, String(v));
  }
  const qs = params.toString();
  return `/health-issues${qs ? `?${qs}` : ""}`;
}

/** The key starts with "anomalies" so every existing invalidation of the issue lists still reaches it. */
export function useHealthIssues(filters: HealthIssueFilters = {}) {
  return useQuery({
    queryKey: ["anomalies", "health-issues", filters],
    queryFn: () => apiFetch<HealthIssue[]>(healthIssuesQuery(filters)),
    staleTime: 30_000,
  });
}
