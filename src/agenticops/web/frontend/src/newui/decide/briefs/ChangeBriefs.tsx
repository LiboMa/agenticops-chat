import { useRef, useState } from "react";
import type { ChangeRequestDetail } from "@/api/types";
import { useAuth } from "@/hooks/useAuth";
import { useChange, useChangeAction } from "@/hooks/useChanges";
import { useLocale } from "@/i18n/LocaleContext";
import { activeChangePlan, planStepMarks, policyActionLabel, verdictLabel } from "@/lib/changeDetail";
import { useNfT } from "../../i18n";
import { whoText } from "../../lib/activity";
import { canClarify, clarifyMessage, clarifyOverflow, requestVm } from "../../lib/briefs/change";
import { approveState, approvedToastKey } from "../../lib/briefs/plan";
import type { HoldTarget } from "../../lib/hold";
import { Message, StateBlock } from "../../shell/StateBlock";
import { BriefFrame } from "../BriefFrame";
import { AcceptBody, useAcceptChecklist } from "../widgets/AcceptBody";
import { Prov } from "../widgets/Cause";
import { HoldButton } from "../widgets/HoldButton";
import { ImpactSection } from "../widgets/ImpactSection";
import { ChecksSection, PlanSection } from "../widgets/PlanSection";
import { ReasonForm } from "../widgets/ReasonForm";
import { Steps } from "../widgets/Steps";
import { useHold } from "../widgets/useHold";
import { approveError, refusal } from "./ApproveBrief";
import { useBriefKeys, useDecision, type BriefProps } from "./briefContext";

/** «What is asked for»: the request in the requester's words, who asked, the resources it resolved to and the names
 *  that matched nothing. */
function RequestSection({ cr }: { cr: ChangeRequestDetail }) {
  const t = useNfT();
  const { user } = useAuth();
  const r = requestVm(cr);
  return (
    <div className="sec">
      <h2>{t("sec.request")}</h2>
      <p>{r.text}</p>
      {r.why && <p className="note">{t("request.why", { why: r.why })}</p>}
      <p className="note">
        {t("request.by", { by: whoText(r.by, user?.email, t) })}{r.emergency ? `　${t("request.emergency")}` : ""}{"　"}
        {r.targets.length ? t("request.targets", { targets: r.targets.map((x) => `${x.type} ${x.id}${x.region ? ` (${x.region})` : ""}`).join("、") }) : t("request.noTargets")}
      </p>
      {r.unresolved.length > 0 && <p className="note err">{t("request.unresolved", { hints: r.unresolved.join("、") })}</p>}
    </div>
  );
}

/** The loading / failed / gone states every change brief shares. */
function useChangeBrief(id: number) {
  const t = useNfT();
  const q = useChange(id);
  const state = q.isPending ? <StateBlock kind="loading" />
    : q.isError || !q.data ? <StateBlock kind="failed" failKey="sec.failedLoad" onRetry={() => void q.refetch()} /> : null;
  return { t, q, cr: q.data ?? null, state };
}

/** A change request still a draft: hand it to the reviewing agent (read-only), or cancel it. */
export function StartReviewBrief({ item, frame }: BriefProps) {
  const id = item.entity.entity_id;
  const { t, cr, state } = useChangeBrief(id);
  const decide = useDecision(item);
  const action = useChangeAction();
  const [form, setForm] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const send = async (what: () => Promise<unknown>, toast: string, label: string) => {
    setError(null);
    setError(await decide(what, toast, undefined, label));
  };
  const start = () => { if (!action.isPending && !frame.readOnly && cr) void send(() => action.mutateAsync({ id, action: "review" }), t("toast.sentReview", { ref: item.ref }), t("pend.review")); };
  useBriefKeys({
    onKey: (key, _e, repeat) => {
      if (form || frame.readOnly) return false;
      if (key === "a") { if (!repeat) start(); return true; }
      if (key === "r") { setError(null); setForm(true); return true; }
      return false;
    },
    onEscape: () => { if (!form) return false; setForm(false); return true; },
  });
  const proposed = cr ? requestVm(cr).proposed : [];
  const actions = form ? (
    <ReasonForm label={t("reject.label")} placeholder={t("cancel.placeholder")} note={t("cancel.note")} submit={t("act.cancelChange")}
                busy={action.isPending} error={error} onCancel={() => setForm(false)}
                onSubmit={(reason) => void send(() => action.mutateAsync({ id, action: "cancel", body: { reason } }), t("toast.cancelled", { ref: item.ref }), t("pend.cancel"))} />
  ) : (
    <>
      <button type="button" className="btn primary" disabled={!cr || action.isPending} onClick={start}><span className="t">{t("act.startReview")}</span><kbd>A</kbd></button>
      <button type="button" className="btn" disabled={!cr} onClick={() => { setError(null); setForm(true); }}><span className="t">{t("act.cancelChange")}</span><kbd>R</kbd></button>
      {error && <p className="note err wide" role="alert">{error}</p>}
    </>
  );
  return (
    <BriefFrame item={item} {...frame} ask={t("ask.start_review")} actions={actions}>
      {state ?? (cr && (
        <>
          <RequestSection cr={cr} />
          <div className="sec">
            <h2>{t("sec.proposed")}</h2>
            {proposed.length ? <Steps steps={proposed} /> : <p className="note">{t("proposed.none")}</p>}
            <p className="note">{t("review.note")}</p>
          </div>
        </>
      ))}
    </BriefFrame>
  );
}

/** A review that stopped on questions: answer them. The server takes one message; the page asks one question at a
 *  time and puts the answers together. */
export function ClarifyBrief({ item, frame }: BriefProps) {
  const id = item.entity.entity_id;
  const { t, cr, state } = useChangeBrief(id);
  const decide = useDecision(item);
  const action = useChangeAction();
  const [answers, setAnswers] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const questions = cr?.review_reasons ?? [];
  const ready = !!cr && canClarify(questions, answers);
  const over = cr ? clarifyOverflow(questions, answers) : 0;       // the server takes one message of a fixed size: too long is not sent, never cut
  const submit = async () => {
    if (!ready || action.isPending || frame.readOnly) return;
    setError(null);
    setError(await decide(() => action.mutateAsync({ id, action: "clarify", body: { message: clarifyMessage(questions, answers) } }),
                          t("toast.answered", { ref: item.ref }), undefined, t("pend.clarify")));
  };
  useBriefKeys({ onKey: (key, _e, repeat) => { if (key !== "a") return false; if (!repeat) void submit(); return true; } });
  const field = (k: number) => frame.readOnly ? null : (
    <input className="field" value={answers[k] ?? ""} placeholder={t("clarify.ph")} aria-label={t("clarify.label", { n: k + 1 })} maxLength={1500}
           onChange={(e) => setAnswers((old) => { const next = [...old]; next[k] = e.target.value; return next; })} />
  );
  const actions = (
    <>
      <button type="button" className="btn primary" disabled={!ready || action.isPending} onClick={() => void submit()}><span className="t">{t("act.submitAnswers")}</span><kbd>A</kbd></button>
      {!ready && cr && <span className="readonly-note" role={over ? "alert" : undefined}>{over ? t("clarify.tooLong", { n: over }) : t("clarify.required")}</span>}
      {error && <p className="note err wide" role="alert">{error}</p>}
    </>
  );
  return (
    <BriefFrame item={item} {...frame} ask={questions.length ? t("ask.clarify", { n: questions.length }) : t("ask.clarify.one")} actions={actions}>
      {state ?? (cr && (
        <>
          <RequestSection cr={cr} />
          <div className="sec">
            <h2>{t("sec.questions")}</h2>
            {questions.length ? questions.map((q, k) => (
              <div key={k}><p style={{ margin: `${k ? 12 : 0}px 0 6px` }}><Prov code={false} />{k + 1}. {q}</p>{field(k)}</div>
            )) : <><p style={{ margin: "0 0 6px" }}>{t("clarify.free")}</p>{field(0)}</>}
            <p className="note">{t("clarify.note")}</p>
          </div>
        </>
      ))}
    </BriefFrame>
  );
}

/** A reviewed change waiting for approval. The server wants a reason with the approval, so the reason comes first
 *  and the hold second; the approval is bound to the implementation plan's content hash. */
export function ChangeApproveBrief({ item, frame }: BriefProps) {
  const id = item.entity.entity_id;
  const { t, cr, state: loadState } = useChangeBrief(id);
  const { t: classic } = useLocale();
  const decide = useDecision(item);
  const action = useChangeAction();
  const [reason, setReason] = useState("");
  const [nudge, setNudge] = useState(false);
  const [form, setForm] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const reasonBox = useRef<HTMLInputElement>(null);
  const reasonNow = useRef(reason);
  reasonNow.current = reason;

  const plan = cr ? activeChangePlan(cr.plans) : null;
  const state = cr ? approveState({ available_actions: cr.available_actions, content_hash: plan?.content_hash ?? null }) : null;
  const armed = !!plan && !!state?.can && !!plan.content_hash && !frame.readOnly && !form && !action.isPending;
  const target: HoldTarget | null = armed && reason.trim() ? { itemId: item.id, planId: plan!.id, hash: plan!.content_hash! } : null;
  const hold = useHold(target, async (tg) => {
    setError(null);
    setError(await decide(
      () => action.mutateAsync({ id, action: "approve", body: { reason: reasonNow.current.trim(), content_hash: tg.hash } }),
      // the answer is the change as it now stands: «executing» = its run was queued, «approved» = it was not
      (res) => t(approvedToastKey("status" in res && (res.status === "executing" || res.status === "approved") ? res.status === "executing" : undefined,
                                  state?.effect ?? "unknown"), { ref: item.ref }),
      (e) => approveError(e, t), t("pend.approve")));
  });
  // the reason comes first. The focus moves to its box when the key comes UP: a key still held would repeat into
  // the box («aaaa…» as the reason) on systems that repeat letters
  const wantReason = useRef(false);
  const down = (key?: string) => {
    if (armed && !reason.trim()) { setNudge(true); if (key === "a") wantReason.current = true; else reasonBox.current?.focus(); return; }
    hold.down(key);
  };

  useBriefKeys({
    onKey: (key, _e, repeat) => {
      if (form) return false;
      if (key === "a") { if (!repeat) down("a"); return true; }
      hold.cancel();
      if (frame.readOnly) return false;
      if (key === "d" && cr) { setError(null); setForm(true); return true; }
      return false;
    },
    onKeyUp: (key) => {
      if (key !== "a") return;
      hold.up();
      if (wantReason.current) { wantReason.current = false; reasonBox.current?.focus(); }
    },
    onEscape: () => { if (!form) return false; setForm(false); return true; },
  });

  const marks = cr ? planStepMarks(cr.steps_diff) : null;
  const ask = !state ? t("ask.approve.loading") : !state.can ? t("ask.approve.cannot", { why: plan ? refusal(state.why, t) : t("plan.none") })
    : t(`ask.approve.${state.effect}`);
  const actions = form ? (
    <ReasonForm label={t("close.label")} placeholder={t("rejectChange.placeholder")} note={t("rejectChange.note")} submit={t("act.rejectChange")}
                busy={action.isPending} error={error} onCancel={() => setForm(false)}
                onSubmit={async (why) => {
                  setError(null);
                  setError(await decide(() => action.mutateAsync({ id, action: "reject", body: { reason: why } }), t("toast.rejectedChange", { ref: item.ref }),
                                        undefined, t("pend.rejectChange")));
                }} />
  ) : (
    <>
      <input ref={reasonBox} className="field reason-in" value={reason} maxLength={2000} disabled={!armed} placeholder={t("approve.reason.ph")}
             aria-label={t("approve.reason.label")} aria-invalid={nudge && !reason.trim()}
             onChange={(e) => { setReason(e.target.value); setNudge(false); }} />
      <HoldButton label={t(state?.effect === "run" ? "act.approve" : "act.approveOnly")} disabled={!armed} holding={hold.holding} hint={hold.hint}
                  onDown={down} onUp={hold.up} onCancel={hold.cancel} />
      <span className="spacer" />
      <button type="button" className="btn quiet" disabled={!cr} onClick={() => { setError(null); setForm(true); }}><span className="t">{t("act.rejectChange")}</span><kbd>D</kbd></button>
      {nudge && !reason.trim() && <p className="note wide" role="status">{t("approve.reason.need")}</p>}
      {state?.shadow && <p className="note wide">{t("approve.shadow")}</p>}
      {error && <p className="note err wide" role="alert">{error}</p>}
    </>
  );
  return (
    <BriefFrame item={item} {...frame} ask={ask} actions={actions}>
      {loadState ?? (cr && (
        <>
          <RequestSection cr={cr} />
          <div className="sec">
            <h2>{t("sec.review")}</h2>
            {cr.review_verdict ? (
              <p><Prov code={false} />{verdictLabel(cr.review_verdict, classic)}{cr.risk_level ? `　${t("review.risk", { risk: cr.risk_level })}` : ""}</p>
            ) : <p className="note">{t("review.none")}</p>}
            {cr.review_reasons.length > 0 && <ul className="notes" style={{ marginTop: 8 }}>{cr.review_reasons.map((r, k) => <li key={k}>{r}</li>)}</ul>}
            {cr.policy_rule && <p className="note"><Prov code />{t("review.policy", { rule: cr.policy_rule, action: policyActionLabel(cr.policy_action ?? "", classic) })}</p>}
          </div>
          {plan ? (
            <PlanSection plan={plan} heading={t("sec.plan")} kind="change">
              {marks && !marks.identical && (
                <p className="note"><Prov code />{t("plan.diffNote", { added: marks.added, modified: marks.modified, removed: marks.removed.length, unchanged: marks.unchanged })}</p>
              )}
            </PlanSection>
          ) : <div className="sec"><h2>{t("sec.plan")}</h2><p className="note">{t("plan.none")}</p></div>}
          <ImpactSection subject={{ changeRequestId: id }} tone="violet" />
          {plan && <ChecksSection plan={plan} />}
        </>
      ))}
    </BriefFrame>
  );
}

/** A change whose run ended and needs a person's verdict: the same checklist as an issue's acceptance; the verdict
 *  ends the change — completed, or failed. */
export function ChangeAcceptBrief({ item, frame }: BriefProps) {
  const id = item.entity.entity_id;
  const { t, cr, state } = useChangeBrief(id);
  const decide = useDecision(item);
  const action = useChangeAction();
  const run = cr ? [...cr.executions].sort((a, b) => b.created_at.localeCompare(a.created_at) || b.id - a.id)[0] ?? null : null;
  const runPlan = run && cr ? cr.plans.find((p) => p.id === run.fix_plan_id) ?? null : null;
  const list = useAcceptChecklist(run, runPlan);
  const [form, setForm] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const send = async (outcome: "completed" | "failed", reason: string) => {
    setError(null);
    setError(await decide(
      () => action.mutateAsync({ id, action: "resolve-review", body: { outcome, reason, ...(outcome === "completed" ? { confirmed_checks: list.confirmed() } : {}) } }),
      t(outcome === "completed" ? "toast.completed" : "toast.changeFailed", { ref: item.ref }), undefined,
      t(outcome === "completed" ? "pend.complete" : "pend.changeFailed")));
  };
  const complete = () => { if (list.ready && !action.isPending) void send("completed", list.reason()); };
  useBriefKeys({
    onKey: (key, _e, repeat) => {
      if (form || frame.readOnly || !run) return false;
      if (key === "a") { if (!repeat) complete(); return true; }
      if (key === "x") { list.tickNext(); return true; }
      if (key === "r") { setError(null); setForm(true); return true; }
      return false;
    },
    onEscape: () => { if (!form) return false; setForm(false); return true; },
  });
  const n = list.vm?.toVerify.length ?? 0;
  const actions = form ? (
    <ReasonForm label={t("reject.label")} placeholder={t("fail.placeholder")} note={t("failChange.note")} submit={t("act.failChange")}
                busy={action.isPending} error={error} onCancel={() => setForm(false)} onSubmit={(reason) => void send("failed", reason)} />
  ) : (
    <>
      <button type="button" className="btn primary" disabled={!list.ready || action.isPending} onClick={complete}><span className="t">{t("act.complete")}</span><kbd>A</kbd></button>
      <button type="button" className="btn" disabled={!run || list.ready} onClick={list.tickNext}><span className="t">{t("act.tick")}</span><kbd>X</kbd></button>
      <button type="button" className="btn" disabled={!run} onClick={() => { setError(null); setForm(true); }}><span className="t">{t("act.failChange")}</span><kbd>R</kbd></button>
      {error && <p className="note err wide" role="alert">{error}</p>}
    </>
  );
  return (
    <BriefFrame item={item} {...frame} ask={n > 0 ? t("ask.acceptChange", { n }) : t("ask.acceptChange.none")} actions={actions}>
      {state ?? (!list.vm ? <Message big={t("accept.none")} /> : <AcceptBody list={list} readOnly={frame.readOnly} why={cr?.needs_review_reason} item={item.id} now={frame.now} />)}
    </BriefFrame>
  );
}
