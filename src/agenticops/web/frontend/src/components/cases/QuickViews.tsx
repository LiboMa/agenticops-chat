import { useNavigate, useSearchParams } from "react-router-dom";
import { useLocale } from "@/i18n/LocaleContext";
import { useReadOnly } from "@/hooks/useBootstrap";
import { useIssueViewCounts } from "@/hooks/useIssueViewCounts";
import { useNavCounts } from "@/hooks/useNavCounts";
import { QUICK_VIEWS, defaultView, queueParams, type QuickView } from "@/lib/caseQueue";
import { topBarCount } from "@/lib/navCounts";
import type { IssueScope } from "@/lib/issueScope";

/** The Issues page's four views (MVP-2.8.0): «在等我» (its number is the sidebar's and the top bar's — one request),
 *  then the issue list's all / failed / waiting long (counted by the server). A view switch always lands on the list
 *  (/app/issues), keeps the other filters and drops a selected «在等我» item; the default view stays out of the URL. */
export function QuickViews({ view, scope, accountId }: { view: QuickView; scope?: IssueScope; accountId?: number }) {
  const { t } = useLocale();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const readOnly = useReadOnly();
  const viewCounts = useIssueViewCounts(scope, accountId);
  const nav = useNavCounts();
  const count = (v: QuickView): string => {
    if (v === "waiting") {
      if (readOnly) return "";
      const n = topBarCount({ status: nav.status, data: nav.data });
      return n !== null ? String(n) : nav.isLoading ? "…" : "—";
    }
    return viewCounts.data ? String(viewCounts.data[v]) : viewCounts.isError ? "—" : "…";
  };
  const select = (v: QuickView) => {
    const next = queueParams(params, "view", v, { view: defaultView(readOnly) }).toString();
    navigate({ pathname: "/app/issues", search: next ? `?${next}` : "" }, { replace: true });
  };
  return (
    <>
      <div role="group" aria-label={t("cases.views")} className="grid grid-cols-2 gap-1">
        {QUICK_VIEWS.map((v) => (
          <button key={v} type="button" aria-pressed={view === v} onClick={() => select(v)}
                  className={`flex items-center justify-between rounded-md border px-2 py-1 text-xs ${view === v
                    ? "border-primary/50 bg-selected font-semibold text-primary" : "border-border text-muted-foreground hover:text-foreground"}`}>
            <span>{t(`cases.view.${v}`)}</span>
            <span className="tabular-nums">{count(v)}</span>
          </button>
        ))}
      </div>
      {/* the counts' own failed state (four data states): never «…» forever (S2 review); the list keeps working */}
      {viewCounts.isError && !viewCounts.data && (
        <p role="alert" className="text-xs text-status-danger">
          {t("cases.viewCountFailed")}
          <button type="button" onClick={() => void viewCounts.refetch()} className="ml-2 text-primary hover:underline">
            {t("common.retry")}
          </button>
        </p>
      )}
    </>
  );
}
