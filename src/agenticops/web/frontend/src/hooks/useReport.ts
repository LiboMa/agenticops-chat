import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { Report } from "@/api/types";

export function useReport(id: number) {
  return useQuery({
    queryKey: ["report", id],
    queryFn: () => apiFetch<Report>(`/reports/${id}`),
    enabled: id > 0,
  });
}
