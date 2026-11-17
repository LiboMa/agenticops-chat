import { useState, type ReactNode } from "react";
import type { FixPlan, UiAction } from "@/api/types";
import { useAuth } from "@/hooks/useAuth";
import { useChange, useChangeAction } from "@/hooks/useChanges";
import { useExecuteFixPlan, useFixPlan, useRejectFixPlan } from "@/hooks/useFixPlans";
import { findAction } from "@/lib/approval";
import { activeChangePlan } from "@/lib/changeDetail";
import { shortHash } from "@/lib/plans";
import { useNfT } from "../../i18n";
import { whoText } from "../../lib/activity";
import { executeState } from "../../lib/briefs/run";
import type { HoldTarget } from "../../lib/hold";
import { utcStamp } from "../../lib/time";
import { Message, StateBlock } from "../../shell/StateBlock";
import { BriefFrame } from "../BriefFrame";
import { Prov } from "../widgets/Cause";
import { HoldButton } from "../widgets/HoldButton";
import { ChecksSection, PlanSection } from "../widgets/PlanSection";
import { ReasonForm } from "../widgets/ReasonForm";
import { useHold } from "../widgets/useHold";
import { refusal } from "./ApproveBrief";
import { errorText, useBriefKeys, useDecide, type BriefProps } from "./briefContext";

interface ViewProps extends BriefProps {
  kind: "fix" | "change";
  query: { isPending: boolean; isError: boolean; refetch: () => unknown };
  plan: FixPlan | null;
  /** the actions the server offers for running it (`execute`) and for taking the approval back */
  actions: UiAction[] | undefined;
  canWithdraw: boolean;
  /** run it now — the approved plan, bound to the hash the page showed */
  run: () => Promise<unknown>;
  withdraw: (reason: string) => Promise<unknown>;
  withdrawn: { label: string; placeholder: string; note: string; toast: string };
}

/** An approved plan whose run never started: why, the plan as it was approved, and the two ways on — run it now
 *  (held: it changes infrastructure) or take the approval back. */
function NotStartedView({ item, frame, kind, query, plan, actions, canWithdraw, run, withdraw, withdrawn }: ViewProps) {
  const t = useNfT();
  const { user } = useAuth();
  const { done } = useDecide();
  const [form, setForm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const state = executeState(actions);
  const target: HoldTarget | null = plan && state.can && plan.content_hash && !frame.readOnly && !form && !busy
    ? { itemId: item.id, planId: plan.id, hash: plan.content_hash } : null;
  const act = async (what: () => Promise<unknown>, toast: string) => {
    setBusy(true);
    setError(null);
    try { await what(); done(toast); } catch (e) { setError(t("err.failed", { msg: errorText(e) })); } finally { setBusy(false); }
  };
  const hold = useHold(target, () => void act(run, t("toast.queued", { ref: item.ref })));

  useBriefKeys({
    onKey: (key, _e, repeat) => {
      if (form) return false;
      if (key === "a") { if (!repeat) hold.down(); return true; }
      hold.cancel();
      if (frame.readOnly) return false;
      if (key === "r" && canWithdraw) { setError(null); setForm(true); return true; }
      return false;
    },
    onKeyUp: (key) => { if (key === "a") hold.up(); },
    onEscape: () => { if (!form) return false; setForm(false); return true; },
  });

  const buttons: ReactNode = form ? (
    <ReasonForm label={t("reject.label")} placeholder={withdrawn.placeholder} note={withdrawn.note} submit={withdrawn.label}
                busy={busy} error={error} onCancel={() => setForm(false)} onSubmit={(reason) => void act(() => withdraw(reason), withdrawn.toast)} />
  ) : (
    <>
      <HoldButton label={t("act.retry")} disabled={!target} holding={hold.holding} hint={hold.hint} onDown={hold.down} onUp={hold.up} onCancel={hold.cancel} />
      {canWithdraw && <button type="button" className="btn" onClick={() => { setError(null); setForm(true); }}><span className="t">{withdrawn.label}</span><kbd>R</kbd></button>}
      {state.shadow && <p className="note wide">{t("approve.shadow")}</p>}
      {error && <p className="note err wide" role="alert">{error}</p>}
    </>
  );
  const drift = plan?.approved_hash ? plan.approved_hash !== plan.content_hash : null;
  return (
    <BriefFrame item={item} {...frame} actions={buttons}
                ask={state.can ? t("ask.not_started.can") : t("ask.not_started.cannot", { why: refusal(state.why, t) })}>
      <div className="sec">
        <h2>{t("sec.whyNotStarted")}</h2>
        <p><Prov code />{t(state.why === "executor_disabled" ? "notStarted.executor_disabled" : "notStarted.generic")}</p>
      </div>
      {query.isPending ? <StateBlock kind="loading" />
        : query.isError ? <StateBlock kind="failed" failKey="sec.failedLoad" onRetry={() => void query.refetch()} />
        : !plan ? <Message big={t("plan.none")} />
        : (
          <>
            <PlanSection plan={plan} heading={t("sec.approvedPlan")} kind={kind}>
              <p className="note"><Prov code />{t(drift === null ? "approved.line.unknown" : drift ? "approved.line.drift" : "approved.line.match",
                { by: whoText(plan.approved_by, user?.email, t), t: utcStamp(plan.approved_at), hash: shortHash(plan.approved_hash) })}</p>
            </PlanSection>
            <ChecksSection plan={plan} />
          </>
        )}
    </BriefFrame>
  );
}

/** An issue's approved fix plan that did not start. Taking the approval back = rejecting the approved plan. */
export function NotStartedBrief(props: BriefProps) {
  const t = useNfT();
  const planQ = useFixPlan(props.item.entity.entity_id);
  const execute = useExecuteFixPlan();
  const reject = useRejectFixPlan();
  const plan = planQ.data ?? null;
  return (
    <NotStartedView {...props} kind="fix" query={planQ} plan={plan} actions={plan?.available_actions}
                    canWithdraw={!!findAction(plan?.available_actions, "reject")?.allowed}
                    run={() => execute.mutateAsync(plan!.id)} withdraw={(reason) => reject.mutateAsync({ id: plan!.id, reason })}
                    withdrawn={{ label: t("act.withdraw"), placeholder: t("withdraw.placeholder"), note: t("withdraw.note"), toast: t("toast.withdrawn", { ref: props.item.ref }) }} />
  );
}

/** A change that was approved and whose run did not start. The way out is cancelling the change. */
export function ChangeNotStartedBrief(props: BriefProps) {
  const t = useNfT();
  const id = props.item.entity.entity_id;
  const changeQ = useChange(id);
  const action = useChangeAction();
  const cr = changeQ.data;
  return (
    <NotStartedView {...props} kind="change" query={changeQ} plan={cr ? activeChangePlan(cr.plans) : null} actions={cr?.available_actions}
                    canWithdraw={!!cr} run={() => action.mutateAsync({ id, action: "execute" })}
                    withdraw={(reason) => action.mutateAsync({ id, action: "cancel", body: { reason } })}
                    withdrawn={{ label: t("act.cancelChange"), placeholder: t("cancel.placeholder"), note: t("cancel.note"), toast: t("toast.cancelled", { ref: props.item.ref }) }} />
  );
}
