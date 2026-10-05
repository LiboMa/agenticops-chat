import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { useAnomaly } from "@/hooks/useAnomaly";
import { useAnomalyRca } from "@/hooks/useAnomalyRca";
import {
  useFixPlans,
  useApproveFixPlan,
  useRejectFixPlan,
  useExecuteFixPlan,
} from "@/hooks/useFixPlans";
import { useUpdateIssueStatus } from "@/hooks/useIssueActions";
import { useIssueExecutions } from "@/hooks/useIssueExecutions";
import { useIssueTimeline } from "@/hooks/useIssueTimeline";
import { useAcceptExecution, useCancelExecution } from "@/hooks/useFixExecutions";
import { useSettings } from "@/hooks/useSettings";
import { usePhaseCards } from "@/hooks/usePhaseCards";
import { useResource } from "@/hooks/useResourceDetail";
import { useLocale } from "@/i18n/LocaleContext";
import { useAuth } from "@/hooks/useAuth";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { ReasonDialog } from "@/components/plans/ReasonDialog";
import { Card, CardBody } from "@/components/ui/Card";
import { SeverityBadge } from "@/components/ui/SeverityBadge";
import { FixPlanStatusBadge } from "@/components/ui/FixPlanStatusBadge";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { PlanView } from "@/components/plans/PlanView";
import { StatusLine, type StatusLineAction } from "@/components/workitem/StatusLine";
import { PhaseCard } from "@/components/workitem/PhaseCard";
import { FactsRail } from "@/components/workitem/FactsRail";
import { ActivityList } from "@/components/workitem/ActivityList";
import { DiagnoseBody, diagnoseSummary } from "@/components/issue/DiagnoseCard";
import { RunBody } from "@/components/issue/RunCard";
import { AcceptBody } from "@/components/issue/AcceptCard";
import { formatFullDate } from "@/lib/formatDate";
import { renderMarkdown } from "@/lib/renderMarkdown";
import { planLabel, shortHash } from "@/lib/plans";
import { fillPlaceholders } from "@/lib/placeholders";
import {
  anchorBadge, approvalBlockedReason, canApprovePlan, executionStatusLabel, factRows, issueFacts, isBlank,
} from "@/lib/issueDetail";
import { issueDetailModel, newestFirst, type Reason } from "@/lib/issueDetailModel";
import { ISSUE_PHASES, type IssuePhaseId, type IssuePrimary } from "@/lib/issuePhases";
import { ISSUE_HASHES, legacyIssueTabHash } from "@/lib/workitemRoutes";
import { toActivity } from "@/lib/activity";
import { apiFetch } from "@/api/client";
import type { FixExecution, HealthIssue, IssueStatus, MergedAlert } from "@/api/types";

/* ================================================================== */
/*  Main component                                                     */
/* ================================================================== */

export default function IssueDetail() {
  const { id } = useParams<{ id: string }>();
  const issueId = Number(id);
  const { t } = useLocale();
  const { isAuthenticated } = useAuth();
  const { confirm, dialog } = useConfirm();
  const location = useLocation();
  const navigate = useNavigate();

  /* -- Data hooks -------------------------------------------------- */
  const anomaly = useAnomaly(issueId);
  const rca = useAnomalyRca(issueId);
  const fixPlans = useFixPlans({ health_issue_id: issueId });
  const executions = useIssueExecutions(issueId);
  const timeline = useIssueTimeline(issueId);
  const settings = useSettings();
  // The anchored resource, so the facts name it rather than the alarm's raw resource_id
  const anchorRes = useResource(anomaly.data?.resource_ref ?? 0);
  const updateStatusMut = useUpdateIssueStatus();
  const cancelExecMut = useCancelExecution();
  const approveMut = useApproveFixPlan();
  const rejectMut = useRejectFixPlan();
  const executeMut = useExecuteFixPlan();

  // The issue poll can land on fix_executed after the runs poll has stopped; the banner needs the verdict the
  // backend wrote to the run in the same transaction, so a status move refetches the runs (and the plan, whose
  // badge moves with them). Keyed by issue id: following a link to another issue reuses this page and is not a move.
  const qc = useQueryClient();
  const issueStatus = anomaly.data?.status;
  const lastStatus = useRef({ id: issueId, status: issueStatus });
  useEffect(() => {
    const prev = lastStatus.current;
    if (prev.id === issueId && prev.status !== undefined && issueStatus !== undefined && prev.status !== issueStatus) {
      qc.invalidateQueries({ queryKey: ["issue-executions", issueId] });
      qc.invalidateQueries({ queryKey: ["fix-plans"] });
    }
    lastStatus.current = { id: issueId, status: issueStatus };
  }, [issueStatus, issueId, qc]);

  // Inputs not loaded stay undefined — still loading, or the fetch failed, never "none": the RCA → list mode (no
  // flash of "rerun RCA"; null is a stored "no RCA"), the threshold → no gate yet, the runs and the timeline (where
  // an approval's auto-run shows before it has a row) → not known. The status line says which instead of inventing
  // a state. A failed refetch keeps the data already loaded.
  const model = anomaly.data ? issueDetailModel({
    issue: anomaly.data,
    rca: rca.data,
    rcaFailed: !!rca.error,
    threshold: settings.data?.rca_min_confidence_for_autofix,
    plans: fixPlans.data,
    executions: executions.data,
    runsFailed: !!executions.error,
    timeline: timeline.data,
    timelineFailed: !!timeline.error,
    executorTimeout: settings.data?.executor_total_timeout,
    now: Date.now(),
  }) : null;

  /* -- URL: an old ?tab= maps once onto its hash; the hash opens a card -- */
  useEffect(() => {
    const q = new URLSearchParams(location.search);
    const tab = q.get("tab");
    if (tab === null) return;
    q.delete("tab");
    const hash = legacyIssueTabHash(tab);
    const rest = q.toString();
    navigate({ search: rest ? `?${rest}` : "", hash: hash ? `#${hash}` : location.hash }, { replace: true });
  }, [location.search, location.hash, navigate]);

  // Every card is controlled: re-seeded whenever the current phase moves (a poll landing on fix_executed opens ④)
  const cards = usePhaseCards<IssuePhaseId>({
    ids: ISSUE_PHASES, hashes: ISSUE_HASHES, phases: model?.phase.phases ?? null,
    seedKey: model ? `${issueId}:${model.phase.current ?? "-"}` : null,
  });
  const [showMerged, setShowMerged] = useState(false);

  /* -- Local state ------------------------------------------------- */
  const [rcaLoading, setRcaLoading] = useState(false);
  const [fixPlanLoading, setFixPlanLoading] = useState(false);
  const [actionInfo, setActionInfo] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [approvalDialog, setApprovalDialog] = useState<"approve" | "reject" | null>(null);
  const [claimedName, setClaimedName] = useState("");
  const [acceptDecision, setAcceptDecision] = useState<"accepted" | "rejected" | null>(null);

  /* -- Handlers ---------------------------------------------------- */
  const triggerRca = async () => {
    setRcaLoading(true);
    setActionInfo(null);
    setActionError(null);
    try {
      await apiFetch<unknown>(`/issues/${issueId}/rca`, { method: "POST" });
      setActionInfo(t("issues.rcaTriggered"));
      setTimeout(() => rca.refetch(), 10000);
    } catch (e: any) {
      setActionError(`${t("issues.rcaFailed")}: ${e.message}`);
    } finally {
      setRcaLoading(false);
    }
  };

  const triggerFixPlan = async () => {
    setFixPlanLoading(true);
    setActionInfo(null);
    setActionError(null);
    try {
      await apiFetch<unknown>(`/issues/${issueId}/generate-fix-plan`, { method: "POST" });
      setActionInfo(t("issues.fixPlanTriggered"));
      setTimeout(() => fixPlans.refetch(), 10000);
    } catch (e: any) {
      setActionError(`${t("issues.fixPlanFailed")}: ${e.message}`);
    } finally {
      setFixPlanLoading(false);
    }
  };

  const updateStatus = (status: IssueStatus) => {
    setActionError(null);
    updateStatusMut.mutate(
      { id: issueId, status },
      {
        onSuccess: () => {
          anomaly.refetch();
          executions.refetch();
          timeline.refetch();
        },
        onError: (err) => setActionError(err.message),
      },
    );
  };

  // a confirmation in the page's language, then the action
  const ask = async (message: string, confirmText: string, run: () => void, variant?: "destructive") => {
    if (await confirm(message, { confirmText, cancelText: t("common.cancel"), variant })) run();
  };

  /* -- Loading / error states -------------------------------------- */
  if (anomaly.isLoading) return <Spinner label={t("common.loading")} />;
  if (anomaly.error)
    return (
      <ErrorBanner
        message={anomaly.error.message}
        onRetry={() => anomaly.refetch()}
        actionLabel={t("common.retry")}
      />
    );

  const a = anomaly.data!;
  const m = model!;
  const plan = m.plan;
  const runs = newestFirst(executions.data);
  const closed = a.status === "resolved" || a.status === "dismissed";
  const canApprove = !!plan && canApprovePlan(plan, a.status);
  const blocked = plan ? approvalBlockedReason(plan, a.status) : null;
  // the latest run's sentence is the status line's: ③ / ④ do not repeat that exact text (P3)
  const quietErrorRunId = m.quietRunError ? m.latestRun?.id ?? null : null;
  const quietReasonRunId = m.quietAcceptReason ? m.latestRun?.id ?? null : null;
  // a failed fetch the status line depends on is said where the reader is — under it — with a retry; an action
  // error wins. The cards show what is already loaded; only with nothing loaded do they say the fetch failed.
  const fetchError = actionError ? null
    : executions.error ? { message: executions.error.message, retry: () => executions.refetch() }
    : rca.error && rca.data === undefined ? { message: rca.error.message, retry: () => rca.refetch() }
    : timeline.error && timeline.data === undefined ? { message: timeline.error.message, retry: () => timeline.refetch() }
    : null;
  const runsFetchError = executions.data === undefined ? executions.error : null;
  const rcaFetchError = rca.data === undefined ? rca.error : null;

  const openApproval = (kind: "approve" | "reject") => {
    (kind === "approve" ? approveMut : rejectMut).reset();
    setApprovalDialog(kind);
  };
  const openAccept = (decision: "accepted" | "rejected") => setAcceptDecision(decision);

  /* -- Status line ------------------------------------------------- */
  const fill = (r: Reason) => ("text" in r ? r.text : fillPlaceholders(t(r.key), r.params));
  const reason = closed
    ? (a.status === "resolved" && a.resolved_at ? t("workitem.reason.resolvedAt").replace("{at}", formatFullDate(a.resolved_at)) : null)
    : m.reason && fill(m.reason);

  // queue the approved plan again; while its auto-run looks under way (⋯ only) the confirm says so — the server
  // refuses a second run (409) until that one ends or goes stale
  const retry = (confirmKey: string) => plan
    ? () => ask(t(confirmKey), t("workitem.primary.retryExecution"),
                () => executeMut.mutate(plan.id, { onError: (err) => setActionError(err.message) }))
    : null;
  const primaryRun: Record<NonNullable<IssuePrimary>, (() => void) | null> = {
    reviewRca: () => { cards.openCard("diagnose"); cards.scrollTo("verdict"); },
    rerunRca: triggerRca,
    generatePlan: triggerFixPlan,
    approveAndRun: canApprove ? () => openApproval("approve") : null,
    retryExecution: retry("workitem.confirm.retry"),
    acceptResult: m.pendingRun ? () => openAccept("accepted") : null,
    markResolved: () => ask(t("workitem.confirm.resolve"), t("workitem.primary.markResolved"), () => updateStatus("resolved")),
  };
  const primaryBusy: Partial<Record<NonNullable<IssuePrimary>, boolean>> = {
    rerunRca: rcaLoading, generatePlan: fixPlanLoading, approveAndRun: approveMut.isPending,
    retryExecution: executeMut.isPending, markResolved: updateStatusMut.isPending,
  };
  const p = m.phase.primary;
  const primary: StatusLineAction | null = p && m.primaryKey && primaryRun[p]
    ? { key: p, label: t(m.primaryKey), run: primaryRun[p]!, disabled: primaryBusy[p] ?? false }
    : null;

  const latestRun = m.latestRun;
  const menu: StatusLineAction[] = m.menu.map((item) => {
    const label = t(`workitem.menu.${item}`);
    switch (item) {
      case "runRca": return { key: item, label, run: triggerRca, disabled: rcaLoading };
      case "skipReviewGeneratePlan": return { key: item, label, run: triggerFixPlan, disabled: fixPlanLoading };
      case "markResolved":
        return { key: item, label, disabled: updateStatusMut.isPending,
                 run: () => ask(t("workitem.confirm.resolve"), t("workitem.primary.markResolved"), () => updateStatus("resolved")) };
      case "dismiss":
        return { key: item, label, variant: "destructive", disabled: updateStatusMut.isPending,
                 run: () => ask(t("workitem.confirm.dismiss"), label, () => updateStatus("dismissed"), "destructive") };
      case "reopen":
        return { key: item, label, disabled: updateStatusMut.isPending,
                 run: () => ask(t("workitem.confirm.reopen"), label, () => updateStatus("open")) };
      case "cancelRun":
        return { key: item, label, variant: "destructive", disabled: cancelExecMut.isPending,
                 run: () => latestRun && ask(t("workitem.confirm.cancelRun"), label,
                   () => cancelExecMut.mutate(latestRun.id, { onError: (err) => setActionError(err.message) }), "destructive") };
      case "retryExecution":
        return { key: item, label, disabled: executeMut.isPending, run: () => retry("workitem.confirm.retryWhileRunning")?.() };
    }
  });

  /* -- Phase cards ------------------------------------------------- */
  const state = (id: IssuePhaseId) => m.phase.phases.find((x) => x.id === id)!.state;
  const runSummary = latestRun && [t("issues.executionN").replace("{n}", String(latestRun.id)),
    latestRun.verification_status ? t(`verification.${latestRun.verification_status}`) : executionStatusLabel(latestRun.status, t)]
    .join(" · ");
  const badge = anchorBadge(a, anchorRes.data?.resource_name);

  /* -- Render ------------------------------------------------------ */
  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
      <div className="space-y-4 min-w-0">
        <StatusLine
          refLabel={`I#${a.id}`}
          title={a.title}
          badges={<SeverityBadge severity={a.severity} />}
          statusLabel={closed ? t(`issues.status.${a.status}`) : t(m.statusKey)}
          tone={m.tone}
          reason={reason}
          waiting={m.waitingKey && t(m.waitingKey)}
          primary={primary}
          menu={menu}
          error={actionError ?? fetchError?.message ?? null}
          onDismissError={() => (actionError ? setActionError(null) : fetchError?.retry())}
          errorActionLabel={actionError ? undefined : t("common.retry")}
          backTo="/app/issues"
          backLabel={t("nav.issues")}
        />
        {actionInfo && (
          <div className="flex items-start gap-3 p-3 rounded-lg bg-primary/10 border border-primary/20 text-sm text-primary">
            <span className="flex-1">{actionInfo}</span>
            <button onClick={() => setActionInfo(null)} aria-label={t("common.close")} title={t("common.close")}
                    className="shrink-0 leading-none hover:opacity-70">×</button>
          </div>
        )}

        {cards.openable.length > 0 && (
          <div className="flex justify-end">
            <button onClick={cards.toggleAll} className="text-xs text-primary hover:underline">
              {t(cards.allOpen ? "workitem.collapseAll" : "workitem.expandAll")}
            </button>
          </div>
        )}

        <PhaseCard id="diagnose" index={1} title={t("workitem.phase.diagnose")} state={state("diagnose")}
                   summary={diagnoseSummary(rca.data, t)}
                   open={cards.isOpen("diagnose")} onToggle={(o) => cards.toggleCard("diagnose", o)}>
          <DiagnoseBody issueId={a.id} rca={rca.data} loading={rca.isLoading} error={rcaFetchError} onRetryFetch={() => rca.refetch()}
                        threshold={settings.data?.rca_min_confidence_for_autofix} timelineEvents={timeline.data}
                        closed={closed} onVerdictDone={() => { anomaly.refetch(); rca.refetch(); }} t={t} />
        </PhaseCard>

        <PhaseCard id="plan" index={2} title={t("workitem.phase.plan")} state={state("plan")}
                   summary={plan && `${planLabel(plan, t)} · ${plan.title}`} futureHint={t("workitem.future.issue.plan")}
                   open={cards.isOpen("plan")} onToggle={(o) => cards.toggleCard("plan", o)}>
          {fixPlans.isLoading ? <Spinner label={t("common.loading")} /> : plan ? (
            <div className="space-y-4">
              <PlanView plan={plan} t={t} />
              {m.otherPlans.length > 0 && (
                <details className="border-t border-border pt-3">
                  <summary className="cursor-pointer text-sm font-semibold text-foreground">
                    {t("workitem.otherPlans").replace("{n}", String(m.otherPlans.length))}
                  </summary>
                  <ul className="mt-2 space-y-2">
                    {m.otherPlans.map((op) => (
                      <li key={op.id} className="flex items-center justify-between gap-3 text-sm">
                        <span className="min-w-0">
                          <span className="text-xs text-muted-foreground mr-2">{planLabel(op, t)}</span>
                          <span className="text-foreground">{op.title}</span>
                        </span>
                        <FixPlanStatusBadge status={op.status} />
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">{t("workitem.future.issue.plan")}</p>
          )}
        </PhaseCard>

        <PhaseCard id="run" index={3} title={t("workitem.phase.run")} state={state("run")} summary={runSummary}
                   futureHint={t("workitem.future.issue.run")}
                   open={cards.isOpen("run")} onToggle={(o) => cards.toggleCard("run", o)}>
          <RunBody plan={plan} issueStatus={a.status} runs={runs} loading={executions.isLoading}
                   error={runsFetchError} onRetryFetch={() => executions.refetch()} quietRunId={quietErrorRunId}
                   autoRunSince={m.autoRun?.startedAt ?? null}
                   onApprove={() => openApproval("approve")} onReject={() => openApproval("reject")}
                   approving={approveMut.isPending} rejecting={rejectMut.isPending} t={t} />
        </PhaseCard>

        <PhaseCard id="accept" index={4} title={t("workitem.phase.accept")} state={state("accept")}
                   summary={latestRun?.verification_status ? t(`verification.${latestRun.verification_status}`) : null}
                   futureHint={t("workitem.future.issue.accept")}
                   open={cards.isOpen("accept")} onToggle={(o) => cards.toggleCard("accept", o)}>
          <AcceptBody runs={runs} loading={executions.isLoading} error={runsFetchError} onRetryFetch={() => executions.refetch()}
                      pendingRun={m.pendingRun} quietRunId={quietReasonRunId}
                      onAccept={() => openAccept("accepted")} onReject={() => openAccept("rejected")} t={t} />
        </PhaseCard>
      </div>

      {/* -- Right rail: key facts + activity -- */}
      <aside className="space-y-4 min-w-0">
        <FactsRail
          title={t("workitem.facts")}
          rows={factRows(a, { name: anchorRes.data?.resource_name ?? null, type: anchorRes.data?.resource_type ?? null })}
          t={t}
          extra={
            <div className="space-y-2 border-t border-border pt-3 text-sm">
              {badge && badge.kind !== "resource" && (
                <span className="inline-block text-xs px-2 py-0.5 rounded bg-amber-500/10 text-amber-600 dark:text-amber-400">
                  {t(`anchor.${badge.kind}`)}
                  {badge.kind === "ambiguous" && ` (${t("anchor.candidatesN").replace("{n}", String(badge.candidates))})`}
                </span>
              )}
              {(a.merged_alerts ?? []).length > 0 && (
                <button onClick={() => setShowMerged(!showMerged)} aria-expanded={showMerged}
                        className="block text-left text-primary hover:underline">
                  {t("workitem.mergedSignals").replace("{n}", String(a.merged_alerts.length))}
                </button>
              )}
              <Link to="/app/signals" className="block text-primary hover:underline">{t("workitem.rawSignals")}</Link>
              <IssueDescription issue={a} t={t} />
            </div>
          }
        />
        {showMerged && (a.merged_alerts ?? []).length > 0 && (
          <MergedAlertsSection alerts={a.merged_alerts} occurrenceCount={a.occurrence_count} />
        )}

        <section id="activity" className="scroll-mt-4">
          <Card>
            <CardBody className="space-y-3">
              <button onClick={() => cards.setActivityOpen(!cards.activityOpen)} aria-expanded={cards.activityOpen}
                      className="flex w-full items-center justify-between text-left">
                <h3 className="text-sm font-semibold text-foreground">{t("workitem.activity")}</h3>
                <svg className={`h-4 w-4 text-muted-foreground transition-transform ${cards.activityOpen ? "rotate-90" : ""}`}
                     fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden>
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                </svg>
              </button>
              {cards.activityOpen && (timeline.isLoading
                ? <Spinner label={t("common.loading")} />
                : <ActivityList entries={toActivity(timeline.data, { hideText: m.reason && "text" in m.reason ? m.reason.text : null })}
                                t={t} emptyKey="activity.empty" />)}
            </CardBody>
          </Card>
        </section>
      </aside>

      {plan && approvalDialog && (canApprove || blocked) && (
        <ReasonDialog
          title={approvalDialog === "approve"
            ? t("workitem.approveTitle").replace("{label}", planLabel(plan, t))
            : `${t("plans.rejectTitle")} ${planLabel(plan, t)}`}
          description={`${plan.title} · ${t("plans.hash")} ${shortHash(plan.content_hash)}`}
          confirmText={approvalDialog === "approve" ? t("workitem.primary.approveAndRun") : t("issues.reject")}
          variant={approvalDialog === "reject" ? "destructive" : "default"}
          required={approvalDialog === "reject"}
          busy={approveMut.isPending || rejectMut.isPending}
          error={(approvalDialog === "approve" ? approveMut.error : rejectMut.error)?.message ?? null}
          onConfirm={(r) => {
            const done = { onSuccess: () => setApprovalDialog(null) };
            if (approvalDialog === "approve") {
              const name = claimedName.trim();
              approveMut.mutate({ id: plan.id, content_hash: plan.content_hash ?? "", reason: r || undefined,
                                  approved_by: !isAuthenticated && name ? name : undefined }, done);
            } else rejectMut.mutate({ id: plan.id, reason: r }, done);
          }}
          onClose={() => setApprovalDialog(null)}
        >
          {/* unauthenticated: the legacy claimed name, audited by the backend but never trusted */}
          {approvalDialog === "approve" && !isAuthenticated && (
            <input type="text" value={claimedName} onChange={(e) => setClaimedName(e.target.value)} maxLength={100}
              placeholder={t("issues.approverPlaceholder")}
              className="w-full mb-3 border border-border bg-background text-foreground rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50" />
          )}
        </ReasonDialog>
      )}
      {m.pendingRun && acceptDecision && (
        <AcceptanceDialog execution={m.pendingRun} decision={acceptDecision} onClose={() => setAcceptDecision(null)} />
      )}
      {dialog}
    </div>
  );
}

/* ================================================================== */
/*  Acceptance                                                         */
/* ================================================================== */

/** Accept / reject a run pending acceptance; both need a reason, and the identity is the session's. */
function AcceptanceDialog({ execution, decision, onClose }: {
  execution: FixExecution;
  decision: "accepted" | "rejected";
  onClose: () => void;
}) {
  const { t } = useLocale();
  const accept = useAcceptExecution();
  return (
    <ReasonDialog
      title={`${t(decision === "accepted" ? "verification.acceptTitle" : "verification.rejectTitle")} #${execution.id}`}
      description={t(decision === "accepted" ? "verification.acceptHint" : "verification.rejectHint")}
      confirmText={t(decision === "accepted" ? "workitem.primary.acceptResult" : "verification.reject")}
      variant={decision === "rejected" ? "destructive" : "default"}
      required
      busy={accept.isPending}
      error={accept.error?.message ?? null}
      onConfirm={(reason) => accept.mutate({ id: execution.id, decision, reason }, { onSuccess: onClose })}
      onClose={onClose}
    />
  );
}

/* ================================================================== */
/*  Description (the alarm's own text) + metric                        */
/* ================================================================== */

function IssueDescription({ issue: a, t }: { issue: HealthIssue; t: (key: string) => string }) {
  const f = issueFacts(a);
  if (isBlank(a.description) && !f.metricName) return null;
  return (
    <details>
      <summary className="cursor-pointer text-muted-foreground">{t("workitem.description")}</summary>
      {!isBlank(a.description) && (
        <div className="mt-2 text-xs text-muted-foreground report-content break-words"
             dangerouslySetInnerHTML={{ __html: renderMarkdown(a.description) }} />
      )}
      {f.metricName && (
        <dl className="mt-2 grid grid-cols-[5rem_1fr] gap-1 text-xs">
          <dt className="text-muted-foreground">{t("issues.metric")}</dt><dd className="text-foreground break-all">{f.metricName}</dd>
          {f.expected != null && <><dt className="text-muted-foreground">{t("issues.expected")}</dt><dd className="text-foreground">{String(f.expected)}</dd></>}
          {f.actual != null && <><dt className="text-muted-foreground">{t("issues.actual")}</dt><dd className="text-foreground">{String(f.actual)}</dd></>}
        </dl>
      )}
    </details>
  );
}

/* ================================================================== */
/*  Merged Alerts                                                      */
/* ================================================================== */

const SEV_CHIP: Record<string, string> = {
  critical: "bg-red-500/20 text-red-400",
  high: "bg-orange-500/20 text-orange-400",
  medium: "bg-yellow-500/20 text-yellow-400",
  low: "bg-secondary text-muted-foreground",
};

function MergedAlertsSection({
  alerts,
  occurrenceCount,
}: {
  alerts: MergedAlert[];
  occurrenceCount?: number;
}) {
  const { t } = useLocale();
  const [expanded, setExpanded] = useState(false);
  const displayed = expanded ? alerts : alerts.slice(-5);

  return (
    <Card>
      <CardBody>
        <button
          onClick={() => setExpanded(!expanded)}
          className="flex items-center gap-2 w-full text-left"
        >
          <h3 className="text-sm font-medium text-muted-foreground uppercase tracking-wider">
            {t("issues.mergedAlerts")} ({alerts.length})
          </h3>
          {occurrenceCount && occurrenceCount > 1 && (
            <span className="text-xs bg-primary/10 text-primary px-2 py-0.5 rounded-full">
              {occurrenceCount} {t("issues.occurrences")}
            </span>
          )}
          <span className="ml-auto text-muted-foreground text-xs">
            {expanded ? t("issues.collapse") : t("issues.expand")}
          </span>
        </button>
        <div className="mt-3 space-y-2">
          {displayed.map((alert, i) => (
            <div key={i} className="flex flex-wrap items-center gap-2 text-sm py-1.5 px-2 rounded bg-secondary">
              <span className="text-xs text-muted-foreground whitespace-nowrap font-mono">
                {new Date(alert.timestamp).toLocaleString()}
              </span>
              <span className="text-xs bg-muted text-muted-foreground px-1.5 py-0.5 rounded">
                {alert.source}
              </span>
              <span className={`text-xs px-1.5 py-0.5 rounded ${SEV_CHIP[alert.severity] || SEV_CHIP.low}`}>
                {alert.severity}
              </span>
              <span className="text-foreground flex-1 min-w-0 break-words">{alert.title}</span>
            </div>
          ))}
          {!expanded && alerts.length > 5 && (
            <div className="text-xs text-muted-foreground text-center">
              {t("issues.showingLast")} {alerts.length}
            </div>
          )}
        </div>
      </CardBody>
    </Card>
  );
}
