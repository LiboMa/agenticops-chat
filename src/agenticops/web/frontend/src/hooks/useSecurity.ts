import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type {
  AttackPathItem,
  SecurityFindingItem,
  SecurityRecommendationItem,
  SecuritySummary,
  SecurityTrendPoint,
} from "@/api/types";

export function useSecuritySummary() {
  return useQuery({
    queryKey: ["security-summary"],
    queryFn: () => apiFetch<SecuritySummary>("/security/summary"),
    staleTime: 30_000,
  });
}

export function useSecurityTrend(days = 30, account?: string) {
  const qs = account ? `?days=${days}&account=${encodeURIComponent(account)}` : `?days=${days}`;
  return useQuery({
    queryKey: ["security-trend", days, account ?? ""],
    queryFn: () => apiFetch<SecurityTrendPoint[]>(`/security/trend${qs}`),
    staleTime: 30_000,
  });
}

export function useSecurityFindings(limit = 100) {
  return useQuery({
    queryKey: ["security-findings", limit],
    queryFn: () => apiFetch<SecurityFindingItem[]>(`/security/findings?limit=${limit}`),
    staleTime: 30_000,
  });
}

export function useSecurityRecommendations(status = "open") {
  return useQuery({
    queryKey: ["security-recommendations", status],
    queryFn: () =>
      apiFetch<SecurityRecommendationItem[]>(`/security/recommendations?status=${status}`),
    staleTime: 30_000,
  });
}

export function useAttackPaths() {
  return useQuery({
    queryKey: ["security-attack-paths"],
    queryFn: () => apiFetch<AttackPathItem[]>("/security/attack-paths"),
    staleTime: 30_000,
  });
}
