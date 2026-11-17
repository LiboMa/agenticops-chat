import { useEffect, useState } from "react";
import { useAcceptExecution } from "@/hooks/useFixExecutions";
import { useFixPlan } from "@/hooks/useFixPlans";
import { useIssueExecutions } from "@/hooks/useIssueExecutions";
import { useLocale } from "@/i18n/LocaleContext";
import { acceptReason, canAccept, checklistItems, confirmedIds } from "@/lib/acceptChecklist";
import { parseItem } from "@/lib/inbox";
import { runSummary } from "@/lib/runSummary";
import { useNfT } from "../../i18n";
import { acceptVm, runToAccept } from "../../lib/briefs/accept";
import { Message, StateBlock } from "../../shell/StateBlock";
import { BriefFrame } from "../BriefFrame";
import { Prov } from "../widgets/Cause";
import { ReasonForm } from "../widgets/ReasonForm";
import { errorText, useBriefKeys, useDecide, type BriefProps } from "./briefContext";

/** A run that succeeded but that the code could not call «passed»: a person looks at the checks that have no result
 *  or a warning, ticks each, and accepts — or says what is wrong. The ticked checks go into the audit trail. */
export function AcceptBrief({ item, frame }: BriefProps) {
  const t = useNfT();
  const { t: classic } = useLocale();          // the checklist's sentences are the classic page's (lib/acceptChecklist)
  const { done } = useDecide();
  const issueId = parseItem(item.id)?.id ?? 0;
  const runsQ = useIssueExecutions(issueId);
  const run = runToAccept(runsQ.data);
  const planQ = useFixPlan(run?.fix_plan_id ?? 0);            // the run's own plan, not the issue's current one
  const accept = useAcceptExecution();
  const [ticked, setTicked] = useState<ReadonlySet<number>>(new Set());
  const [form, setForm] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { setTicked(new Set()); }, [run?.id]);

  const runPlan = planQ.data ?? null;
  const vm = run ? acceptVm(run, runPlan) : null;
  const items = run ? checklistItems(runSummary(run, runPlan), classic) : [];   // the boxes: one per check to verify, then the overall one
  const ready = !!run && canAccept(items, ticked);
  const toggle = (k: number) => setTicked((old) => { const next = new Set(old); if (next.has(k)) next.delete(k); else next.add(k); return next; });
  const tickNext = () => { const k = items.findIndex((_, i) => !ticked.has(i)); if (k >= 0) toggle(k); };

  const send = async (decision: "accepted" | "rejected", reason: string) => {
    if (!run) return;
    setError(null);
    try {
      await accept.mutateAsync({ id: run.id, decision, reason, ...(decision === "accepted" ? { confirmed_checks: confirmedIds(items, ticked) } : {}) });
      done(t(decision === "accepted" ? "toast.accepted" : "toast.notAccepted", { ref: item.ref }));
    } catch (e) {
      setError(t("err.failed", { msg: errorText(e) }));
    }
  };
  const acceptNow = () => { if (ready && !accept.isPending) void send("accepted", acceptReason("", items, classic)); };

  useBriefKeys({
    onKey: (key, _e, repeat) => {
      if (form || frame.readOnly || !run) return false;
      if (key === "a") { if (!repeat) acceptNow(); return true; }
      if (key === "x") { tickNext(); return true; }
      if (key === "r") { setError(null); setForm(true); return true; }
      return false;
    },
    onEscape: () => { if (!form) return false; setForm(false); return true; },
  });

  const n = vm?.toVerify.length ?? 0;
  const ask = n > 0 ? t("ask.accept", { n }) : t("ask.accept.none");
  const actions = form ? (
    <ReasonForm label={t("reject.label")} placeholder={t("fail.placeholder")} note={t("accept.rejectNote")} submit={t("act.rejectAccept")}
                busy={accept.isPending} error={error} onCancel={() => setForm(false)} onSubmit={(reason) => void send("rejected", reason)} />
  ) : (
    <>
      <button type="button" className="btn primary" disabled={!ready || accept.isPending} onClick={acceptNow}><span className="t">{t("act.accept")}</span><kbd>A</kbd></button>
      <button type="button" className="btn" disabled={!run || ready} onClick={tickNext}><span className="t">{t("act.tick")}</span><kbd>X</kbd></button>
      <button type="button" className="btn" disabled={!run} onClick={() => { setError(null); setForm(true); }}><span className="t">{t("act.rejectAccept")}</span><kbd>R</kbd></button>
      {error && <p className="note err wide" role="alert">{error}</p>}
    </>
  );
  const box = (k: number, label: string) => frame.readOnly ? null : (
    <button type="button" className="tickbox" role="checkbox" aria-checked={ticked.has(k)} aria-label={label} onClick={() => toggle(k)}>{ticked.has(k) ? "✓" : ""}</button>
  );

  return (
    <BriefFrame item={item} {...frame} ask={ask} actions={actions}>
      {runsQ.isPending ? <StateBlock kind="loading" />
        : runsQ.isError ? <StateBlock kind="failed" failKey="sec.failedLoad" onRetry={() => void runsQ.refetch()} />
        : !vm ? <Message big={t("accept.none")} />
        : (
          <>
            <div className="sec">
              <h2>{t("sec.ran")}</h2>
              <p><Prov code />{t("ran.line", { run: vm.runId, done: vm.stepsDone, total: vm.stepsTotal, duration: vm.duration })}</p>
              <p className="note"><Prov code />{
                vm.planVersion === null ? t("ran.bind.noPlan")
                  : t(vm.matchesApproved === true ? "ran.bind.match" : vm.matchesApproved === false ? "ran.bind.drift" : "ran.bind.unknown",
                      { v: vm.planVersion, hash: vm.hash8 ?? "—" })
              }</p>
              {vm.reason && <p className="note"><Prov code />{t("ran.why", { reason: vm.reason })}</p>}
            </div>
            {vm.failed.length > 0 && (
              <div className="sec">
                <h2>{t("sec.failedChecks")}</h2>
                <ul className="checks">{vm.failed.map((c) => <li key={c.id ?? c.label}><span className="pc">{c.id}</span><span>{c.label}</span><span className="st bad">{t("st.failed")}</span></li>)}</ul>
              </div>
            )}
            {vm.passed.length > 0 && (
              <div className="sec">
                <h2>{t("sec.auto")}</h2>
                <ul className="checks">{vm.passed.map((c) => <li key={c.id ?? c.label}><span className="pc">{c.id}</span><span>{c.label}</span><span className="st ok">{t("st.passed")}</span></li>)}</ul>
              </div>
            )}
            <div className="sec">
              <h2>{t("sec.need")}</h2>
              <ul className="checks">
                {vm.toVerify.map((c, k) => (
                  <li key={c.id ?? c.label}>{box(k, `${t("accept.tick")} ${c.id ?? c.label}`)}<span className="pc">{c.id}</span><span>{c.label}</span><span className="st need">{t(`state.${c.state}`)}</span></li>
                ))}
                {!frame.readOnly && <li>{box(items.length - 1, t("accept.overall"))}<span className="pc" /><span>{t("accept.overall")}</span></li>}
              </ul>
              {!frame.readOnly && <p className="note">{t("accept.note")}</p>}
            </div>
          </>
        )}
    </BriefFrame>
  );
}
