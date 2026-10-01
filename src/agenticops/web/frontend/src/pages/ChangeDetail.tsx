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
import { formatFullDate } from "@/lib/formatDate";
import { renderMarkdown } from "@/lib/renderMarkdown";
import { isHintResolved, policySummary, toPipelineEvents } from "@/lib/changeDetail";

// The dialog-driven actions; `useChanges` exports the discriminated `ChangeActionArgs`, not a `ChangeAction` alias,
// so `action` is kept to this subset and branched on below to build a well-typed mutate() argument.
type PendingAction = "approve" | "reject" | "cancel" | "resolve-review";
type Pending = {
  action: PendingAction;
  title: string;
  confirmText: string;
  variant?: "default" | "destructive";
  extra?: { outcome: "completed" | "failed" };
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
  const plan = cr.plans[0];
  const p = policySummary(cr.policy_decision, cr.review_reasons);
  const acct = cr.account_id != null ? accounts.data?.find((a) => a.id === cr.account_id) : undefined;

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
          ? { id: cr.id, action: "approve", body: { reason, content_hash: plan?.content_hash ?? "" } }
          : { id: cr.id, action: pending.action, body: { reason } };
    act.mutate(args, { onSuccess: () => setPending(null) });
  };
  const onExecute = async () => {
    if (await confirm(t("plans.executeConfirm"), { confirmText: t("issues.execute"), cancelText: t("common.cancel") })) {
      runDirect({ id: cr.id, action: "execute" });
    }
  };

  const canCancel = ["draft", "needs_clarification", "planned", "approved"].includes(cr.status);
  const canCopy = ["needs_review", "completed", "failed", "rolled_back", "rejected", "cancelled"].includes(cr.status);

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3 flex-wrap">
        {backLink}
        <h1 className="text-2xl font-semibold text-foreground">
          C#{cr.id} · {cr.title}
        </h1>
        <ChangeStatusBadge status={cr.status} />
        {cr.risk_level && <RiskLevelBadge level={cr.risk_level} />}
      </div>
      <ChangeStepper cr={cr} />
      {msg && <ErrorBanner message={msg} onRetry={() => setMsg(null)} actionLabel={t("common.close")} />}

      {/* Request */}
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
        </CardBody>
      </Card>

      {/* Review */}
      {(cr.review_verdict || cr.review_reasons.length > 0 || cr.policy_rule) && (
        <Card>
          <CardHeader>
            <h2 className="font-semibold">{t("changes.review")}</h2>
            <span className="text-xs text-muted-foreground">
              {joinDot([cr.reviewed_by, cr.reviewed_at && formatFullDate(cr.reviewed_at)])}
            </span>
          </CardHeader>
          <CardBody className="space-y-2 text-sm">
            <div>
              <span className="text-muted-foreground">{t("changes.verdict")}: </span>
              <span className="font-mono">{cr.review_verdict ?? "-"}</span>
            </div>
            {cr.action_type && (
              <div>
                <span className="text-muted-foreground">{t("changes.actionType")}: </span>
                <span className="font-mono">{cr.action_type}</span>
              </div>
            )}
            {cr.policy_rule && (
              <div>
                <span className="text-muted-foreground">{t("changes.policy")}: </span>
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
          </CardBody>
        </Card>
      )}

      {/* Plan */}
      {plan && (
        <Card>
          <CardHeader>
            <h2 className="font-semibold">
              {t("changes.plan")} #{plan.id}
            </h2>
            <FixPlanStatusBadge status={plan.status} />
          </CardHeader>
          <CardBody>
            <div
              className="text-muted-foreground mb-4 report-content"
              dangerouslySetInnerHTML={{ __html: renderMarkdown(plan.summary) }}
            />
            <ol className="space-y-4">
              {plan.steps.map((s, i) => (
                <RunbookStep key={i} index={i + 1} step={s} />
              ))}
            </ol>
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

      {/* Approval + actions */}
      <Card>
        <CardHeader>
          <h2 className="font-semibold">{t("changes.approval")}</h2>
          {cr.approved_by && (
            <span className="text-xs text-muted-foreground">
              {t("plans.approvedBy")}{" "}
              {joinDot([cr.approved_by, cr.approved_at && formatFullDate(cr.approved_at), cr.approval_reason])}
            </span>
          )}
          {cr.rejected_by && (
            <span className="text-xs text-red-500">
              {t(cr.status === "cancelled" ? "changes.status.cancelled" : "changes.status.rejected")}:{" "}
              {joinDot([cr.rejected_by, cr.rejected_at && formatFullDate(cr.rejected_at), cr.rejection_reason])}
            </span>
          )}
        </CardHeader>
        <CardBody className="flex flex-wrap gap-2 items-center">
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
              <label className="text-sm text-muted-foreground block">{t("changes.clarifyLabel")}</label>
              <textarea
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
                onClick={() =>
                  openDialog({ action: "approve", title: `${t("plans.approveTitle")} C#${cr.id}`, confirmText: t("issues.approve") })
                }
                className="px-4 py-2 text-sm rounded-lg bg-emerald-600 text-white disabled:opacity-50"
              >
                {t("issues.approve")}
              </button>
              <button
                disabled={act.isPending}
                onClick={() =>
                  openDialog({
                    action: "reject",
                    title: `${t("plans.rejectTitle")} C#${cr.id}`,
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
              {t("issues.execute")}
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
          {cr.status === "needs_review" && (
            <>
              <span className="w-full text-sm text-muted-foreground">{t("changes.needsReviewNote")}</span>
              <button
                disabled={act.isPending}
                onClick={() =>
                  openDialog({
                    action: "resolve-review",
                    title: `${t("changes.markCompleted")} C#${cr.id}`,
                    confirmText: t("changes.markCompleted"),
                    extra: { outcome: "completed" },
                  })
                }
                className="px-4 py-2 text-sm rounded-lg bg-emerald-600 text-white disabled:opacity-50"
              >
                {t("changes.markCompleted")}
              </button>
              <button
                disabled={act.isPending}
                onClick={() =>
                  openDialog({
                    action: "resolve-review",
                    title: `${t("changes.markFailed")} C#${cr.id}`,
                    confirmText: t("changes.markFailed"),
                    variant: "destructive",
                    extra: { outcome: "failed" },
                  })
                }
                className="px-4 py-2 text-sm rounded-lg border border-red-500/40 text-red-500 disabled:opacity-50"
              >
                {t("changes.markFailed")}
              </button>
            </>
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
        </CardBody>
      </Card>

      {/* Executions */}
      {cr.executions.length > 0 && (
        <Card>
          <CardHeader>
            <h2 className="font-semibold">{t("changes.execution")}</h2>
          </CardHeader>
          <CardBody>
            <ExecutionsTable executions={cr.executions} />
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
          }}
        />
      )}
      {dialog}
    </div>
  );
}
