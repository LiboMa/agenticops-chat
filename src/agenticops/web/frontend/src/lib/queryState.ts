/** The four data states every module shows (MVP-2.8.0 S1): loading, failed, empty, ready — plus `stale` when a
 *  refresh failed but the last good data is still on screen. "Empty" only after a SUCCESSFUL request returned an
 *  empty collection: a failed request is never "no data". */
export type QueryKind = "loading" | "error" | "empty" | "ready";

export interface QueryLike {
  isPending: boolean;
  isError: boolean;
  data: unknown;
  /** ms epoch of the last successful fetch (TanStack's `dataUpdatedAt`); 0 = never */
  dataUpdatedAt: number;
}

export interface QueryView {
  kind: QueryKind;
  /** a refresh failed and `data` is the last good result */
  stale: boolean;
  /** when the data on screen was fetched; null when there is none */
  asOf: number | null;
}

export function queryView<T>(q: QueryLike, isEmpty: (data: T) => boolean): QueryView {
  const hasData = q.data !== undefined;
  if (!hasData) {
    if (q.isError) return { kind: "error", stale: false, asOf: null };
    if (q.isPending) return { kind: "loading", stale: false, asOf: null };
  }
  const asOf = q.dataUpdatedAt || null;
  const kind: QueryKind = isEmpty(q.data as T) ? "empty" : "ready";
  return { kind, stale: hasData && q.isError, asOf };
}

/** What a module says about its own data in its corner (MVP-2.9.0 N20): «fetched», or «failed» whenever the last
 *  request failed — also when older data is still on screen under the stale notice. */
export function moduleStatus(q: QueryLike): "loading" | "failed" | "fetched" {
  if (q.isError) return "failed";
  return q.data !== undefined ? "fetched" : "loading";
}
