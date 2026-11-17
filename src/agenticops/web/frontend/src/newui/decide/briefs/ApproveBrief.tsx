import { useState } from "react";
import { ApiError } from "@/api/client";
import { useApproveFixPlan, useFixPlan, useRejectFixPlan } from "@/hooks/useFixPlans";
import { findAction } from "@/lib/approval";
import { parseItem } from "@/lib/inbox";
import { useNfT } from "../../i18n";
import { approveState } from "../../lib/briefs/plan";
import type { HoldTarget } from "../../lib/hold";
import { StateBlock } from "../../shell/StateBlock";
import { BriefFrame } from "../BriefFrame";
import { CauseSection, useCause } from "../widgets/CauseSection";
import { HoldButton } from "../widgets/HoldButton";
import { ImpactSection } from "../widgets/ImpactSection";
import { ChecksSection, PlanSection } from "../widgets/PlanSection";
import { ReasonForm } from "../widgets/ReasonForm";
import { useHold } from "../widgets/useHold";
import { errorText, useBriefKeys, useDecide, type BriefProps } from "./briefContext";
import { DismissForm } from "./shared";

export const REFUSALS = ["read_only", "forbidden", "issue_closed", "run_in_flight", "executor_disabled", "state", "no_hash"];
/** Why the server does not allow an action, in words. */
export const refusal = (why: string | null, t: (k: string, v?: Record<string, string | null>) => string): string =>
  t(REFUSALS.includes(why ?? "") ? `refused.${why}` : "refused.other", { code: why });

/** A fix plan that waits for approval. Approving is bound to the content hash that was on the page; with the executor
 *  on it runs at once — so the key must be held, and the hold approves only the plan it began on. */
export function ApproveBrief({ item, frame }: BriefProps) {
  const t = useNfT();
  const { done, openPeek } = useDecide();
  const issueId = parseItem(item.id)?.id ?? 0;
  const planQ = useFixPlan(item.entity.entity_id);
  const source = useCause(issueId);
  const approve = useApproveFixPlan();
  const reject = useRejectFixPlan();
  const [form, setForm] = useState<null | "reject" | "close">(null);
  const [error, setError] = useState<string | null>(null);

  const plan = planQ.data;
  const state = plan ? approveState(plan) : null;
  const canReject = !!plan && !!findAction(plan.available_actions, "reject")?.allowed;
  const target: HoldTarget | null = plan && state?.can && plan.content_hash && !frame.readOnly && !form && !approve.isPending
    ? { itemId: item.id, planId: plan.id, hash: plan.content_hash } : null;

  const hold = useHold(target, async (tg) => {
    setError(null);
    try {
      await approve.mutateAsync({ id: tg.planId, content_hash: tg.hash });
      done(t(state?.runs ? "toast.approved.run" : "toast.approved.only", { ref: item.ref }));
    } catch (e) {
      setError(e instanceof ApiError && e.status === 409 ? t("err.changed") : t("err.failed", { msg: errorText(e) }));
    }
  });

  useBriefKeys({
    onKey: (key, _e, repeat) => {
      if (form) return false;
      if (key === "a") { if (!repeat) hold.down(); return true; }
      hold.cancel();                                      // any other key lets go of a hold
      if (key === " " && source.cause?.evidence.length) { openPeek(source.cause.evidence, 0); return true; }
      if (frame.readOnly) return false;
      if (key === "r" && canReject) { setError(null); setForm("reject"); return true; }
      if (key === "d") { setError(null); setForm("close"); return true; }
      return false;
    },
    onKeyUp: (key) => { if (key === "a") hold.up(); },
    onEscape: () => { if (!form) return false; setForm(null); return true; },
  });

  const ask = !state ? t("ask.approve.loading") : !state.can ? t("ask.approve.cannot", { why: refusal(state.why, t) })
    : t(state.runs ? "ask.approve.run" : "ask.approve.only");

  const actions = form === "reject" && plan ? (
    <ReasonForm label={t("reject.label")} placeholder={t("reject.placeholder")} note={t("reject.note")} submit={t("act.reject")}
                busy={reject.isPending} error={error} onCancel={() => setForm(null)}
                onSubmit={async (reason) => {
                  setError(null);
                  try { await reject.mutateAsync({ id: plan.id, reason }); done(t("toast.rejected", { ref: item.ref })); }
                  catch (e) { setError(t("err.failed", { msg: errorText(e) })); }
                }} />
  ) : form === "close" ? <DismissForm item={item} onCancel={() => setForm(null)} /> : (
    <>
      <HoldButton label={t(state?.runs ? "act.approve" : "act.approveOnly")} disabled={!target} holding={hold.holding} hint={hold.hint}
                  onDown={hold.down} onUp={hold.up} onCancel={hold.cancel} />
      {canReject && <button type="button" className="btn" onClick={() => { setError(null); setForm("reject"); }}><span className="t">{t("act.reject")}</span><kbd>R</kbd></button>}
      <span className="spacer" />
      <button type="button" className="btn quiet" onClick={() => { setError(null); setForm("close"); }}><span className="t">{t("act.close")}</span><kbd>D</kbd></button>
      {state?.shadow && <p className="note wide">{t("approve.shadow")}</p>}
      {error && <p className="note err wide" role="alert">{error}</p>}
    </>
  );

  return (
    <BriefFrame item={item} {...frame} ask={ask} actions={actions}>
      <CauseSection heading={t("sec.why")} source={source} />
      {planQ.isPending ? <div className="sec"><h2>{t("sec.plan")}</h2><StateBlock kind="loading" /></div>
        : planQ.isError || !plan ? <div className="sec"><h2>{t("sec.plan")}</h2><StateBlock kind="failed" failKey="sec.failedLoad" onRetry={() => void planQ.refetch()} /></div>
        : <PlanSection plan={plan} heading={t("sec.plan")} kind="fix" />}
      <ImpactSection subject={{ issueId }} tone={item.severity === "critical" ? "red" : "amber"} />
      {plan && <ChecksSection plan={plan} />}
    </BriefFrame>
  );
}
