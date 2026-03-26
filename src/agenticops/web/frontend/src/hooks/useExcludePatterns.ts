import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";

interface ExcludePatternsResponse {
  patterns: string[];
}

export function useExcludePatterns() {
  return useQuery<ExcludePatternsResponse>({
    queryKey: ["excludePatterns"],
    queryFn: () => apiFetch<ExcludePatternsResponse>("/settings/issue-exclude-patterns"),
  });
}

export function useUpdateExcludePatterns() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (patterns: string[]) =>
      apiFetch<ExcludePatternsResponse>("/settings/issue-exclude-patterns", {
        method: "PATCH",
        body: JSON.stringify({ patterns }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["excludePatterns"] });
    },
  });
}
