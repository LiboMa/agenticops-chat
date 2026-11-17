import { useState } from "react";
import { ApiError } from "@/api/client";
import { useAnomalyRca } from "@/hooks/useAnomalyRca";
import { useApproveFixPlan, useFixPlan, useRejectFixPlan } from "@/hooks/useFixPlans";
import { useGraphFocus } from "@/hooks/useGraphFocus";
import { useSettings } from "@/hooks/useSettings";
import { findAction } from "@/lib/approval";
import { parseItem } from "@/lib/inbox";
import { useDismissIssue } from "../../hooks/useIssueDecisions";
import { useNfT } from "../../i18n";
import { causeVm } from "../../lib/briefs/cause";
import { approveState, planHead, postChecksVm, rollbackVm, stepsVm } from "../../lib/briefs/plan";
import type { HoldTarget } from "../../lib/hold";
import { StateBlock } from "../../shell/StateBlock";
import { BriefFrame } from "../BriefFrame";
import { Cause, Prov } from "../widgets/Cause";
import { HoldButton } from "../widgets/HoldButton";
import { ReasonForm } from "../widgets/ReasonForm";
import { Steps } from "../widgets/Steps";
import { useHold } from "../widgets/useHold";
import { errorText, useBriefKeys, useDecide, type BriefProps } from "./briefContext";

const REFUSALS = ["read_only", "forbidden", "issue_closed", "run_in_flight", "executor_disabled", "state", "no_hash"];

/** A fix plan that waits for approval. Approving is bound to the content hash that was on the page; with the executor
 *  on it runs at once — so the key must be held, and the hold approves only the plan it began on. */
export function ApproveBrief({ item, frame }: BriefProps) {
  const t = useNfT();
  const { done, openPeek } = useDecide();
  const issueId = parseItem(item.id)?.id ?? 0;
  const planQ = useFixPlan(item.entity.entity_id);
  const rcaQ = useAnomalyRca(issueId);
  const focusQ = useGraphFocus({ issueId });
  const settings = useSettings();
  const approve = useApproveFixPlan();
  const reject = useRejectFixPlan();
  const dismiss = useDismissIssue(issueId);
  const [form, setForm] = useState<null | "reject" | "close">(null);
  const [error, setError] = useState<string | null>(null);

  const plan = planQ.data;
  const state = plan ? approveState(plan) : null;
  const cause = causeVm(rcaQ.data, settings.data?.rca_min_confidence_for_autofix);
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
      if (key === " " && cause?.evidence.length) { openPeek(cause.evidence, 0); return true; }
      if (frame.readOnly) return false;
      if (key === "r" && canReject) { setError(null); setForm("reject"); return true; }
      if (key === "d") { setError(null); setForm("close"); return true; }
      return false;
    },
    onKeyUp: (key) => { if (key === "a") hold.up(); },
    onEscape: () => { if (!form) return false; setForm(null); return true; },
  });

  const why = state && !state.can ? t(REFUSALS.includes(state.why ?? "") ? `refused.${state.why}` : "refused.other", { code: state.why }) : null;
  const ask = !state ? t("ask.approve.loading") : why ? t("ask.approve.cannot", { why }) : t(state.runs ? "ask.approve.run" : "ask.approve.only");

  const actions = form === "reject" && plan ? (
    <ReasonForm label={t("reject.label")} placeholder={t("reject.placeholder")} note={t("reject.note")} submit={t("act.reject")}
                busy={reject.isPending} error={error} onCancel={() => setForm(null)}
                onSubmit={async (reason) => {
                  setError(null);
                  try { await reject.mutateAsync({ id: plan.id, reason }); done(t("toast.rejected", { ref: item.ref })); }
                  catch (e) { setError(t("err.failed", { msg: errorText(e) })); }
                }} />
  ) : form === "close" ? (
    <ReasonForm label={t("close.label")} placeholder={t("close.placeholder")} note={t("close.note")} submit={t("act.close")}
                busy={dismiss.busy} error={dismiss.error && t("err.failed", { msg: dismiss.error })} onCancel={() => setForm(null)}
                onSubmit={async (reason) => { if (await dismiss.dismiss(reason, t("close.notePrefix"))) done(t("toast.closed", { ref: item.ref })); }} />
  ) : (
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

  const head = plan ? planHead(plan) : null;
  const steps = plan ? stepsVm(plan) : [];
  const checks = plan ? postChecksVm(plan) : [];
  const rollback = plan ? rollbackVm(plan) : null;
  const focus = focusQ.data;
  const fan = focus ? Math.min(focus.blast.structural, 6) : 0;
  const tone = item.severity === "critical" ? "red" : "amber";

  return (
    <BriefFrame item={item} {...frame} ask={ask} actions={actions}>
      <div className="sec">
        <h2>{t("sec.why")}</h2>
        {rcaQ.isPending ? <div className="skel" style={{ height: 54 }} />
          : rcaQ.isError ? <p className="note err">{t("sec.failedLoad")}</p>
          : cause ? <Cause cause={cause} /> : <p className="note">{t("cause.none")}</p>}
      </div>

      <div className="sec">
        <h2>
          {t("sec.plan")}
          {head && <>　<span className="num" style={{ color: "var(--dim)" }}>
            {t("plan.version", { label: t("plan.label.fix"), v: head.version })}　{head.hash8 && t("plan.hash", { hash: head.hash8 })}　{head.risk}
          </span></>}
        </h2>
        {planQ.isPending ? <StateBlock kind="loading" />
          : planQ.isError || !plan ? <StateBlock kind="failed" failKey="sec.failedLoad" onRetry={() => void planQ.refetch()} />
          : (
            <>
              {steps.length ? <Steps steps={steps} /> : <p className="note">{t("plan.noSteps")}</p>}
              {steps.some((s) => s.tier) && <p className="note"><Prov code />{t("plan.tierNote")}</p>}
              <p className="note">{t("plan.rollback")}{rollback?.trigger ? `　${t("plan.rollback.trigger", { t: rollback.trigger })}` : ""}</p>
              {rollback && rollback.steps.length > 0 && <Steps steps={rollback.steps} />}
              {rollback && rollback.notes.length > 0 && (
                <dl className="res rb">{rollback.notes.map((n) => <div key={n.label}><dt>{n.label}</dt><dd>{n.text}</dd></div>)}</dl>
              )}
              {rollback && !rollback.steps.length && !rollback.notes.length && <p className="note">{t("plan.rollback.none")}</p>}
            </>
          )}
      </div>

      <div className="sec">
        <h2>{t("sec.impact")}</h2>
        {focusQ.isPending ? <div className="skel" style={{ height: 54 }} />
          : focusQ.isError || !focus ? <p className="note err">{t("sec.failedLoad")}</p>
          : focus.anchor.status !== "anchored" ? <p className="note">{t("impact.unanchored")}</p>
          : (
            <div className="impact">
              <svg width="150" height="84" viewBox="0 0 150 84" role="img" aria-label={t("impact.fan")}>
                {Array.from({ length: fan }, (_, k) => {
                  const y = fan === 1 ? 42 : 12 + k * (60 / (fan - 1));
                  return <g key={k}><line x1="20" y1="42" x2="124" y2={y} stroke={`var(--${tone})`} strokeOpacity=".55" /><circle cx="124" cy={y} r="4" fill="var(--chalk)" fillOpacity=".85" /></g>;
                })}
                <circle cx="20" cy="42" r="6" fill={`var(--${tone})`} /><circle cx="20" cy="42" r="11" fill="none" stroke={`var(--${tone})`} strokeOpacity=".5" />
              </svg>
              <div>
                <div className="nums">
                  <div><b>{focus.blast.structural}</b>{t("impact.structural")}</div>
                  <div><b>{focus.blast.potential}</b>{t("impact.potential")}</div>
                  <div><b>{focus.blast.observed}</b>{t("impact.observed")}</div>
                </div>
                <p className="note"><Prov code />{t("impact.note")}{focus.blast.truncated ? ` ${t("impact.truncated")}` : ""}</p>
              </div>
            </div>
          )}
      </div>

      <div className="sec">
        <h2>{t("sec.done")}</h2>
        {plan && checks.length > 0 ? (
          <>
            <ul className="checks">
              {checks.map((c) => <li key={c.id}><span className="pc">{c.id}</span><span>{c.text}</span><span className="st">{t("checks.after")}</span></li>)}
            </ul>
            <p className="note">{t("checks.note")}</p>
          </>
        ) : plan ? <p className="note">{t("checks.none")}</p> : <div className="skel" style={{ height: 40 }} />}
      </div>
    </BriefFrame>
  );
}
