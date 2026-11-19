import { useMemo } from "react";
import { useInfiniteQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { ChangeRequestPage, HealthIssuePage } from "@/api/types";
import { changesRequest, issuesRequest, itemRows, nextOffset, type ItemRow, type ItemsQuery } from "../lib/items";

/** The «all items» table's data: pages of issues or of change requests, loaded one after another. The filters, the
 *  search and the order are the server's; `total` is the answer's own count. Under the keys the rest of the app
 *  already invalidates ("anomalies", "changes"), so a decision made elsewhere refreshes the table. */
export function useAllItems(q: ItemsQuery, accountId: number | null) {
  const issues = useInfiniteQuery({
    queryKey: ["anomalies", "health-issues", "all-items", q, accountId],
    enabled: q.kind === "issue",
    initialPageParam: 0,
    queryFn: ({ pageParam }) => apiFetch<HealthIssuePage>(issuesRequest(q, accountId, pageParam)),
    getNextPageParam: (last, pages) => nextOffset(pages.reduce((n, p) => n + p.items.length, 0), last.total, last.items.length),
    staleTime: 15_000,
  });
  const changes = useInfiniteQuery({
    queryKey: ["changes", "all-items", q, accountId],
    enabled: q.kind === "change",
    initialPageParam: 0,
    queryFn: ({ pageParam }) => apiFetch<ChangeRequestPage>(changesRequest(q, accountId, pageParam)),
    getNextPageParam: (last, pages) => nextOffset(pages.reduce((n, p) => n + p.items.length, 0), last.total, last.items.length),
    staleTime: 15_000,
  });
  const active = q.kind === "issue" ? issues : changes;
  const rows = useMemo<ItemRow[]>(() => (
    q.kind === "issue" ? itemRows("issue", (issues.data?.pages ?? []).flatMap((p) => p.items))
                       : itemRows("change", (changes.data?.pages ?? []).flatMap((p) => p.items))
  ), [q.kind, issues.data, changes.data]);
  const pages = active.data?.pages;
  return {
    rows,
    /** how many match in all — the newest answer's count; null until an answer is in */
    total: pages?.length ? pages[pages.length - 1].total : null,
    status: (active.data ? "ready" : active.isError ? "failed" : "loading") as "ready" | "failed" | "loading",
    /** the last answer is older than the newest attempt (a refresh failed): when it came (ms) */
    staleAt: active.isError && active.data ? active.dataUpdatedAt : null,
    hasMore: !!active.hasNextPage, more: () => { void active.fetchNextPage(); },
    loadingMore: active.isFetchingNextPage, moreFailed: active.isFetchNextPageError,
    retry: () => { void active.refetch(); },
  };
}
