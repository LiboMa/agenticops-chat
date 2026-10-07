import { useLayoutEffect, useRef } from "react";
import { Navigate, Outlet, useLocation, useMatch, useNavigate, useOutletContext, useParams } from "react-router-dom";
import { useLocale } from "@/i18n/LocaleContext";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { CaseQueue } from "@/components/cases/CaseQueue";
import IssueDetail from "@/pages/IssueDetail";
import { SPLIT_MEDIA, backTarget } from "@/lib/caseQueue";
import { legacyIssuesViewRedirect } from "@/lib/workitemRoutes";

type PaneContext = { paneRef: React.RefObject<HTMLDivElement>; wide: boolean };

/** Cases (MVP-2.7.0 S4): the queue beside the reading pane at ≥ 1280px (the queue never remounts as you select);
 *  below that, the list and a full-screen case, one at a time. */
export default function Cases() {
  const location = useLocation();
  const wide = useMediaQuery(SPLIT_MEDIA);
  const match = useMatch("/app/issues/:id");
  const paneRef = useRef<HTMLDivElement>(null);
  // Resources and signals left this hub for their own pages: an old ?view= link lands there, no extra history
  const redirect = legacyIssuesViewRedirect(location.search);
  if (redirect) return <Navigate to={redirect} replace />;
  const selectedId = match?.params.id ? Number(match.params.id) : null;

  if (!wide) {
    return selectedId == null ? <CaseQueue selectedId={null} wide={false} /> : <Outlet context={{ paneRef, wide } satisfies PaneContext} />;
  }
  return (
    <div className="grid h-[calc(100vh-var(--topbar-h)-3rem)] grid-cols-[300px_minmax(0,960px)] gap-5 max-[1350px]:grid-cols-[280px_minmax(0,960px)]">
      <CaseQueue selectedId={selectedId} wide />
      <div ref={paneRef} className="min-h-0 overflow-y-auto pr-1">
        <Outlet context={{ paneRef, wide } satisfies PaneContext} />
      </div>
    </div>
  );
}

export function CasePlaceholder() {
  const { t } = useLocale();
  return (
    <div className="flex h-full items-center justify-center rounded-lg border border-dashed border-border text-sm text-muted-foreground">
      {t("cases.selectPrompt")}
    </div>
  );
}

/** The reading pane: one IssueDetail per case (key = id), so nothing local — a dialog, a draft — follows you from
 *  one case to the next; the pane (or the page, full screen) starts at the top unless a hash points into it. */
export function CaseReading() {
  const { id } = useParams<{ id: string }>();
  const { paneRef, wide } = useOutletContext<PaneContext>();
  const location = useLocation();
  const navigate = useNavigate();
  useLayoutEffect(() => {
    if (location.hash) return;
    if (wide) paneRef.current?.scrollTo({ top: 0 });
    else window.scrollTo(0, 0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, wide]);
  if (wide) return <IssueDetail key={id} embedded />;
  const back = backTarget(location.state, location.search);
  return <IssueDetail key={id} back={back.kind === "history" ? { onBack: () => navigate(-1) } : { to: back.to }} />;
}
