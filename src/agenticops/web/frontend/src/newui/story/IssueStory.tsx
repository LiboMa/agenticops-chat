import { useState } from "react";
import { ApiError } from "@/api/client";
import type { FixExecution, FixPlan } from "@/api/types";
import { useAnomaly } from "@/hooks/useAnomaly";
import { useAuth } from "@/hooks/useAuth";
import { useFixPlans } from "@/hooks/useFixPlans";
import { useIssueExecutions } from "@/hooks/useIssueExecutions";
import { useIssueTimeline } from "@/hooks/useIssueTimeline";
import { useRecheckAt } from "@/hooks/useRecheckAt";
import { useResource } from "@/hooks/useResourceDetail";
import { useSettings } from "@/hooks/useSettings";
import { useLocale } from "@/i18n/LocaleContext";
import { findAction } from "@/lib/approval";
import { factRows, issueFacts, issueSourceLabel } from "@/lib/issueDetail";
import { issueDetailModel, newestFirst } from "@/lib/issueDetailModel";
import { errorText, useBriefKeys, useDecide } from "../decide/briefs/briefContext";
import { AgentAtWork } from "../decide/widgets/AgentAtWork";
import { Cause, Prov } from "../decide/widgets/Cause";
import { PlanSection } from "../decide/widgets/PlanSection";
import { Quote } from "../decide/widgets/RunSteps";
import { useActivity } from "../hooks/useActivity";
import { useReopenIssue } from "../hooks/useIssueDecisions";
import { useFreshRca } from "../hooks/useItemData";
import { useNfT } from "../i18n";
import { agentOn, stoppedOn, whoText } from "../lib/activity";
import { causeVm } from "../lib/briefs/cause";
import { humanVerdict, noteWasCut } from "../lib/briefs/verdict";
import { closure, issueSpine, lastMove, planBasis, planLine, planRewrittenAt, reachedOf, waitKey, waitSince, type IssueStep } from "../lib/story";
import { utcStamp } from "../lib/time";
import { Message, StateBlock } from "../shell/StateBlock";
import { useShell } from "../shell/shellContext";
import { Notes } from "./Notes";
import { BackOnly, FactList, RunList, Spine, StoryHead, WholeRecord, type StepView, type StoryFrame } from "./StoryBits";

const TONE: Record<string, string> = { critical: "crit", high: "warn", medium: "info", low: "info" };
const LONG = 420;

/** One issue from the moment it was found to its acceptance. Where it stands is the classic page's own answer
 *  (lib/issueDetailModel), laid out on six steps; every sentence comes from the issue's own records. */
export function IssueStory({ id, frame }: { id: number; frame: StoryFrame }) {
  const t = useNfT();
  const issueQ = useAnomaly(id);
  // an issue that does not exist: nothing else is asked about it — its timeline would be fetched every 15 seconds for
  // as long as the page stayed open. (While the answer is on its way the rest loads alongside, not after.)
  if (issueQ.error instanceof ApiError && issueQ.error.status === 404) {
    return <article className="story card"><BackOnly frame={frame} /><Message big={t("story.none.big")}><p>{t("story.none.p")}</p></Message></article>;
  }
  return <IssueRecord id={id} frame={frame} />;
}

function IssueRecord({ id, frame }: { id: number; frame: StoryFrame }) {
  const t = useNfT();
  const { t: classic } = useLocale();
  const { user } = useAuth();
  const { notify } = useShell();
  const { openPeek } = useDecide();
  const issueQ = useAnomaly(id);
  const rcaQ = useFreshRca(id);                            // read again each time the page opens: never a diagnosis from a cache
  const plansQ = useFixPlans({ health_issue_id: id });
  const runsQ = useIssueExecutions(id);
  const timeline = useIssueTimeline(id);
  const settings = useSettings();
  const anchor = useResource(issueQ.data?.resource_ref ?? 0);
  const activity = useActivity(null).data;                 // every account: the item is what it is, whatever the scope
  const lane = agentOn(activity, frame.item);
  const halted = stoppedOn(activity, frame.item);          // its last diagnosis ended, the status stayed «investigating»
  const reopen = useReopenIssue(id);
  const [error, setError] = useState<string | null>(null);
  const [wide, setWide] = useState(false);

  const issue = issueQ.data;
  const gate = settings.data?.rca_min_confidence_for_autofix;
  const model = issue ? issueDetailModel({
    issue, rca: rcaQ.data, rcaFailed: rcaQ.isError, threshold: gate,
    plans: plansQ.data, plansFailed: plansQ.isError, executions: runsQ.data, runsFailed: runsQ.isError,
    timeline: timeline.data, timelineFetchedAt: timeline.dataUpdatedAt, timelineFailed: timeline.isError,
    executorTimeout: settings.data?.executor_total_timeout, autoFixEnabled: settings.data?.auto_fix_enabled, now: frame.now,
  }) : null;
  useRecheckAt(model?.recheckAt ?? null, () => { void timeline.refetch(); });

  const cause = causeVm(rcaQ.data, gate);
  useBriefKeys({
    onKey: (key) => {
      if (key === " " && cause?.evidence.length) { openPeek(cause.evidence, 0); return true; }
      return false;
    },
  });

  if (issueQ.isPending) return <article className="story card"><BackOnly frame={frame} /><StateBlock kind="loading" /></article>;
  if (!issue || !model) {
    return (
      <article className="story card">
        <BackOnly frame={frame} />
        <StateBlock kind="failed" failKey="story.failed.p" onRetry={() => void issueQ.refetch()} />
      </article>
    );
  }

  const rca = rcaQ.data ?? null;
  const plan = model.plan;
  const runs = newestFirst(runsQ.data);
  const latest = model.latestRun;
  const sub = model.phase.sub;
  const steps = issueSpine(sub, reachedOf(rca, plan, runsQ.data));
  const who = (actor: string | null | undefined) => whoText(actor, user?.email, t);
  const planOf = (run: FixExecution): FixPlan | null => plansQ.data?.find((p) => p.id === run.fix_plan_id) ?? null;
  const verdict = humanVerdict(timeline.data, rca?.id);
  const gone = issue.status === "dismissed" ? closure(timeline.data) : null;
  const done = issue.status === "resolved" ? lastMove(timeline.data, "resolved") : null;
  const closed = issue.status === "resolved" || issue.status === "dismissed";
  // an agent's work that outlived its own limit is not «an agent is on it»
  const wait = waitKey(model.phase.waitingFor, !!frame.mine, !activity ? null : !lane ? false : lane.overdue ? "overdue" : true, closed);
  const stateName = (status: string) => (t(`state.issue.${status}`) === `state.issue.${status}` ? status : t(`state.issue.${status}`));
  const rewrittenAt = plan ? planRewrittenAt(timeline.data, plan.id) : null;
  const source = issueSourceLabel(issue.source, classic);
  const closedAt = steps.find((s) => s.state === "closed")?.id ?? null;
  // why a diagnosis did not go on to a plan by itself: the classic page's own reason (the gate, or the second model)
  const why = sub === "needsReview" && model.reason && "key" in model.reason ? model.reason : null;

  const line = plan ? planLine(plan) : null;
  const basis = plan ? planBasis(plan, rca) : "unknown";
  const body: Record<IssueStep, React.ReactNode> = {
    found: (
      <>
        <p><Prov code />{t("story.found.source", { source })}{issue.occurrence_count > 1 ? t("story.found.seen", { n: issue.occurrence_count }) : ""}</p>
        {issue.description && (
          <>
            <p className={issue.description.length > LONG && !wide ? "clamp" : undefined} style={{ whiteSpace: "pre-wrap" }}>{issue.description}</p>
            {issue.description.length > LONG && <p><button type="button" className="more-btn" aria-expanded={wide} onClick={() => setWide(!wide)}>{t(wide ? "cause.less" : "cause.more")}</button></p>}
          </>
        )}
      </>
    ),
    rca: (
      <>
        {lane?.kind === "diagnosis" && <AgentAtWork lane={lane} now={frame.now} />}
        {halted && <p><Prov code />{t(halted.since ? "story.rca.stopped" : "story.rca.stopped.unknown", { t: utcStamp(halted.since, frame.now) })}</p>}
        {rcaQ.isPending ? <div className="skel" style={{ height: 54, marginTop: 6 }} />
          : rcaQ.isError ? <p className="note err">{t("sec.failedLoad")}</p>
          : !cause ? (lane?.kind === "diagnosis" ? null : <p>{t("story.rca.none")}</p>)
          : <div className="box"><Cause cause={cause} /></div>}
        {verdict?.verdict === "incorrect" && (
          <>
            <p>{t("story.rca.wrong", { by: who(verdict.by) })}</p>
            {verdict.note && <Quote text={verdict.note + (noteWasCut(verdict.note) ? t("verdict.cut") : "")} cite={`${who(verdict.by)}　${utcStamp(verdict.at, frame.now)} UTC`} />}
          </>
        )}
        {verdict?.verdict === "correct" && <p>{t("story.rca.confirmed", { by: who(verdict.by) })}</p>}
        {why?.key === "workitem.reason.rcaRefuted" && <p><Prov code />{t("story.rca.needsCall")}</p>}
        {why?.key === "workitem.reason.rcaBelowGate" && <p><Prov code />{t("story.rca.belowGate", { conf: why.params?.conf, gate: why.params?.threshold })}</p>}
      </>
    ),
    plan: (
      <>
        {lane?.kind === "plan" && <AgentAtWork lane={lane} now={frame.now} />}
        {plansQ.isPending ? <div className="skel" style={{ height: 40, marginTop: 6 }} />
          : plansQ.isError && !plansQ.data ? <p className="note err">{t("sec.failedLoad")}</p>
          : !plan || !line ? (lane?.kind === "plan" ? null : <p>{t("story.plan.none")}</p>)
          : (
            <>
              <p>
                <Prov code />
                {t(line.writes === null ? "story.plan.summary" : "story.plan.summary.tiers",
                   { label: t("plan.label.fix"), v: line.version, hash: line.hash8 ?? "—", n: line.steps, w: line.writes })}
                {line.unclear > 0 ? t("story.plan.unclear", { u: line.unclear }) : ""}
              </p>
              {basis === "older" && <p><Prov code />{t("plan.basis.older")}</p>}
              {basis === "rewritten" && (
                <p><Prov code />{t(rewrittenAt ? "plan.basis.rewrittenAt" : "plan.basis.rewritten",
                                   { t: utcStamp(plan.created_at, frame.now), at: utcStamp(rewrittenAt, frame.now) })}</p>
              )}
              {model.otherPlans.length > 0 && <p>{t("story.plan.count", { n: model.otherPlans.length + 1 })}</p>}
              <details className="more"><summary>{t("story.plan.steps")}</summary><PlanSection plan={plan} heading={t("sec.plan")} kind="fix" /></details>
              {plan.status === "rejected" && (
                <>
                  <p>{t("story.plan.rejected", { by: who(plan.rejected_by) || "—" })}</p>
                  {plan.rejection_reason && <Quote text={plan.rejection_reason} cite={`${who(plan.rejected_by)}　${utcStamp(plan.rejected_at, frame.now)} UTC`} />}
                </>
              )}
            </>
          )}
      </>
    ),
    approve: plan?.approved_at && plan.status !== "rejected"
      ? <p><Prov code />{t("story.approve.done", { by: who(plan.approved_by) || "—", t: utcStamp(plan.approved_at, frame.now) })}</p>
      : sub === "awaitingApproval" ? <p>{t(frame.mine ? "story.approve.you" : "story.approve.person")}</p> : null,
    run: (
      <>
        {lane?.kind === "run" && <p className="back" role="status">{t("story.run.running")}</p>}
        {sub === "notQueued" && <p><Prov code />{t("story.run.notStarted")}</p>}
        {(sub === "checkingRun" || sub === "runStateUnavailable") && <p>{t("story.run.checking")}</p>}
        {sub === "executing" && model.autoRun && lane?.kind !== "run" && <p><Prov code />{t("story.run.started", { t: utcStamp(model.autoRun.startedAt, frame.now) })}</p>}
        {runsQ.isPending ? <div className="skel" style={{ height: 40, marginTop: 6 }} />
          : runsQ.isError && !runsQ.data ? <p className="note err">{t("sec.failedLoad")}</p>
          : <RunList runs={runs} planOf={planOf} now={frame.now} />}
      </>
    ),
    accept: (
      <>
        {sub === "awaitingAcceptance" && <p><Prov code />{latest?.verification_reason ? t("story.accept.need", { reason: latest.verification_reason }) : t("story.accept.needPlain")}</p>}
        {sub === "passed" && <p><Prov code />{t("story.accept.passed")}</p>}
        {sub === "unverified" && <p><Prov code />{t("story.accept.noVerdict")}</p>}
        {sub === "resolved" && <p><Prov code />{t("story.resolved", { t: utcStamp(issue.resolved_at, frame.now) })}</p>}
        {/* it was closed without running a fix: say from where, so «resolved» is not read as «fixed» */}
        {sub === "resolved" && done?.from && done.from !== "fix_executed" && <p><Prov code />{t("story.resolved.from", { from: stateName(done.from) })}</p>}
        {sub === "resolved" && done?.note && <Quote text={done.note} cite={`${who(done.by)}　${utcStamp(done.at, frame.now)} UTC`} />}
      </>
    ),
  };
  const heads: Record<IssueStep, { at?: string | null; who?: string | null }> = {
    found: { at: issue.detected_at, who: source },
    rca: { at: rca?.created_at, who: rca ? [t("by.rca"), rca.model_id].filter(Boolean).join(" · ") : null },
    plan: { at: basis === "rewritten" ? null : plan?.created_at, who: plan ? t("by.sre") : null },   // a rewritten plan's creation time is not when it was written
    approve: { at: plan?.approved_at, who: plan?.approved_at ? who(plan.approved_by) : null },
    run: { at: latest?.started_at ?? latest?.created_at, who: latest?.executed_by },
    // resolved: who marked it, from the timeline (the run's acceptance, if any, stands with its run)
    accept: sub === "resolved" ? { at: issue.resolved_at, who: who(done?.by) || null }
      : { at: latest?.accepted_at, who: who(latest?.accepted_by) || null },
  };
  const view: StepView[] = steps.map((s) => ({
    ...s, ...heads[s.id],
    body: (
      <>
        {body[s.id]}
        {s.id === closedAt && (
          <>
            <p><Prov code />{t("story.dismissed")}</p>
            {/* only what the person typed is quoted under their name — never the code's own reason */}
            {gone?.note && <Quote text={gone.note} cite={t("story.dismissed.cite", { by: who(gone.by), t: utcStamp(gone.at, frame.now) })} />}
          </>
        )}
      </>
    ),
  }));

  const canReopen = issue.status === "dismissed" && !frame.readOnly;
  const state = stateName(issue.status);
  return (
    <>
      <article className="story card" aria-label={t("story.label")}>
        <StoryHead frame={frame} refText={`I#${id}`} tone={TONE[issue.severity] ?? ""} sev={t(`sev.${issue.severity}`)} title={issue.title}
                   state={state} wait={wait} stuck={!!lane?.overdue} liveLane={(lane ?? halted)?.id}
                   since={waitSince(wait, issue.waiting_since, lane?.since)}
                   place={[issue.account_name, issueFacts(issue).region].filter(Boolean).join("　")}>
          {canReopen && (
            <p style={{ margin: "10px 0 0" }}>
              <button type="button" className="btn sm" disabled={reopen.isPending} onClick={async () => {
                setError(null);
                try { await reopen.mutateAsync(); notify(t("toast.reopened", { ref: `I#${id}` })); }
                catch (e) { setError(t("err.failed", { msg: errorText(e) })); }
              }}><span className="t">{t("act.reopen")}</span></button>
            </p>
          )}
          {error && <p className="note err" role="alert">{error}</p>}
        </StoryHead>
        <Spine steps={view} now={frame.now} />
        <WholeRecord events={timeline.data} failed={timeline.isError} now={frame.now} />
      </article>
      <aside className="facts card">
        <FactList status={issue.status} classicTo={`/app/issues/${id}`} now={frame.now} rows={[
          ...factRows(issue, { name: anchor.data?.resource_name ?? null, type: anchor.data?.resource_type ?? null }, classic, rca)
            .map((r) => ({ label: classic(r.labelKey), value: r.value, kind: r.kind, href: r.href })),
          ...(issue.occurrence_count > 1 ? [{ label: t("fact.seen"), value: `× ${issue.occurrence_count}` }] : []),
        ]} />
        <Notes issueId={id} events={timeline.data} failed={timeline.isError} canNote={!!findAction(issue.available_actions, "note")?.allowed} now={frame.now} />
      </aside>
    </>
  );
}
