import { useState } from "react";
import { ApiError } from "@/api/client";
import { useApproveFixPlan, useFixPlan } from "@/hooks/useFixPlans";
import { findAction } from "@/lib/approval";
import { parseItem } from "@/lib/inbox";
import { useRequestChanges } from "../../hooks/usePlanReview";
import { useNfT } from "../../i18n";
import { approveState, approvedToastKey } from "../../lib/briefs/plan";
import type { HoldTarget } from "../../lib/hold";
import { planBasis } from "../../lib/story";
import { utcStamp } from "../../lib/time";
import { StateBlock } from "../../shell/StateBlock";
import { BriefFrame } from "../BriefFrame";
import { Prov } from "../widgets/Cause";
import { CauseSection, useCause } from "../widgets/CauseSection";
import { HoldButton } from "../widgets/HoldButton";
import { ImpactSection } from "../widgets/ImpactSection";
import { ChecksSection, PlanSection } from "../widgets/PlanSection";
import { PrevDiffSection } from "../widgets/PrevDiffSection";
import { ReasonForm } from "../widgets/ReasonForm";
import { useHold } from "../widgets/useHold";
import { errorText, useBriefKeys, useDecide, useDecision, type BriefProps } from "./briefContext";
import { DismissForm } from "./shared";

export const REFUSALS = ["read_only", "forbidden", "issue_closed", "run_in_flight", "executor_disabled", "state", "no_hash"];
/** Why the server does not allow an action, in words. */
export const refusal = (why: string | null, t: (k: string, v?: Record<string, string | null>) => string): string =>
  t(REFUSALS.includes(why ?? "") ? `refused.${why}` : "refused.other", { code: why });

/** A refused approval in words. A 409 has many causes — the plan changed, someone else approved or rejected it, the
 *  issue was closed — and the server says which: its own sentence is shown, never one fixed guess. */
export const approveError = (e: unknown, t: (k: string, v?: Record<string, string>) => string): string =>
  t(e instanceof ApiError && e.status === 409 ? "err.refused" : "err.failed", { msg: errorText(e) });

/** While an approve brief is open its plan is read again this often: «approving does not run it» must not outlive
 *  the executor being switched on. */
export const PLAN_REFRESH_MS = 15_000;

/** A request for changes that was refused, in words: an agent already on the issue means the plan was NOT sent back. */
export const changesError = (e: unknown, t: (k: string, v?: Record<string, string>) => string): string =>
  e instanceof ApiError && e.code === "agent_run_in_flight" ? t("err.changesBusy")
    : e instanceof ApiError && e.code === "plan_changed" ? t("err.changesStale") : approveError(e, t);

/** A fix plan that waits for approval. Approving is bound to the content hash that was on the page; with the executor
 *  on it runs at once — so the key must be held, and the hold approves only the plan it began on. «R» asks for
 *  changes (N14): the plan is sent back with the reason and the plan agent redoes it — one request, both or neither;
 *  when the new plan comes back, the brief says what it changed (PrevDiffSection). */
export function ApproveBrief({ item, frame }: BriefProps) {
  const t = useNfT();
  const { openPeek } = useDecide();
  const decide = useDecision(item);
  const issueId = parseItem(item.id)?.id ?? 0;
  const planQ = useFixPlan(item.entity.entity_id, PLAN_REFRESH_MS);
  const source = useCause(issueId);
  const approve = useApproveFixPlan();
  const changes = useRequestChanges();
  const [form, setForm] = useState<null | "changes" | "close">(null);
  const [error, setError] = useState<string | null>(null);

  const plan = planQ.data;
  const state = plan ? approveState(plan) : null;
  const basis = plan ? planBasis(plan, source.rca) : "unknown";     // an approver should know a plan was not written from the diagnosis above it
  const canChange = !!plan && !!findAction(plan.available_actions, "request_changes")?.allowed;
  const target: HoldTarget | null = plan && state?.can && plan.content_hash && !frame.readOnly && !form && !approve.isPending
    ? { itemId: item.id, planId: plan.id, hash: plan.content_hash } : null;

  const hold = useHold(target, async (tg) => {
    setError(null);
    setError(await decide(
      () => approve.mutateAsync({ id: tg.planId, content_hash: tg.hash }),
      // what the server's answer says happened — the executor may have been switched on or off since the page was read
      (res) => t(approvedToastKey(res?.run_queued ?? undefined, state?.effect ?? "unknown"), { ref: item.ref }),
      (e) => approveError(e, t), t("pend.approve")));
  });

  useBriefKeys({
    onKey: (key, _e, repeat) => {
      if (form) return false;
      if (key === "a") { if (!repeat) hold.down("a"); return true; }
      hold.cancel();                                      // any other key lets go of a hold
      if (key === " " && source.cause?.evidence.length) { openPeek(source.cause.evidence, 0); return true; }
      if (frame.readOnly) return false;
      if (key === "r" && canChange) { setError(null); setForm("changes"); return true; }
      if (key === "d") { setError(null); setForm("close"); return true; }
      return false;
    },
    onKeyUp: (key) => { if (key === "a") hold.up(); },
    onEscape: () => { if (!form) return false; setForm(null); return true; },
  });

  const ask = !state ? t("ask.approve.loading") : !state.can ? t("ask.approve.cannot", { why: refusal(state.why, t) })
    : t(`ask.approve.${state.effect}`);

  const actions = form === "changes" && plan ? (
    <ReasonForm label={t("changes.label")} placeholder={t("changes.placeholder")} note={t("changes.note")} submit={t("act.changes")}
                busy={changes.isPending} error={error} onCancel={() => setForm(null)}
                onSubmit={async (reason) => {
                  setError(null);
                  setError(await decide(() => changes.mutateAsync({ id: plan.id, reason, content_hash: plan.content_hash }), t("toast.changesAsked", { ref: item.ref }),
                                        (e) => changesError(e, t), t("pend.changes")));
                }} />
  ) : form === "close" ? <DismissForm item={item} onCancel={() => setForm(null)} /> : (
    <>
      <HoldButton label={t(state?.effect === "run" ? "act.approve" : "act.approveOnly")} disabled={!target} holding={hold.holding} hint={hold.hint}
                  onDown={hold.down} onUp={hold.up} onCancel={hold.cancel} />
      {canChange && <button type="button" className="btn" onClick={() => { setError(null); setForm("changes"); }}><span className="t">{t("act.changes")}</span><kbd>R</kbd></button>}
      <span className="spacer" />
      <button type="button" className="btn quiet" onClick={() => { setError(null); setForm("close"); }}><span className="t">{t("act.close")}</span><kbd>D</kbd></button>
      {state?.shadow && <p className="note wide">{t("approve.shadow")}</p>}
      {error && <p className="note err wide" role="alert">{error}</p>}
    </>
  );

  return (
    <BriefFrame item={item} {...frame} ask={ask} actions={actions}>
      <CauseSection heading={t("sec.why")} source={source} />
      {plan && <PrevDiffSection plan={plan} now={frame.now} />}
      {planQ.isPending ? <div className="sec"><h2>{t("sec.plan")}</h2><StateBlock kind="loading" /></div>
        : planQ.isError || !plan ? <div className="sec"><h2>{t("sec.plan")}</h2><StateBlock kind="failed" failKey="sec.failedLoad" onRetry={() => void planQ.refetch()} /></div>
        : (
          <PlanSection plan={plan} heading={t("sec.plan")} kind="fix">
            {basis === "older" && <p className="note"><Prov code />{t("plan.basis.older")}</p>}
            {basis === "rewritten" && <p className="note"><Prov code />{t("plan.basis.rewritten", { t: utcStamp(plan.created_at, frame.now) })}</p>}
          </PlanSection>
        )}
      <ImpactSection subject={{ issueId }} tone={item.severity === "critical" ? "red" : "amber"} />
      {plan && <ChecksSection plan={plan} />}
    </BriefFrame>
  );
}
