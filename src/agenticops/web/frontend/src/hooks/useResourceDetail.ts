import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { Resource, Anomaly, FixPlanWithExecutions, RelatedResources } from "@/api/types";

export function useResource(id: number) {
  return useQuery({
    queryKey: ["resource", id],
    queryFn: () => apiFetch<Resource>(`/resources/${id}`),
    enabled: id > 0,
  });
}

export function useResourceIssues(id: number, enabled: boolean) {
  return useQuery({
    queryKey: ["resourceIssues", id],
    queryFn: () => apiFetch<Anomaly[]>(`/resources/${id}/issues`),
    enabled: id > 0 && enabled,
    staleTime: 30_000,
  });
}

export function useResourceFixPlans(id: number, enabled: boolean) {
  return useQuery({
    queryKey: ["resourceFixPlans", id],
    queryFn: () => apiFetch<FixPlanWithExecutions[]>(`/resources/${id}/fix-plans`),
    enabled: id > 0 && enabled,
    staleTime: 30_000,
  });
}

export function useResourceRelated(id: number, enabled: boolean) {
  return useQuery({
    queryKey: ["resourceRelated", id],
    queryFn: () => apiFetch<RelatedResources>(`/resources/${id}/related`),
    enabled: id > 0 && enabled,
    staleTime: 60_000,
  });
}
