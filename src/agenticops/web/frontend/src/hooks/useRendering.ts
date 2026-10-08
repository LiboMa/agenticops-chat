import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { ContentRendering } from "@/api/types";

/** One language of one report version (MVP-2.7.0 S6) — reading never translates; polled while it is being prepared. */
export function useRendering(reportId: number, version: number | undefined, language: "zh" | "en", enabled = true) {
  return useQuery({
    queryKey: ["rendering", "report", reportId, version, language],
    queryFn: () => apiFetch<ContentRendering>(`/content/report/${reportId}/rendering?version=${version}&language=${language}`),
    enabled: enabled && reportId > 0 && !!version,
    refetchInterval: (q) => (q.state.data?.status === "pending" ? 4_000 : false),
  });
}

/** «Prepare translation» / «Retry»: queue the languages that are missing, failed or stale. */
export function useRequestTranslation(reportId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { version: number; languages: ("zh" | "en")[] }) =>
      apiFetch<ContentRendering[]>(`/content/report/${reportId}/translations`, {
        method: "POST", body: JSON.stringify({ source_version: v.version, languages: v.languages }) }),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["rendering", "report", reportId] });
      qc.invalidateQueries({ queryKey: ["reports"] });
    },
  });
}
