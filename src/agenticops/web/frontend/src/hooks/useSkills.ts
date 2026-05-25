import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type {
  Skill,
  SkillDetail,
  SkillGenerateRequest,
  SkillGenerateResponse,
  SkillDraftRequest,
  SkillReviewData,
  SkillImproveResponse,
  SkillImprovementRecord,
} from "@/api/types";

export function useSkills() {
  return useQuery({
    queryKey: ["skills"],
    queryFn: () => apiFetch<Skill[]>("/skills"),
    staleTime: 60_000,
  });
}

export function useSkill(name: string) {
  return useQuery({
    queryKey: ["skill", name],
    queryFn: () => apiFetch<SkillDetail>(`/skills/${encodeURIComponent(name)}`),
    enabled: !!name,
    staleTime: 5 * 60_000,
  });
}

export function useGenerateSkill() {
  return useMutation({
    mutationFn: (data: SkillGenerateRequest) =>
      apiFetch<SkillGenerateResponse>("/skills/generate", {
        method: "POST",
        body: JSON.stringify(data),
      }),
  });
}

export function useSaveDraft() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: SkillDraftRequest) =>
      apiFetch<{ name: string; path: string }>("/skills/draft", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["skills"] }),
  });
}

export function useImportSkill() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (file: File) => {
      const formData = new FormData();
      formData.append("file", file);
      const headers: Record<string, string> = {};
      const token = localStorage.getItem("aiops_token");
      if (token) headers["Authorization"] = `Bearer ${token}`;
      const res = await fetch("/api/skills/import", {
        method: "POST",
        headers,
        body: formData,
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(body.detail ?? res.statusText);
      }
      return res.json() as Promise<{ name: string; path: string }>;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["skills"] }),
  });
}

export function useDeleteSkill() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) =>
      apiFetch<{ deleted: boolean; name: string }>(
        `/skills/${encodeURIComponent(name)}`,
        { method: "DELETE" },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["skills"] }),
  });
}

export function useUpdateSkill() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ name, content }: { name: string; content: string }) =>
      apiFetch<{ updated: boolean; name: string }>(`/skills/${encodeURIComponent(name)}`, {
        method: "PUT",
        body: JSON.stringify({ content }),
      }),
    onSuccess: (_, { name }) => {
      qc.invalidateQueries({ queryKey: ["skills"] });
      qc.invalidateQueries({ queryKey: ["skill", name] });
    },
  });
}

export function useReviewSkill() {
  return useMutation({
    mutationFn: (name: string) =>
      apiFetch<SkillReviewData>(`/skills/${encodeURIComponent(name)}/review`, { method: "POST" }),
  });
}

export function usePromoteSkill() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) =>
      apiFetch<{ promoted: boolean; name: string }>(`/skills/${encodeURIComponent(name)}/promote`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["skills"] }),
  });
}

export function useImproveSkill() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ name, improvement, trigger }: { name: string; improvement: string; trigger?: string }) =>
      apiFetch<SkillImproveResponse>(`/skills/${encodeURIComponent(name)}/improve`, {
        method: "POST",
        body: JSON.stringify({ improvement, trigger: trigger ?? "manual", source: "web" }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["skills"] });
      qc.invalidateQueries({ queryKey: ["skill-improvements"] });
    },
  });
}

export function useSkillImprovements(status: "all" | "pending" | "history" = "all", limit = 50) {
  return useQuery({
    queryKey: ["skill-improvements", status, limit],
    queryFn: () => apiFetch<SkillImprovementRecord[]>(`/skills/improvements?status=${status}&limit=${limit}`),
    staleTime: 30_000,
  });
}

export function useSkillImprovementHistory(limit = 50) {
  return useQuery({
    queryKey: ["skill-improvements", "history", limit],
    queryFn: () => apiFetch<SkillImprovementRecord[]>(`/skills/improvements?status=history&limit=${limit}`),
    staleTime: 30_000,
  });
}

export function useBatchDismissImprovements() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (ids: string[]) =>
      apiFetch<{ results: { id: string; dismissed: boolean }[] }>("/skills/improvements/batch-dismiss", {
        method: "POST",
        body: JSON.stringify({ ids }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["skill-improvements"] }),
  });
}
