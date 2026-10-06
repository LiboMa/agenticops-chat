import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useChange, useChangeAction, type ChangeActionArgs } from "@/hooks/useChanges";
import { useChangeTimeline } from "@/hooks/useChangeTimeline";
import { useSettings } from "@/hooks/useSettings";
import { useAccounts } from "@/hooks/useAccounts";
import { usePhaseCards } from "@/hooks/usePhaseCards";
import { useLocale } from "@/i18n/LocaleContext";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { ApiError } from "@/api/client";
import { Card, CardBody } from "@/components/ui/Card";
import { RiskLevelBadge } from "@/components/ui/RiskLevelBadge";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { ReasonDialog } from "@/components/plans/ReasonDialog";
import { NewChangeDialog } from "@/components/plans/NewChangeDialog";
import { PlanView } from "@/components/plans/PlanView";
import { StatusLine, type StatusLineAction } from "@/components/workitem/StatusLine";
import { PhaseCard } from "@/components/workitem/PhaseCard";
import { FactsRail } from "@/components/workitem/FactsRail";
import { ActivityList } from "@/components/workitem/ActivityList";
import { RequestBody } from "@/components/change/RequestCard";
import { ReviewBody } from "@/components/change/ReviewCard";
import { ChangeRunBody, ClosedRecord } from "@/components/change/RunCard";
import { ChangeAcceptBody } from "@/components/change/AcceptCard";
import { externalRefLink, requestSummary, reviewSummary, runSummary, toPipelineEvents } from "@/lib/changeDetail";
import { changeDetailModel } from "@/lib/changeDetailModel";
import { CHANGE_PHASES, type ChangePhaseId, type ChangePrimary } from "@/lib/changePhases";
import { CHANGE_HASHES } from "@/lib/workitemRoutes";
import { toActivity } from "@/lib/activity";
import { isBlank, type FactRow } from "@/lib/issueDetail";
import { planCounts, planLabel, shortHash } from "@/lib/plans";
import type { Account, ChangeRequestDetail } from "@/api/types";

// The dialog-driven actions; `useChanges` exports the discriminated `ChangeActionArgs`, not a `ChangeAction` alias,
// so `action` is kept to this subset and branched on below to build a well-typed mutate() argument.
type PendingAction = "approve" | "reject" | "cancel" | "resolve-review";
type Pending = {
  action: PendingAction;
  title: string;
  description?: string;
  confirmText: string;
  variant?: "default" | "destructive";
  extra?: { outcome: "completed" | "failed" };
  // approve: the hash the dialog shows is the hash it sends, even if a poll replaces the plan while it is open
  contentHash?: string;
};

/** The right rail's key facts, blank rows dropped. */
function changeFactRows(cr: ChangeRequestDetail, acct: Account | undefined, t: (k: string) => string): FactRow[] {
  const rows: FactRow[] = [];
  const res = cr.target_resources;
  const targets = res.length > 0 ? res.map((r) => r.resource_id) : cr.target_hints;
  if (targets.length > 0) {
    rows.push({ labelKey: "changes.targets", kind: "mono",
                value: targets.length > 1 ? `${targets[0]} +${targets.length - 1}` : targets[0],
                href: res[0]?.db_id != null ? `/app/resources/${res[0].db_id}` : undefined });
  }
  rows.push({ labelKey: "facts.account",
              value: cr.account_id == null ? t("plans.form.accountAny") : acct ? `${acct.name} (${acct.provider})` : `#${cr.account_id}` });
  if (cr.risk_level) rows.push({ labelKey: "plans.risk", value: cr.risk_level });
  rows.push({ labelKey: "plans.requestedBy", value: cr.requested_by, kind: "mono" });
  const ext = externalRefLink(cr.external_ref);
  if (ext) rows.push({ labelKey: "changes.externalRef", value: ext.label, kind: "mono", href: ext.url ?? undefined, external: true });
  const created = cr.requested_at ?? cr.created_at;
  if (created) rows.push({ labelKey: "issues.created", value: created, kind: "date" });
  if (!isBlank(cr.trace_id)) rows.push({ labelKey: "facts.trace", value: cr.trace_id!, kind: "mono", copy: true });
  return rows;
}

export default function ChangeDetail() {
  const { id } = useParams<{ id: string }>();
  // key={id} resets every local piece of state when the route moves to another change (e.g. copy-as-new).
  return <ChangeDetailView key={id} crId={Number(id)} />;
}

function ChangeDetailView({ crId }: { crId: number }) {
  const { t } = useLocale();
  const settings = useSettings();
  const navigate = useNavigate();
  const accounts = useAccounts();
  const { confirm, dialog } = useConfirm();
  const act = useChangeAction();
  const [pending, setPending] = useState<Pending | null>(null);
  const [clarify, setClarify] = useState("");
  const [copy, setCopy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const changesOn = settings.data?.change_management_enabled === true;
  const valid = Number.isInteger(crId) && crId > 0;
  // 0 keeps both queries disabled, so a disabled flag or a bad id never fetches (the API would 404).
  const qId = changesOn && valid ? crId : 0;
  const q = useChange(qId);
  const tl = useChangeTimeline(qId, q.data?.status);
  const model = q.data ? changeDetailModel(q.data) : null;

  /* -- URL: the hash opens a card (or the activity) and scrolls to it -- */
  // Every card is controlled: re-seeded whenever the phase or its sub-state moves (a poll landing on needs_review
  // opens ⑤; needs_clarification re-opens ② for its answer box)
  const cards = usePhaseCards<ChangePhaseId>({
    ids: CHANGE_PHASES, hashes: CHANGE_HASHES, phases: model?.phase.phases ?? null,
    seedKey: model ? `${model.phase.current}:${model.phase.sub}` : null,
  });

  const backLink = (
    <Link to="/app/plans?tab=changes" className="text-sm text-muted-foreground hover:text-foreground">
      ← {t("nav.plans")}
    </Link>
  );
  const notFoundNotice = (
    <div className="space-y-4">
      {backLink}
      <p className="text-sm text-muted-foreground">{t("changes.notFound")}</p>
    </div>
  );

  if (settings.isLoading) return <Spinner label={t("common.loading")} />;
  if (!changesOn) return <p className="text-sm text-muted-foreground">{t("changes.disabled")}</p>;
  if (!valid || (q.error instanceof ApiError && q.error.status === 404)) return notFoundNotice;
  if (q.isLoading) return <Spinner label={t("common.loading")} />;
  if (q.error)
    return <ErrorBanner message={q.error.message} onRetry={() => q.refetch()} actionLabel={t("common.retry")} />;
  if (!q.data || !model) return notFoundNotice;

  const cr = q.data;
  const m = model;
  // The plan an approve acts on (activeChangePlan, the backend's active_plan_for), so the dialog shows and sends its
  // content_hash
  const plan = m.plan;
  const acct = cr.account_id != null ? accounts.data?.find((a) => a.id === cr.account_id) : undefined;
  // The graph's impact count only feeds the policy when enforced; until then the review card labels it
  const impactNote = settings.data?.policy_graph_impact_enforce ? undefined : t("changes.impactReference");

  /* -- Handlers ---------------------------------------------------- */
  const runDirect = (args: ChangeActionArgs) => {
    setMsg(null);
    act.mutate(args, { onError: (e) => setMsg((e as Error).message) });
  };
  const sendClarify = () => {
    setMsg(null);
    act.mutate(
      { id: cr.id, action: "clarify", body: { message: clarify.trim() } },
      { onSuccess: () => setClarify(""), onError: (e) => setMsg((e as Error).message) },
    );
  };
  const openDialog = (next: Pending) => {
    act.reset();
    setPending(next);
  };
  const onDialogConfirm = (reason: string) => {
    if (!pending) return;
    const args: ChangeActionArgs =
      pending.action === "resolve-review"
        ? { id: cr.id, action: "resolve-review", body: { outcome: pending.extra?.outcome ?? "completed", reason } }
        : pending.action === "approve"
          ? { id: cr.id, action: "approve", body: { reason, content_hash: pending.contentHash ?? "" } }
          : { id: cr.id, action: pending.action, body: { reason } };
    act.mutate(args, { onSuccess: () => setPending(null) });
  };
  const onExecute = async () => {
    if (await confirm(t("plans.executeConfirm"), { confirmText: t("changes.retryExecution"), cancelText: t("common.cancel") })) {
      runDirect({ id: cr.id, action: "execute" });
    }
  };
  const openApprove = () =>
    openDialog({
      action: "approve",
      title: `${t("changes.approveAndRun")} ${plan ? planLabel(plan, t) : `C#${cr.id}`}`,
      description: plan
        ? `${t("changes.approveRunsNote")} ${t("plans.hash")} ${shortHash(plan.content_hash)}`
        : t("changes.approveRunsNote"),
      confirmText: t("changes.approveAndRun"),
      contentHash: plan?.content_hash ?? "",
    });
  const openReject = () =>
    openDialog({
      action: "reject",
      title: `${t("plans.rejectTitle")} ${plan ? planLabel(plan, t) : `C#${cr.id}`}`,
      confirmText: t("issues.reject"),
      variant: "destructive",
    });
  const openCancel = () =>
    openDialog({
      action: "cancel",
      title: `${t("changes.cancelChange")} C#${cr.id}`,
      confirmText: t("common.confirm"),
      variant: "destructive",
    });
  const openAccept = (outcome: "completed" | "failed") =>
    openDialog({
      action: "resolve-review",
      title: `${t(outcome === "completed" ? "changes.markCompleted" : "changes.markFailed")} C#${cr.id}`,
      confirmText: t(outcome === "completed" ? "changes.markCompleted" : "changes.markFailed"),
      variant: outcome === "failed" ? "destructive" : undefined,
      extra: { outcome },
    });

  /* -- Status line ------------------------------------------------- */
  // The primary button: the same handlers as the cards' outlined buttons, so the two never disagree
  const primaryRun: Record<NonNullable<ChangePrimary>, () => void> = {
    startReview: () => runDirect({ id: cr.id, action: "review" }),
    answerReviewer: () => { cards.openCard("review"); cards.scrollTo("change-clarify", true); },
    approveAndRun: openApprove,
    retryExecution: onExecute,
    markCompleted: () => openAccept("completed"),
    copyAsNew: () => setCopy(true),
  };
  const p = m.phase.primary;
  const primary: StatusLineAction | null = p && m.primaryKey
    ? { key: p, label: t(m.primaryKey), run: primaryRun[p], disabled: act.isPending || (p === "copyAsNew" && accounts.isLoading) }
    : null;
  const menu: StatusLineAction[] = m.menu.map((item) => {
    switch (item) {
      case "restartReview":
        return { key: item, label: t("changes.restartReview"), title: t("changes.restartReviewHint"), disabled: act.isPending,
                 run: () => runDirect({ id: cr.id, action: "review" }) };
      case "reject": return { key: item, label: t("issues.reject"), variant: "destructive", disabled: act.isPending, run: openReject };
      case "cancel": return { key: item, label: t("changes.cancelChange"), variant: "destructive", disabled: act.isPending, run: openCancel };
      case "copyAsNew": return { key: item, label: t("changes.copyAsNew"), disabled: accounts.isLoading, run: () => setCopy(true) };
    }
  });
  // A direct action's message, else a dialog action's once its dialog is closed (open, the dialog shows it)
  const error = msg ?? (!pending && act.error ? act.error.message : null);

  /* -- Phase cards ------------------------------------------------- */
  const has = (id: ChangePhaseId) => m.phase.phases.some((x) => x.id === id);
  const state = (id: ChangePhaseId) => m.phase.phases.find((x) => x.id === id)!.state;
  const card = (id: ChangePhaseId) => ({
    id, index: CHANGE_PHASES.indexOf(id) + 1, title: t(`workitem.phase.${id}`), state: state(id),
    futureHint: id === "request" ? null : t(`workitem.future.change.${id}`),
    open: cards.isOpen(id), onToggle: (o: boolean) => cards.toggleCard(id, o),
  });
  const counts = plan && planCounts(plan);
  const planSummary = plan && counts && `${planLabel(plan, t)} · ${t("plan.counts")
    .replace("{steps}", String(counts.steps)).replace("{pre}", String(counts.preChecks))
    .replace("{post}", String(counts.postChecks)).replace("{rollback}", String(counts.rollback))}`;
  const latestRun = m.latestRun;
  // a cancel before any review / approval ends the list at ① / ②: who cancelled is said in that card
  const closedHere = (id: ChangePhaseId) => cr.status === "cancelled" && state(id) === "failed" && <ClosedRecord cr={cr} t={t} />;

  /* -- Render ------------------------------------------------------ */
  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
      <div className="space-y-4 min-w-0">
        <StatusLine
          refLabel={`C#${cr.id}`}
          title={cr.title}
          badges={
            <>
              {cr.risk_level && <RiskLevelBadge level={cr.risk_level} />}
              <span className="text-xs px-2 py-0.5 rounded bg-secondary text-muted-foreground">
                {t(`plans.changeType.${cr.effective_change_type ?? cr.requested_change_type}`)}
              </span>
            </>
          }
          statusLabel={t(m.statusKey)}
          tone={m.tone}
          reason={m.reason}
          waiting={m.waitingKey && t(m.waitingKey)}
          primary={primary}
          menu={menu}
          error={error}
          onDismissError={() => { setMsg(null); act.reset(); }}
          backTo="/app/plans?tab=changes"
          backLabel={t("nav.plans")}
        />

        {cards.openable.length > 0 && (
          <div className="flex justify-end">
            <button onClick={cards.toggleAll} className="text-xs text-primary hover:underline">
              {t(cards.allOpen ? "workitem.collapseAll" : "workitem.expandAll")}
            </button>
          </div>
        )}

        <PhaseCard {...card("request")} summary={requestSummary(cr, t)}>
          <div className="space-y-4">
            <RequestBody cr={cr} t={t} />
            {closedHere("request")}
          </div>
        </PhaseCard>

        {has("review") && (
          <PhaseCard {...card("review")} summary={reviewSummary(cr, t)}>
            <div className="space-y-4">
              <ReviewBody cr={cr} quietReasons={m.quietReviewReasons} impactNote={impactNote} clarify={clarify}
                          onClarifyChange={setClarify} onSendClarify={sendClarify} sending={act.isPending} t={t} />
              {/* the list ends here (a policy block): the plan it stopped stays readable */}
              {m.reviewPlan && (
                <div className="space-y-2 border-t border-border pt-4">
                  <h4 className="text-sm font-semibold text-foreground">{t("workitem.reviewedPlan")}</h4>
                  <PlanView plan={m.reviewPlan} stepsDiff={cr.steps_diff} t={t} />
                </div>
              )}
              {closedHere("review")}
            </div>
          </PhaseCard>
        )}

        {has("plan") && (
          <PhaseCard {...card("plan")} summary={planSummary}>
            {plan ? <PlanView plan={plan} stepsDiff={cr.steps_diff} t={t} />
                  : <p className="text-sm text-muted-foreground">{t("workitem.future.change.plan")}</p>}
          </PhaseCard>
        )}

        {has("run") && (
          <PhaseCard {...card("run")} summary={runSummary(cr, latestRun, t)}>
            <ChangeRunBody cr={cr} plan={plan} runs={m.runs} quietRunId={m.quietRunError ? latestRun?.id ?? null : null}
                           endsHere={!has("accept")} acceptNote={m.acceptNote}
                           onApprove={openApprove} onReject={openReject} onRetry={onExecute} busy={act.isPending} t={t} />
          </PhaseCard>
        )}

        {has("accept") && (
          <PhaseCard {...card("accept")}
                     summary={latestRun?.verification_status ? t(`verification.${latestRun.verification_status}`) : null}>
            <ChangeAcceptBody status={cr.status} latestRun={latestRun} quietReason={m.quietAcceptReason}
                              onCompleted={() => openAccept("completed")} onFailed={() => openAccept("failed")}
                              busy={act.isPending} t={t} />
          </PhaseCard>
        )}
      </div>

      {/* -- Right rail: key facts + activity -- */}
      <aside className="space-y-4 min-w-0">
        <FactsRail title={t("workitem.facts")} rows={changeFactRows(cr, acct, t)} t={t} />
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
              {cards.activityOpen && (tl.isLoading ? <Spinner label={t("common.loading")} />
                : tl.error ? <ErrorBanner message={tl.error.message} onRetry={() => tl.refetch()} actionLabel={t("common.retry")} />
                : <ActivityList entries={toActivity(toPipelineEvents(tl.data ?? []), { hideText: m.reason })} t={t}
                                emptyKey="changes.noEvents" />)}
            </CardBody>
          </Card>
        </section>
      </aside>

      {pending && (
        <ReasonDialog
          title={pending.title}
          description={pending.description}
          confirmText={pending.confirmText}
          variant={pending.variant}
          busy={act.isPending}
          error={act.error?.message ?? null}
          onConfirm={onDialogConfirm}
          onClose={() => setPending(null)}
        />
      )}
      {copy && (
        <NewChangeDialog
          onClose={() => setCopy(false)}
          onCreated={(newId) => {
            setCopy(false);
            navigate(`/app/changes/${newId}`);
          }}
          initial={{
            title: cr.title,
            description: cr.description,
            account_name: acct?.name,
            targets: cr.target_hints,
            requested_change_type: cr.requested_change_type,
            justification: cr.justification ?? undefined,
            proposed_steps: cr.proposed_steps ?? undefined,
            external_ref: cr.external_ref ?? undefined,
          }}
        />
      )}
      {dialog}
    </div>
  );
}
