import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { IssueStatus } from "@/api/types";

export function useUpdateIssueStatus() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, status }: { id: number; status: IssueStatus }) =>
      apiFetch<unknown>(`/issues/${id}/status`, {
        method: "PUT",
        body: JSON.stringify({ status }),
      }),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["anomaly", vars.id] });
      qc.invalidateQueries({ queryKey: ["anomalies"] });
    },
  });
}
