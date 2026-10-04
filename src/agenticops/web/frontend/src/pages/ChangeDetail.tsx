import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useChange, useChangeAction, type ChangeActionArgs } from "@/hooks/useChanges";
import { useChangeTimeline } from "@/hooks/useChangeTimeline";
import { useSettings } from "@/hooks/useSettings";
import { useAccounts } from "@/hooks/useAccounts";
import { useLocale } from "@/i18n/LocaleContext";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { ApiError } from "@/api/client";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { RiskLevelBadge } from "@/components/ui/RiskLevelBadge";
import { FixPlanStatusBadge } from "@/components/ui/FixPlanStatusBadge";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { ChangeStepper } from "@/components/plans/ChangeStepper";
import { ChangeStatusBadge } from "@/components/plans/ChangeStatusBadge";
import { ReasonDialog } from "@/components/plans/ReasonDialog";
import { NewChangeDialog } from "@/components/plans/NewChangeDialog";
import { RunbookStep } from "@/components/plans/RunbookStep";
import { CheckItem } from "@/components/plans/CheckItem";
import { RollbackPlan } from "@/components/plans/RollbackPlan";
import { ExecutionsTable } from "@/components/plans/ExecutionsTable";
import { PipelineTimeline } from "@/components/plans/PipelineTimeline";
import { ExecutionEvidence } from "@/components/plans/ExecutionEvidence";
import { VerificationChip } from "@/components/plans/VerificationChip";
import { LocalGraph } from "@/components/graph/LocalGraph";
import { formatFullDate } from "@/lib/formatDate";
import { renderMarkdown } from "@/lib/renderMarkdown";
import {
  activeChangePlan, changeHeadline, externalRefLink, isHintResolved, planStepMarks, policySummary, toPipelineEvents,
  type ChangeNextAction,
} from "@/lib/changeDetail";
import { newestFirst } from "@/lib/issueDetail";
import { planLabel, shortHash } from "@/lib/plans";

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

// Join the present, non-empty parts of a header line with " · " (no dangling separators).
const joinDot = (parts: Array<string | null | undefined | false>): string =>
  parts.filter((x): x is string => typeof x === "string" && x.length > 0).join(" · ");

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

  const backLink = (
    <Link to="/app/changes" className="text-sm text-muted-foreground hover:text-foreground">
      ← {t("nav.changes")}
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
  if (!q.data) return notFoundNotice;

  const cr = q.data;
  // The plan an approve acts on (the backend's active_plan_for), so the dialog shows and sends its content_hash
  const plan = activeChangePlan(cr.plans);
  const p = policySummary(cr.policy_decision, cr.review_reasons);
  const acct = cr.account_id != null ? accounts.data?.find((a) => a.id === cr.account_id) : undefined;
  const runs = newestFirst(cr.executions);
  const latest = runs[0] ?? null;
  const head = changeHeadline(cr, latest);
  const marks = planStepMarks(cr.steps_diff);
  const ext = externalRefLink(cr.external_ref);
  const shadowImpact = cr.policy_decision?.shadow_blast_radius;
  // The graph's impact count only feeds the policy when enforced; until then the approval card labels it
  const impactNote = settings.data?.policy_graph_impact_enforce ? undefined : t("changes.impactReference");

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
  const openAccept = (outcome: "completed" | "failed") =>
    openDialog({
      action: "resolve-review",
      title: `${t(outcome === "completed" ? "changes.markCompleted" : "changes.markFailed")} C#${cr.id}`,
      confirmText: t(outcome === "completed" ? "changes.markCompleted" : "changes.markFailed"),
      variant: outcome === "failed" ? "destructive" : undefined,
      extra: { outcome },
    });
  const focusClarify = () => {
    const el = document.getElementById("change-clarify");
    el?.scrollIntoView({ behavior: "smooth", block: "center" });
    el?.focus();
  };
  // The header's primary button: the same handler as the card's, so the two never disagree
  const PRIMARY: Record<ChangeNextAction, { label: string; run: () => void }> = {
    review: { label: t("changes.startReview"), run: () => runDirect({ id: cr.id, action: "review" }) },
    clarify: { label: t("changes.answerReviewer"), run: focusClarify },
    approve: { label: t("changes.approveAndRun"), run: openApprove },
    execute: { label: t("changes.retryExecution"), run: onExecute },
    accept: { label: t("changes.markCompleted"), run: () => openAccept("completed") },
  };
  const primary = head.action ? PRIMARY[head.action] : null;

  const canCancel = ["draft", "needs_clarification", "planned", "approved"].includes(cr.status);
  const canCopy = ["needs_review", "completed", "failed", "rolled_back", "rejected", "cancelled"].includes(cr.status);
  const muted = "text-muted-foreground";

  return (
    <div className="space-y-6">
      {backLink}
      {/* One line: title · status · reason · to-do · primary action (spec §3.E.4) */}
      <Card>
        <CardBody className="space-y-3">
          <div className="flex items-center gap-3 flex-wrap">
            <span className="font-mono text-sm bg-secondary text-muted-foreground px-2 py-0.5 rounded">C#{cr.id}</span>
            <h1 className="text-2xl font-semibold text-foreground">{cr.title}</h1>
            {cr.risk_level && <RiskLevelBadge level={cr.risk_level} />}
          </div>
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
            <ChangeStatusBadge status={cr.status} />
            {head.reason && (
              <>
                <span className={muted}>·</span>
                <span className="min-w-0 break-words text-foreground">{head.reason}</span>
              </>
            )}
            <span className={muted}>·</span>
            <span className={muted}>{t("changes.todoLabel")}:</span>
            <span className="text-foreground">{t(`changes.todo.${head.todo ?? "none"}`)}</span>
            {primary && (
              <button
                disabled={act.isPending}
                onClick={primary.run}
                className="ml-auto px-3 py-1.5 text-xs font-medium rounded-lg bg-primary text-primary-foreground disabled:opacity-50"
              >
                {primary.label}
              </button>
            )}
          </div>
          <ChangeStepper cr={cr} />
        </CardBody>
      </Card>
      {msg && <ErrorBanner message={msg} onRetry={() => setMsg(null)} actionLabel={t("common.close")} />}

      {/* Request: what was asked for, with the requester's own steps and the external ticket */}
      <Card>
        <CardHeader>
          <h2 className="font-semibold">{t("changes.request")}</h2>
          <span className="text-xs text-muted-foreground" title={t("changes.source")}>
            {joinDot([cr.source, cr.trace_id])}
          </span>
        </CardHeader>
        <CardBody className="space-y-3">
          <div className="text-sm report-content" dangerouslySetInnerHTML={{ __html: renderMarkdown(cr.description) }} />
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
            <div>
              <span className="text-muted-foreground block">{t("plans.requestedBy")}</span>
              <span className="font-mono">{cr.requested_by}</span>
            </div>
            <div>
              <span className="text-muted-foreground block">{t("plans.type")}</span>
              {t(`plans.changeType.${cr.effective_change_type ?? cr.requested_change_type}`)}
            </div>
            <div>
              <span className="text-muted-foreground block">{t("issues.created")}</span>
              {formatFullDate(cr.requested_at ?? cr.created_at)}
            </div>
            <div>
              <span className="text-muted-foreground block">{t("plans.form.account")}</span>
              {cr.account_id == null
                ? t("plans.form.accountAny")
                : acct
                  ? `${acct.name} (${acct.provider})`
                  : `#${cr.account_id}`}
            </div>
          </div>
          {ext && (
            <div className="text-sm">
              <span className="text-muted-foreground">{t("changes.externalRef")}: </span>
              {ext.url ? (
                <a href={ext.url} target="_blank" rel="noopener noreferrer" className="font-mono text-primary hover:underline">
                  {ext.label}
                </a>
              ) : (
                <span className="font-mono">{ext.label}</span>
              )}
              {ext.requestedBy && (
                <span className="text-muted-foreground"> · {t("changes.externalRequestedBy").replace("{name}", ext.requestedBy)}</span>
              )}
            </div>
          )}
          <div>
            <span className="text-muted-foreground block text-sm mb-1">{t("changes.targets")}</span>
            <div className="flex flex-wrap gap-1">
              {cr.target_resources.map((x, i) => {
                const title = typeof x.evidence === "string" ? x.evidence : x.evidence.command;
                return x.db_id != null ? (
                  <Link
                    key={`${x.resource_id}-${i}`}
                    to={`/app/resources/${x.db_id}`}
                    className="px-1.5 py-0.5 rounded bg-secondary text-xs font-mono hover:underline"
                    title={title}
                  >
                    {x.resource_id}
                  </Link>
                ) : (
                  <span
                    key={`${x.resource_id}-${i}`}
                    className="px-1.5 py-0.5 rounded bg-secondary text-xs font-mono"
                    title={title}
                  >
                    {x.resource_id}
                  </span>
                );
              })}
              {cr.target_hints
                .filter((h) => !isHintResolved(h, cr.target_resources))
                .map((h, i) => (
                  <span
                    key={`hint-${i}`}
                    className="px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-600 text-xs font-mono"
                    title={t("changes.unresolved")}
                  >
                    {h}?
                  </span>
                ))}
            </div>
          </div>
          {cr.justification && (
            <div>
              <span className="text-muted-foreground block text-sm">{t("changes.justification")}</span>
              <p className="text-sm text-muted-foreground">{cr.justification}</p>
            </div>
          )}
          {(cr.proposed_steps?.length ?? 0) > 0 && (
            <div>
              <span className="text-muted-foreground block text-sm mb-1">{t("changes.proposedSteps")}</span>
              <ol className="space-y-1 text-sm">
                {cr.proposed_steps!.map((st, i) => (
                  <li key={i} className="flex gap-2">
                    <span className="font-mono text-xs text-muted-foreground pt-0.5">{i + 1}.</span>
                    <div className="min-w-0">
                      {st.action && <div className="text-foreground">{st.action}</div>}
                      <code className="text-xs font-mono break-all">{st.command}</code>
                    </div>
                  </li>
                ))}
              </ol>
            </div>
          )}
        </CardBody>
      </Card>

      {/* Implementation plan vN: its steps, how they differ from the request's, and its content hash */}
      {plan && (
        <Card>
          <CardHeader>
            <h2 className="font-semibold">{planLabel(plan, t)}</h2>
            <div className="flex items-center gap-2">
              <span className="text-xs font-mono text-muted-foreground">
                {t("plans.hash")} {shortHash(plan.content_hash)}
                {plan.approved_hash &&
                  ` · ${t("plans.approvedVersion").replace("{n}", String(plan.approved_version ?? plan.plan_version))} ${shortHash(plan.approved_hash)}`}
              </span>
              <FixPlanStatusBadge status={plan.status} />
            </div>
          </CardHeader>
          <CardBody>
            <div
              className="text-muted-foreground mb-4 report-content"
              dangerouslySetInnerHTML={{ __html: renderMarkdown(plan.summary) }}
            />
            {marks && (
              <p className="mb-3 text-xs text-muted-foreground">
                {t("changes.stepsDiff")}:{" "}
                {marks.identical
                  ? t("changes.stepsDiff.identical")
                  : t("changes.stepsDiff.summary")
                      .replace("{added}", String(marks.added))
                      .replace("{modified}", String(marks.modified))
                      .replace("{removed}", String(marks.removed.length))
                      .replace("{unchanged}", String(marks.unchanged))}
              </p>
            )}
            <ol className="space-y-4">
              {plan.steps.map((st, i) => {
                const mark = marks?.byPlanStep.get(i + 1);
                return (
                  <div key={i}>
                    {mark && (
                      <p className="mb-1 text-xs text-amber-600 dark:text-amber-400 break-all">
                        {mark.kind === "added"
                          ? t("changes.stepsDiff.added")
                          : t("changes.stepsDiff.modified").replace("{cmd}", mark.proposed)}
                      </p>
                    )}
                    <RunbookStep index={i + 1} step={st} />
                  </div>
                );
              })}
            </ol>
            {marks && marks.removed.length > 0 && (
              <div className="mt-4">
                <h4 className="font-semibold mb-1 text-sm">{t("changes.stepsDiff.removed")}</h4>
                <ul className="space-y-1 text-xs">
                  {marks.removed.map((r) => (
                    <li key={r.proposed_step} className="font-mono break-all text-muted-foreground line-through">
                      {r.proposed_step}. {r.command}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {plan.pre_checks.length > 0 && (
              <div className="mt-6">
                <h4 className="font-semibold mb-2">{t("issues.preChecks")}</h4>
                <ul className="space-y-1.5">
                  {plan.pre_checks.map((c, i) => (
                    <CheckItem key={i} item={c} />
                  ))}
                </ul>
              </div>
            )}
            {plan.post_checks.length > 0 && (
              <div className="mt-6">
                <h4 className="font-semibold mb-2">{t("issues.postChecks")}</h4>
                <ul className="space-y-1.5">
                  {plan.post_checks.map((c, i) => (
                    <CheckItem key={i} item={c} />
                  ))}
                </ul>
              </div>
            )}
            {Object.keys(plan.rollback_plan).length > 0 && <RollbackPlan plan={plan.rollback_plan} />}
          </CardBody>
        </Card>
      )}

      {/* Approval: what the review and the policy advised, apart from what a human actually decided */}
      <Card>
        <CardHeader>
          <h2 className="font-semibold">{t("changes.approval")}</h2>
        </CardHeader>
        <CardBody className="space-y-5">
          <section className="space-y-2 text-sm">
            <h3 className="font-medium text-foreground">
              {t("changes.policyAdvice")}
              <span className="ml-2 text-xs font-normal text-muted-foreground">
                {joinDot([cr.reviewed_by, cr.reviewed_at && formatFullDate(cr.reviewed_at)])}
              </span>
            </h3>
            <div>
              <span className={muted}>{t("changes.verdict")}: </span>
              <span className="font-mono">{cr.review_verdict ?? "-"}</span>
            </div>
            {cr.action_type && (
              <div>
                <span className={muted}>{t("changes.actionType")}: </span>
                <span className="font-mono">{cr.action_type}</span>
              </div>
            )}
            {cr.policy_rule && (
              <div>
                <span className={muted}>{t("changes.policy")}: </span>
                <span className="font-mono">
                  {cr.policy_rule} → {cr.policy_action}
                </span>
              </div>
            )}
            {cr.review_reasons.length > 0 && (
              <ul className="list-disc list-inside text-muted-foreground">
                {cr.review_reasons.map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
            )}
            {p.reasons.length > 0 && (
              <ul className="list-disc list-inside text-muted-foreground">
                {p.reasons.map((r, i) => (
                  <li key={`p-${i}`}>{r}</li>
                ))}
              </ul>
            )}
            {p.escalatedFrom && p.effectiveRisk && (
              <div className="text-amber-600">
                {t("changes.riskEscalated").replace("{from}", p.escalatedFrom).replace("{to}", p.effectiveRisk)}
              </div>
            )}
            {typeof shadowImpact === "number" && (
              <div className={muted}>{t("changes.shadowImpact").replace("{n}", String(shadowImpact))}</div>
            )}
            <div className="pt-1">
              <h4 className="mb-1 text-xs font-medium uppercase tracking-wider text-muted-foreground">
                {t("changes.impactGraph")}
              </h4>
              <LocalGraph subject={{ changeRequestId: cr.id }} note={impactNote} height={300} />
            </div>
          </section>

          <section className="space-y-1 text-sm border-t border-border pt-4">
            <h3 className="font-medium text-foreground">{t("changes.actualApproval")}</h3>
            {cr.approved_by ? (
              <p>
                <span className={muted}>{t("plans.approvedBy")}: </span>
                {joinDot([
                  cr.approved_by,
                  cr.approved_at && formatFullDate(cr.approved_at),
                  plan?.approved_hash &&
                    `${t("plans.approvedVersion").replace("{n}", String(plan.approved_version ?? plan.plan_version))} ${shortHash(plan.approved_hash)}`,
                ])}
                {cr.approval_reason && <span className="block text-muted-foreground">{cr.approval_reason}</span>}
              </p>
            ) : cr.rejected_by ? (
              <p className="text-red-500">
                {t(cr.status === "cancelled" ? "changes.status.cancelled" : "changes.status.rejected")}:{" "}
                {joinDot([cr.rejected_by, cr.rejected_at && formatFullDate(cr.rejected_at), cr.rejection_reason])}
              </p>
            ) : (
              <p className={muted}>{t("changes.notApproved")}</p>
            )}
          </section>

          <div className="flex flex-wrap gap-2 items-center">
            {cr.status === "draft" && (
              <button
                disabled={act.isPending}
                onClick={() => runDirect({ id: cr.id, action: "review" })}
                className="px-4 py-2 text-sm rounded-lg bg-primary text-primary-foreground disabled:opacity-50"
              >
                {t("changes.startReview")}
              </button>
            )}
            {cr.status === "under_review" && (
              <>
                <button
                  disabled={act.isPending}
                  onClick={() => runDirect({ id: cr.id, action: "review" })}
                  className="px-4 py-2 text-sm rounded-lg border border-border disabled:opacity-50"
                >
                  {t("changes.restartReview")}
                </button>
                <span className="text-xs text-muted-foreground">{t("changes.restartReviewHint")}</span>
              </>
            )}
            {cr.status === "needs_clarification" && (
              <div className="w-full space-y-2">
                <label htmlFor="change-clarify" className="text-sm text-muted-foreground block">{t("changes.clarifyLabel")}</label>
                <textarea
                  id="change-clarify"
                  rows={3}
                  maxLength={4000}
                  value={clarify}
                  onChange={(e) => setClarify(e.target.value)}
                  placeholder={t("changes.clarifyPlaceholder")}
                  className="w-full border border-border bg-background rounded-lg px-3 py-2 text-sm"
                />
                <button
                  disabled={!clarify.trim() || act.isPending}
                  onClick={sendClarify}
                  className="px-4 py-2 text-sm rounded-lg bg-primary text-primary-foreground disabled:opacity-50"
                >
                  {t("changes.clarify")}
                </button>
              </div>
            )}
            {cr.status === "planned" && (
              <>
                <button
                  disabled={act.isPending}
                  onClick={openApprove}
                  className="px-4 py-2 text-sm rounded-lg bg-emerald-600 text-white disabled:opacity-50"
                >
                  {t("changes.approveAndRun")}
                </button>
                <button
                  disabled={act.isPending}
                  onClick={() =>
                    openDialog({
                      action: "reject",
                      title: `${t("plans.rejectTitle")} ${plan ? planLabel(plan, t) : `C#${cr.id}`}`,
                      confirmText: t("issues.reject"),
                      variant: "destructive",
                    })
                  }
                  className="px-4 py-2 text-sm rounded-lg border border-red-500/40 text-red-500 disabled:opacity-50"
                >
                  {t("issues.reject")}
                </button>
              </>
            )}
            {cr.status === "approved" && (
              <button
                disabled={act.isPending}
                onClick={onExecute}
                className="px-4 py-2 text-sm rounded-lg bg-primary text-primary-foreground disabled:opacity-50"
              >
                {t("changes.retryExecution")}
              </button>
            )}
            {canCancel && (
              <button
                disabled={act.isPending}
                onClick={() =>
                  openDialog({
                    action: "cancel",
                    title: `${t("changes.cancelChange")} C#${cr.id}`,
                    confirmText: t("common.confirm"),
                    variant: "destructive",
                  })
                }
                className="px-4 py-2 text-sm rounded-lg border border-border text-muted-foreground disabled:opacity-50"
              >
                {t("changes.cancelChange")}
              </button>
            )}
            {cr.status === "executing" && (
              <span className="text-sm text-muted-foreground">{t("changes.executingNote")}</span>
            )}
            {canCopy && (
              <button
                disabled={accounts.isLoading}
                onClick={() => setCopy(true)}
                className="px-4 py-2 text-sm rounded-lg border border-border disabled:opacity-50"
              >
                {t("changes.copyAsNew")}
              </button>
            )}
          </div>
        </CardBody>
      </Card>

      {/* Execution evidence: the run history, then what each run did — newest first, the newest open */}
      {runs.length > 0 && (
        <Card>
          <CardHeader>
            <h2 className="font-semibold">{t("changes.execution")}</h2>
          </CardHeader>
          <CardBody className="space-y-4">
            <ExecutionsTable executions={runs} />
            {runs.map((ex, i) => (
              <details key={ex.id} open={i === 0} className="border-t border-border pt-3">
                <summary className="cursor-pointer text-sm font-semibold text-foreground">
                  {t("issues.executionN").replace("{n}", String(ex.id))}
                  <span className="ml-2 text-xs font-normal text-muted-foreground">
                    {ex.status}{ex.started_at && ` · ${formatFullDate(ex.started_at)}`}
                  </span>
                </summary>
                <div className="mt-4">
                  <ExecutionEvidence execution={ex} />
                </div>
              </details>
            ))}
          </CardBody>
        </Card>
      )}

      {/* Acceptance: the newest run's verification, and the human verdict a needs_review change waits for */}
      {(latest || cr.status === "needs_review") && (
        <Card>
          <CardHeader>
            <h2 className="font-semibold">{t("changes.acceptance")}</h2>
            {latest && <VerificationChip status={latest.verification_status} />}
          </CardHeader>
          <CardBody className="space-y-4">
            {latest ? (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
                <div className="md:col-span-2">
                  <span className="text-muted-foreground block">{t("verification.reason")}</span>
                  <span className="text-foreground whitespace-pre-wrap">{latest.verification_reason || "—"}</span>
                </div>
                <div>
                  <span className="text-muted-foreground block">{t("verification.acceptedBy")}</span>
                  <span className="text-foreground">{latest.accepted_by || "—"}</span>
                </div>
                <div>
                  <span className="text-muted-foreground block">{t("verification.acceptedAt")}</span>
                  <span className="text-foreground">{latest.accepted_at ? formatFullDate(latest.accepted_at) : "—"}</span>
                </div>
                <div className="md:col-span-2">
                  <span className="text-muted-foreground block">{t("verification.note")}</span>
                  <span className="text-foreground whitespace-pre-wrap">{latest.acceptance_note || "—"}</span>
                </div>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">{t("changes.noAcceptance")}</p>
            )}
            {cr.status === "needs_review" && (
              <div className="flex flex-wrap gap-2 items-center">
                <span className="w-full text-sm text-muted-foreground">{t("changes.needsReviewNote")}</span>
                <button
                  disabled={act.isPending}
                  onClick={() => openAccept("completed")}
                  className="px-4 py-2 text-sm rounded-lg bg-emerald-600 text-white disabled:opacity-50"
                >
                  {t("changes.markCompleted")}
                </button>
                <button
                  disabled={act.isPending}
                  onClick={() => openAccept("failed")}
                  className="px-4 py-2 text-sm rounded-lg border border-red-500/40 text-red-500 disabled:opacity-50"
                >
                  {t("changes.markFailed")}
                </button>
              </div>
            )}
          </CardBody>
        </Card>
      )}

      {/* Timeline */}
      <Card>
        <CardHeader>
          <h2 className="font-semibold">{t("changes.timeline")}</h2>
        </CardHeader>
        <CardBody>
          {tl.isLoading ? (
            <Spinner label={t("common.loading")} />
          ) : tl.error ? (
            <ErrorBanner message={tl.error.message} onRetry={() => tl.refetch()} actionLabel={t("common.retry")} />
          ) : (tl.data ?? []).length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("changes.noEvents")}</p>
          ) : (
            <PipelineTimeline events={toPipelineEvents(tl.data ?? [])} />
          )}
        </CardBody>
      </Card>

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
