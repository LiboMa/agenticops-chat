import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { Report } from "@/api/types";

export function useReports() {
  return useQuery({
    queryKey: ["reports"],
    queryFn: () => apiFetch<Report[]>("/reports"),
    staleTime: 60_000,
  });
}
