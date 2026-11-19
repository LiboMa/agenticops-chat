import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import { findingsRequest, type FindingsQuery } from "@/lib/security";
import type {
  AttackPathItem,
  SecurityFindingPage,
  SecurityRecommendationItem,
  SecuritySummary,
  SecurityTrend,
} from "@/api/types";

// Every module takes the account of the top bar's scope (undefined = all accounts) — MVP-2.9.0 N20.
const scoped = (path: string, accountId: number | undefined, sep: "?" | "&") =>
  accountId === undefined ? path : `${path}${sep}account_id=${accountId}`;

export function useSecuritySummary(accountId?: number) {
  return useQuery({
    queryKey: ["security-summary", accountId ?? null],
    queryFn: () => apiFetch<SecuritySummary>(scoped("/security/summary", accountId, "?")),
    staleTime: 30_000,
  });
}

export function useSecurityTrend(days = 30, accountId?: number) {
  return useQuery({
    queryKey: ["security-trend", days, accountId ?? null],
    queryFn: () => apiFetch<SecurityTrend>(scoped(`/security/trend?days=${days}`, accountId, "&")),
    staleTime: 30_000,
  });
}

/** One page of findings; the previous page stays on screen while the next one loads. */
export function useSecurityFindings(query: FindingsQuery, accountId?: number) {
  const path = findingsRequest(query, accountId);
  return useQuery({
    queryKey: ["security-findings", path],
    queryFn: () => apiFetch<SecurityFindingPage>(path),
    staleTime: 30_000,
    placeholderData: keepPreviousData,
  });
}

export function useSecurityRecommendations(status = "open", accountId?: number) {
  return useQuery({
    queryKey: ["security-recommendations", status, accountId ?? null],
    queryFn: () =>
      apiFetch<SecurityRecommendationItem[]>(scoped(`/security/recommendations?status=${status}`, accountId, "&")),
    staleTime: 30_000,
  });
}

export function useAttackPaths(accountId?: number) {
  return useQuery({
    queryKey: ["security-attack-paths", accountId ?? null],
    queryFn: () => apiFetch<AttackPathItem[]>(scoped("/security/attack-paths", accountId, "?")),
    staleTime: 30_000,
  });
}
