import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { Report, ReportFromSessionRequest } from "@/api/types";

export function useReports() {
  return useQuery({
    queryKey: ["reports"],
    queryFn: () => apiFetch<Report[]>("/reports"),
    staleTime: 60_000,
  });
}

export function useCreateReportFromSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req: ReportFromSessionRequest) =>
      apiFetch<Report>("/reports/from-session", {
        method: "POST",
        body: JSON.stringify(req),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["reports"] }),
  });
}
