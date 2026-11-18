import { useState } from "react";
import { useAuth } from "@/hooks/useAuth";
import { useFixPlan } from "@/hooks/useFixPlans";
import { useIssueExecutions } from "@/hooks/useIssueExecutions";
import { useNfT } from "../../i18n";
import { whoText } from "../../lib/activity";
import { failedVm, runStepsVm } from "../../lib/briefs/run";
import { utcStamp } from "../../lib/time";
import { Message, StateBlock } from "../../shell/StateBlock";
import { BriefFrame } from "../BriefFrame";
import { AgentAtWork } from "../widgets/AgentAtWork";
import { Prov } from "../widgets/Cause";
import { CauseSection, useCause } from "../widgets/CauseSection";
import { RecordedSteps } from "../../live/LiveSteps";
import { Quote, RunSteps } from "../widgets/RunSteps";
import { useBriefKeys, useDecide, type BriefProps } from "./briefContext";
import { DismissForm, useAgentAsk } from "./shared";

/** A run that ended as a failure: a step failed, a declared check failed, or a person did not accept the result.
 *  The issue is back at «root cause identified» — the next step is a new plan, or a new diagnosis. */
export function FailedBrief({ item, frame }: BriefProps) {
  const t = useNfT();
  const { user } = useAuth();
  const { openPeek } = useDecide();
  const agent = useAgentAsk(item);
  const source = useCause(agent.issueId);
  const runsQ = useIssueExecutions(agent.issueId);
  const run = runsQ.data?.[0] ?? null;                         // the newest run is the one that failed
  const planQ = useFixPlan(run?.fix_plan_id ?? 0);
  const [closing, setClosing] = useState(false);
  const runPlan = planQ.data ?? null;
  const vm = run ? failedVm(run, runPlan) : null;
  // a person stopped it (N9): the same page, in other words — who stopped it, what had been done, what was rolled back
  const stop = vm?.stopped ?? null;
  const stopWho = stop ? whoText(stop.by, user?.email, t) || t("who.someone") : "";

  useBriefKeys({
    onKey: (key, _e, repeat) => {
      if (closing) return false;
      if (key === " " && source.cause?.evidence.length) { openPeek(source.cause.evidence, 0); return true; }
      if (frame.readOnly) return false;
      if (key === "a") { if (!repeat) void agent.ask("plan"); return true; }
      if (key === "m") { if (!repeat) void agent.ask("rca"); return true; }
      if (key === "d") { agent.setError(null); setClosing(true); return true; }
      return false;
    },
    onEscape: () => { if (!closing) return false; setClosing(false); return true; },
  });

  const actions = closing ? <DismissForm item={item} onCancel={() => setClosing(false)} /> : (
    <>
      <button type="button" className="btn primary" disabled={agent.busy} onClick={() => void agent.ask("plan")}><span className="t">{t("act.newPlan")}</span><kbd>A</kbd></button>
      <button type="button" className="btn" disabled={agent.busy} onClick={() => void agent.ask("rca")}><span className="t">{t("act.rediagnose")}</span><kbd>M</kbd></button>
      <span className="spacer" />
      <button type="button" className="btn quiet" onClick={() => setClosing(true)}><span className="t">{t("act.close")}</span><kbd>D</kbd></button>
      {agent.error && <p className="note err wide" role="alert">{agent.error}</p>}
    </>
  );
  return (
    <BriefFrame item={item} {...frame} ask={stop ? t("ask.stopped", { who: stopWho }) : t("ask.failed")} actions={actions}>
      <AgentAtWork lane={agent.lane} now={frame.now} />
      {runsQ.isPending ? <StateBlock kind="loading" />
        : runsQ.isError ? <StateBlock kind="failed" failKey="sec.failedLoad" onRetry={() => void runsQ.refetch()} />
        : !run || !vm ? <Message big={t("resolve.none")} />
        : (
          <>
            <div className="sec">
              <h2>{t(stop ? "sec.stoppedAt" : "sec.failedStep")}</h2>
              <p><Prov code />{stop
                ? t(stop.reported ? "ran.stopped" : "ran.stopped.noSteps", { who: stopWho, t: utcStamp(stop.at), run: vm.runId, n: stop.done, duration: vm.duration })
                : t(`ran.failed.${vm.variant === "step" && vm.failedAt === null ? "other" : vm.variant}`, { run: vm.runId, n: vm.failedAt, duration: vm.duration })}</p>
              {stop?.note && <Quote text={stop.note} cite={t("stop.cite", { by: stopWho, t: utcStamp(stop.at) })} />}
              {vm.error && <p className="note err"><Prov code />{t("ran.error", { msg: vm.error })}</p>}
              {vm.failedChecks.length > 0 && (
                <ul className="checks" style={{ marginTop: 8 }}>
                  {vm.failedChecks.map((c) => <li key={c.id ?? c.label}><span className="pc">{c.id}</span><span>{c.label}</span><span className="st bad">{t("st.failed")}</span></li>)}
                </ul>
              )}
              <details className="more" open={stop ? stop.reported > 0 : vm.variant === "step"}>
                <summary>{t("sec.steps")}</summary>
                <RunSteps steps={runStepsVm(run, runPlan)} />
              </details>
              <RecordedSteps item={item.id} executionId={run.id} now={frame.now} />
            </div>
            {vm.variant === "rejected" && (
              <div className="sec">
                <h2>{t("sec.rejectedAccept")}</h2>
                <Quote text={vm.note || "—"} cite={t("accept.cite", { by: whoText(vm.by, user?.email, t), t: utcStamp(vm.at) })} />
              </div>
            )}
            <div className="sec">
              <h2>{t("sec.stateNow")}</h2>
              <p><Prov code />{vm.rollback.ran > 0 ? t(vm.rollback.failed ? "rollback.failed" : "rollback.ran", { n: vm.rollback.ran, f: vm.rollback.failed })
                : !stop ? t("rollback.none")
                : t(!stop.reported ? "rollback.none.stoppedUnknown" : stop.done ? "rollback.none.stopped" : "rollback.none.stoppedClean", { n: stop.done })}</p>
            </div>
          </>
        )}
      <CauseSection heading={t("sec.itsReason")} source={source} />
    </BriefFrame>
  );
}
