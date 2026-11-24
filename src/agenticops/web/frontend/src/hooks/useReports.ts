import { keepPreviousData, useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import { nextOffset, reportsRequest, type ReportsQuery } from "@/lib/reports";
import type { Report, ReportFromSessionRequest, ReportPage } from "@/api/types";

/** The reports list, searched / dated / counted by the server (MVP-2.9.0 N21), one page at a time. The previous
 *  query's rows stay on screen while the next one loads. */
export function useReportsList(query: ReportsQuery) {
  return useInfiniteQuery({
    queryKey: ["reports", "list", query.q.trim(), query.from, query.to],
    queryFn: ({ pageParam }) => apiFetch<ReportPage>(reportsRequest(query, pageParam)),
    initialPageParam: 0,
    getNextPageParam: (last, pages) => nextOffset(pages.reduce((n, p) => n + p.items.length, 0), last.total, last.items.length),
    staleTime: 60_000,
    placeholderData: keepPreviousData,
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
