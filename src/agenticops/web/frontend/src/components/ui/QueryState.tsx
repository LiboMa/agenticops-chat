import type { ReactNode } from "react";
import { useLocale } from "@/i18n/LocaleContext";
import { queryView, type QueryLike } from "@/lib/queryState";
import { formatUtcTime } from "@/lib/formatDate";
import { Spinner } from "./Spinner";
import { ErrorBanner } from "./ErrorBanner";
import { EmptyState } from "./EmptyState";

interface QueryStateProps<T> {
  query: QueryLike & { data: T | undefined; error?: unknown };
  isEmpty: (data: T) => boolean;
  emptyText: string;
  onRetry: () => void;
  children: (data: T) => ReactNode;
}

/** One data module's four states (MVP-2.8.0 S1): loading, failed (with retry), empty (only after a successful
 *  empty response), ready — and, when a refresh failed, the last good data under a «refresh failed · data as of»
 *  notice. One module failing never hides another: wrap each module in its own QueryState. */
export function QueryState<T>({ query, isEmpty, emptyText, onRetry, children }: QueryStateProps<T>) {
  const { t } = useLocale();
  const view = queryView<T>(query, isEmpty);
  if (view.kind === "loading") return <Spinner label={t("common.loading")} />;
  if (view.kind === "error") {
    const detail = query.error instanceof Error && query.error.message ? ` · ${query.error.message}` : "";
    return <ErrorBanner message={`${t("common.state.failed")}${detail}`} onRetry={onRetry} actionLabel={t("common.retry")} />;
  }
  return (
    <>
      {view.stale && <StaleNotice asOf={view.asOf} onRetry={onRetry} />}
      {view.kind === "empty" ? <EmptyState message={emptyText} /> : children(query.data as T)}
    </>
  );
}

/** «Refresh failed — showing the last data fetched · as of HH:MM UTC» + fetch again — for a page whose data is not
 *  one wrappable module (it keeps its own layout and shows this above it). */
export function StaleNotice({ asOf, onRetry }: { asOf: number | null; onRetry: () => void }) {
  const { t } = useLocale();
  return (
    <div role="status" className="mb-3 flex flex-wrap items-center justify-between gap-2 rounded-md border border-status-warn/30 bg-status-warn/10 px-3 py-2 text-sm text-status-warn">
      <span>{t("common.state.staleNotice").replace("{time}", formatUtcTime(asOf))}</span>
      <button type="button" onClick={onRetry}
              className="rounded-md border border-status-warn/40 px-2.5 py-1 text-xs font-medium hover:bg-status-warn/10">
        {t("common.state.refetch")}
      </button>
    </div>
  );
}
