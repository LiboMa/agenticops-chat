import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { SOPRecord, KBStats } from "@/api/types";

interface KBCase {
  filename: string;
  path: string;
  case_id: string;
  resource_type: string;
  severity: string;
  created_at: string;
  status: string;
  size_bytes: number;
  preview: string;
}

export function useKBStats() {
  return useQuery({
    queryKey: ["kb-stats"],
    queryFn: () => apiFetch<KBStats>("/kb/stats"),
    staleTime: 30_000,
    retry: 1,
  });
}

export function useKBSops(status?: string) {
  return useQuery({
    queryKey: ["kb-sops", status],
    queryFn: () =>
      apiFetch<{ count: number; sops: SOPRecord[] }>(
        status ? `/kb/sops?status=${status}` : "/kb/sops",
      ),
    staleTime: 30_000,
  });
}

export function useKBSop(id: number | null) {
  return useQuery({
    queryKey: ["kb-sop", id],
    queryFn: () => apiFetch<SOPRecord>(`/kb/sops/${id}`),
    enabled: id !== null,
    staleTime: 30_000,
  });
}

export function useKBCases() {
  return useQuery({
    queryKey: ["kb-cases"],
    queryFn: () => apiFetch<{ count: number; cases: KBCase[] }>("/kb/cases"),
    staleTime: 30_000,
  });
}

export function useApproveSop() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, approved_by }: { id: number; approved_by: string }) =>
      apiFetch<{ status: string; approved_by: string }>(
        `/kb/sops/${id}/approve`,
        { method: "POST", body: JSON.stringify({ approved_by }), headers: { "Content-Type": "application/json" } },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["kb-sops"] });
      qc.invalidateQueries({ queryKey: ["kb-sop"] });
      qc.invalidateQueries({ queryKey: ["kb-stats"] });
    },
  });
}

export function useRejectSop() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      apiFetch<{ status: string }>(`/kb/sops/${id}/reject`, { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["kb-sops"] });
      qc.invalidateQueries({ queryKey: ["kb-sop"] });
      qc.invalidateQueries({ queryKey: ["kb-stats"] });
    },
  });
}

export function useDeprecateSop() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      apiFetch<{ status: string }>(`/kb/sops/${id}/deprecate`, { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["kb-sops"] });
      qc.invalidateQueries({ queryKey: ["kb-sop"] });
      qc.invalidateQueries({ queryKey: ["kb-stats"] });
    },
  });
}
