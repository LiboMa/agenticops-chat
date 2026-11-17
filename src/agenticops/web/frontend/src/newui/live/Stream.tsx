import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import type { FixExecution, FixPlan, PipelineEvent } from "@/api/types";
import { useAnomalyRca } from "@/hooks/useAnomalyRca";
import { useAuth } from "@/hooks/useAuth";
import { useChange } from "@/hooks/useChanges";
import { useChangeTimeline } from "@/hooks/useChangeTimeline";
import { useFixPlan, useFixPlans } from "@/hooks/useFixPlans";
import { useIssueExecutions } from "@/hooks/useIssueExecutions";
import { useIssueTimeline } from "@/hooks/useIssueTimeline";
import { useSettings } from "@/hooks/useSettings";
import { useLocale } from "@/i18n/LocaleContext";
import { toActivity } from "@/lib/activity";
import { safeRoute, type AttentionItem } from "@/lib/attention";
import { activeChangePlan, toPipelineEvents } from "@/lib/changeDetail";
import { parseItem } from "@/lib/inbox";
import { currentFixPlan } from "@/lib/issuePhases";
import { fillPlaceholders } from "@/lib/placeholders";
import { Cause, Prov } from "../decide/widgets/Cause";
import { HoldButton } from "../decide/widgets/HoldButton";
import { PlanSection } from "../decide/widgets/PlanSection";
import { Steps } from "../decide/widgets/Steps";
import { useNfT } from "../i18n";
import { whoText } from "../lib/activity";
import { causeVm } from "../lib/briefs/cause";
import { requestVm } from "../lib/briefs/change";
import { stepsVm } from "../lib/briefs/plan";
import type { LaneView, StopState } from "../lib/live";
import { utcStamp } from "../lib/time";
import { RunList } from "../story/StoryBits";
import { LANE_CLASS, agentName, laneState } from "./Lanes";

const RECORD_MAX = 8;

/** The newest few entries of the item's timeline, oldest first — what is on record about it, in the classic page's
 *  own sentences. The agents' steps are not recorded while they work; this is. */
function Record({ events, failed, now }: { events: PipelineEvent[] | undefined; failed: boolean; now: number }) {
  const t = useNfT();
  const { t: classic } = useLocale();
  if (events === undefined) return failed ? <p className="note err">{t("sec.failedLoad")}</p> : <div className="skel" style={{ height: 60, marginTop: 14 }} />;
  const entries = toActivity(events).slice(-RECORD_MAX);
  return (
    <div className="sec">
      <h2>{t("live.record")}</h2>
      {entries.length === 0 ? <p className="note">{t("story.all.none")}</p> : (
        <ol className="lsteps">
          {entries.map((e, i) => (
            <li key={i} className="done">
              <span className="say">{fillPlaceholders(classic(e.labelKey), e.labelParams)}{e.count > 1 ? ` ×${e.count}` : ""}{e.summary ? ` — ${e.summary}` : ""}</span>
              <span className="cmd">{utcStamp(e.ts, now)} UTC　{e.actor}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

const Block = ({ heading, children }: { heading: string; children: ReactNode }) => <div className="sec"><h2>{heading}</h2>{children}</div>;
const Loading = () => <div className="skel" style={{ height: 54 }} />;

/** The plan a run in flight is executing. The executor writes each step's result only when the run ends. */
function PlanInFlight({ plan, pending, failed }: { plan: FixPlan | null; pending: boolean; failed: boolean }) {
  const t = useNfT();
  return (
    <Block heading={t("live.plan")}>
      {pending ? <Loading /> : failed ? <p className="note err">{t("sec.failedLoad")}</p>
        : !plan ? <p className="note">{t("live.plan.none")}</p>
        : <><Steps steps={stepsVm(plan)} /><p className="note"><Prov code />{t("live.noSteps.run")}</p></>}
    </Block>
  );
}

function IssueLane({ lane, issueId, now }: { lane: LaneView; issueId: number; now: number }) {
  const t = useNfT();
  const timeline = useIssueTimeline(issueId);
  return (
    <>
      {lane.group === "running" && (lane.kind === "diagnosis" || lane.kind === "plan") && <p className="note"><Prov code />{t("live.noSteps.agent")}</p>}
      {lane.stopped && <p className="note">{t("live.stopped.next")}</p>}
      {lane.group === "running" && lane.kind === "run" && <RunningRun issueId={issueId} />}
      {lane.group === "recent" && lane.kind === "run" && lane.row !== null && <EndedRun issueId={issueId} runId={lane.row} now={now} />}
      {lane.group === "recent" && lane.kind === "diagnosis" && lane.row !== null && <EndedDiagnosis issueId={issueId} rcaId={lane.row} />}
      {lane.group === "recent" && lane.kind === "plan" && lane.row !== null && <EndedPlan planId={lane.row} />}
      <Record events={timeline.data} failed={timeline.isError} now={now} />
    </>
  );
}

function RunningRun({ issueId }: { issueId: number }) {
  const plans = useFixPlans({ health_issue_id: issueId });
  return <PlanInFlight plan={currentFixPlan(plans.data)} pending={plans.isPending} failed={plans.isError && !plans.data} />;
}

function EndedRun({ issueId, runId, now }: { issueId: number; runId: number; now: number }) {
  const t = useNfT();
  const runs = useIssueExecutions(issueId);
  const plans = useFixPlans({ health_issue_id: issueId });
  const run = runs.data?.find((r) => r.id === runId) ?? null;
  const planOf = (r: FixExecution): FixPlan | null => plans.data?.find((p) => p.id === r.fix_plan_id) ?? null;
  return (
    <Block heading={t("live.result")}>
      {runs.isPending ? <Loading /> : runs.isError && !runs.data ? <p className="note err">{t("sec.failedLoad")}</p>
        : !run ? <p className="note">{t("live.result.none")}</p> : <RunList runs={[run]} planOf={planOf} now={now} />}
    </Block>
  );
}

function EndedDiagnosis({ issueId, rcaId }: { issueId: number; rcaId: number }) {
  const t = useNfT();
  const rcaQ = useAnomalyRca(issueId);
  const gate = useSettings().data?.rca_min_confidence_for_autofix;
  const cause = causeVm(rcaQ.data, gate);
  return (
    <Block heading={t("live.result")}>
      {rcaQ.isPending ? <Loading /> : rcaQ.isError ? <p className="note err">{t("sec.failedLoad")}</p>
        : !cause ? <p className="note">{t("cause.none")}</p>
        : (
          <>
            {rcaQ.data && rcaQ.data.id !== rcaId && <p className="note"><Prov code />{t("live.result.newerRca")}</p>}
            <Cause cause={cause} />
          </>
        )}
    </Block>
  );
}

function EndedPlan({ planId }: { planId: number }) {
  const t = useNfT();
  const planQ = useFixPlan(planId);
  return planQ.isPending ? <Block heading={t("live.result")}><Loading /></Block>
    : planQ.isError || !planQ.data ? <Block heading={t("live.result")}><p className="note err">{t("sec.failedLoad")}</p></Block>
    : <PlanSection plan={planQ.data} heading={t("live.result")} kind="fix" />;
}

function ChangeLane({ lane, changeId, now }: { lane: LaneView; changeId: number; now: number }) {
  const t = useNfT();
  const q = useChange(changeId);
  const timeline = useChangeTimeline(changeId, q.data?.status);
  const cr = q.data;
  return (
    <>
      {lane.kind === "change_review" && (
        <>
          <p className="note"><Prov code />{t("live.noSteps.review")}</p>
          <Block heading={t("sec.request")}>
            {q.isPending ? <Loading /> : !cr ? <p className="note err">{t("sec.failedLoad")}</p> : <p style={{ whiteSpace: "pre-wrap" }}>{requestVm(cr).text}</p>}
          </Block>
        </>
      )}
      {lane.kind === "change_run" && <PlanInFlight plan={cr ? activeChangePlan(cr.plans) : null} pending={q.isPending} failed={q.isError && !cr} />}
      <Record events={timeline.data ? toPipelineEvents(timeline.data) : undefined} failed={timeline.isError} now={now} />
    </>
  );
}

/** Stopping the lane's run (N9). `state` = lib/live.stopState; `offered` = this person is offered the control (not
 *  a read-only account — who may stop is the server's answer, and its refusal is `error`). */
export interface StopControl {
  state: NonNullable<StopState>; offered: boolean; busy: boolean; holding: boolean; hint: boolean; error: string | null;
  onDown: (key?: string) => void; onUp: () => void; onCancel: () => void;
}

/** The opened lane: who is doing what, since when and how the server knows — then what there is to show of it. */
export function Stream({ lane, moved, mine, now, stop, onBack, onStory, onDecide }: {
  lane: LaneView;
  /** the address named a lane that has ended; this is what it left behind */
  moved: boolean;
  /** the lane's item as it stands on this person's own list; null = it does not wait on them */
  mine: AttentionItem | null;
  /** null = this lane is not a run that can be stopped, and nobody stopped it */
  stop: StopControl | null;
  now: number; onBack: () => void; onStory: () => void; onDecide: () => void;
}) {
  const t = useNfT();
  const { user } = useAuth();
  const target = parseItem(lane.item);
  const classicRoute = safeRoute(lane.route ?? "");
  const basis = (lane.group !== "running" && lane.group !== "stalled") || !lane.basis ? null
    : t(`live.basis.${lane.basis}`) === `live.basis.${lane.basis}` ? null : t(`live.basis.${lane.basis}`, { who: whoText(lane.requestedBy, user?.email, t) });
  return (
    <>
      <button type="button" className="back narrow-only" onClick={onBack}>← {t("live.back")}</button>
      <div className="meta">
        <span className="ag">{agentName(lane.agent, t)}</span>
        <span className={`st ${LANE_CLASS[lane.tone]}`}>{laneState(lane, now, t)}</span>
        {lane.ref && <span className="ref">{lane.ref}</span>}
        {target && <button type="button" className="story-link" style={{ marginLeft: "auto" }} onClick={onStory}>{t("act.story")}<kbd>↵</kbd></button>}
      </div>
      <h1>{lane.title}</h1>
      {moved && <p className="back" role="status">{t("live.moved")}</p>}
      {basis && (
        <p className={lane.stopped ? "note err" : "note"}>
          <Prov code />{basis}{lane.at ? `　${t(lane.stopped ? "live.stoppedAt" : "live.since", { t: utcStamp(lane.at, now) })}` : lane.stopped ? "" : `　${t("lane.sinceUnknown")}`}
        </p>
      )}
      {lane.overdue && !lane.stopped && <p className="note err"><Prov code />{t("live.overdue")}</p>}
      {stop?.state === "stopping" && (
        <p className="note err" role="status">
          <Prov code />{t("live.stoppingNote", { who: whoText(lane.execution?.stopRequestedBy, user?.email, t) || t("who.someone"),
                                                 t: utcStamp(lane.execution?.stopRequestedAt ?? null, now) })}
        </p>
      )}
      {stop?.state === "can" && stop.offered && <p className="note">{t("live.noSteer")}</p>}
      {lane.group === "upcoming" && <p className="note"><Prov code />{t("live.upcoming", { t: utcStamp(lane.at, now) })}</p>}
      {lane.group === "recent" && !target && <p className="note"><Prov code />{t("live.ended", { t: utcStamp(lane.at, now), outcome: t(`outcome.${lane.outcome ?? "done"}`) })}</p>}
      {target?.kind === "issue" && <IssueLane key={lane.id} lane={lane} issueId={target.id} now={now} />}
      {target?.kind === "change" && <ChangeLane key={lane.id} lane={lane} changeId={target.id} now={now} />}
      <div className="controls">
        {stop?.state === "can" && stop.offered && (
          <HoldButton danger label={t("live.stop")} disabled={stop.busy} holding={stop.holding} hint={stop.hint}
                      onDown={stop.onDown} onUp={stop.onUp} onCancel={stop.onCancel} />
        )}
        {target && mine && <button type="button" className="btn primary" onClick={onDecide}><span className="t">{t("story.goDecide")}</span></button>}
        {target && <button type="button" className="btn" onClick={onStory}><span className="t">{t("live.openStory")}</span><kbd>↵</kbd></button>}
        {!target && classicRoute && <Link className="btn" to={classicRoute}><span className="t">{t("live.openClassic")}</span></Link>}
        {stop?.error && <p className="note err wide" role="alert">{stop.error}</p>}
      </div>
    </>
  );
}
