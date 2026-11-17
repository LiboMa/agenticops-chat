import { ApiError } from "@/api/client";
import type { FixExecution, FixPlan } from "@/api/types";
import { useAccounts } from "@/hooks/useAccounts";
import { useAuth } from "@/hooks/useAuth";
import { useChange } from "@/hooks/useChanges";
import { useChangeTimeline } from "@/hooks/useChangeTimeline";
import { useLocale } from "@/i18n/LocaleContext";
import { policyActionLabel, sourceLabel, toPipelineEvents, verdictLabel } from "@/lib/changeDetail";
import { changeDetailModel } from "@/lib/changeDetailModel";
import { AgentAtWork } from "../decide/widgets/AgentAtWork";
import { Prov } from "../decide/widgets/Cause";
import { PlanSection } from "../decide/widgets/PlanSection";
import { Quote } from "../decide/widgets/RunSteps";
import { Steps } from "../decide/widgets/Steps";
import { useActivity } from "../hooks/useActivity";
import { useNfT } from "../i18n";
import { agentOn, whoText } from "../lib/activity";
import { requestVm } from "../lib/briefs/change";
import { changeSpine, planLine, runLine, waitKey, waitSince, type ChangeStep } from "../lib/story";
import { utcStamp } from "../lib/time";
import { Message, StateBlock } from "../shell/StateBlock";
import { BackOnly, FactList, RunList, Spine, StoryHead, WholeRecord, type FactView, type StepView, type StoryFrame } from "./StoryBits";

const TONE: Record<string, string> = { L3: "crit", L2: "warn", L1: "info", L0: "info" };

/** One change request from the request to its acceptance. Where it stands is the classic page's own answer
 *  (lib/changeDetailModel), laid out on six steps; every sentence comes from the request's own records. */
export function ChangeStory({ id, frame }: { id: number; frame: StoryFrame }) {
  const t = useNfT();
  const q = useChange(id);
  // a change that does not exist: its timeline is not asked for every ten seconds
  if (q.error instanceof ApiError && q.error.status === 404) {
    return <article className="story card"><BackOnly frame={frame} /><Message big={t("story.none.big")}><p>{t("story.none.p")}</p></Message></article>;
  }
  return <ChangeRecord id={id} frame={frame} />;
}

function ChangeRecord({ id, frame }: { id: number; frame: StoryFrame }) {
  const t = useNfT();
  const { t: classic } = useLocale();
  const { user } = useAuth();
  const q = useChange(id);
  const accounts = useAccounts();
  const timeline = useChangeTimeline(id, q.data?.status);
  const activity = useActivity(null).data;                 // every account: the item is what it is, whatever the scope
  const lane = agentOn(activity, frame.item);

  if (q.isPending) return <article className="story card"><BackOnly frame={frame} /><StateBlock kind="loading" /></article>;
  const cr = q.data;
  if (!cr) {
    return (
      <article className="story card">
        <BackOnly frame={frame} />
        <StateBlock kind="failed" failKey="story.failed.p" onRetry={() => void q.refetch()} />
      </article>
    );
  }

  const model = changeDetailModel(cr);
  const sub = model.phase.sub;
  const plan = model.plan;
  const latest = model.latestRun;
  // «failed» with a run that itself ended well = a person judged it failed when accepting it
  const failedAtAcceptance = sub === "failed" && !!latest && !runLine(latest, null).bad && !!latest.completed_at;
  const steps = changeSpine(sub, model.phase.current, !!cr.approved_at, failedAtAcceptance);
  const who = (actor: string | null | undefined) => whoText(actor, user?.email, t);
  const planOf = (run: FixExecution): FixPlan | null => cr.plans.find((p) => p.id === run.fix_plan_id) ?? null;
  const closed = ["completed", "failed", "rolled_back", "rejected", "cancelled"].includes(cr.status);
  const wait = waitKey(model.phase.waitingFor, !!frame.mine, !activity ? null : !lane ? false : lane.overdue ? "overdue" : true, closed);
  const closedAt = steps.find((s) => s.state === "closed")?.id ?? null;
  const r = requestVm(cr);
  const line = plan ? planLine(plan) : null;
  const region = cr.target_resources.find((x) => x.region)?.region ?? null;
  const accountName = accounts.data?.find((a) => a.id === cr.account_id)?.name ?? null;

  const body: Record<ChangeStep, React.ReactNode> = {
    request: (
      <>
        <p style={{ whiteSpace: "pre-wrap" }}>{r.text}</p>
        {r.why && <p>{t("request.why", { why: r.why })}</p>}
        <p>
          <Prov code />
          {r.targets.length ? t("request.targets", { targets: r.targets.map((x) => `${x.type} ${x.id}${x.region ? ` (${x.region})` : ""}`).join("、") }) : t("request.noTargets")}
          {r.emergency ? `　${t("request.emergency")}` : ""}
        </p>
        {r.unresolved.length > 0 && <p className="note err">{t("request.unresolved", { hints: r.unresolved.join("、") })}</p>}
        {r.proposed.length > 0 && <details className="more"><summary>{t("sec.proposed")}</summary><Steps steps={r.proposed} /></details>}
        {sub === "draft" && <p>{t("story.request.draft")}</p>}
      </>
    ),
    review: (
      <>
        {lane?.kind === "change_review" && <AgentAtWork lane={lane} now={frame.now} />}
        {cr.review_verdict && <p><Prov code={false} />{t("story.change.review.verdict", { v: verdictLabel(cr.review_verdict, classic) })}{cr.risk_level ? `　${t("review.risk", { risk: cr.risk_level })}` : ""}</p>}
        {sub === "needsClarification" && <p>{t(cr.review_reasons.length ? "story.change.review.stuck" : "story.change.review.stuckPlain", { n: cr.review_reasons.length })}</p>}
        {cr.review_reasons.length > 0 && <ul className="reasons">{cr.review_reasons.map((x, k) => <li key={k}><Prov code={false} />{x}</li>)}</ul>}
        {cr.policy_rule && <p className="note"><Prov code />{t("review.policy", { rule: cr.policy_rule, action: policyActionLabel(cr.policy_action ?? "", classic) })}</p>}
      </>
    ),
    plan: !plan || !line ? <p>{t("story.plan.none")}</p> : (
      <>
        <p>
          <Prov code />
          {t(line.writes === null ? "story.plan.summary" : "story.plan.summary.tiers",
             { label: t("plan.label.change"), v: line.version, hash: line.hash8 ?? "—", n: line.steps, w: line.writes })}
          {line.unclear > 0 ? t("story.plan.unclear", { u: line.unclear }) : ""}
        </p>
        <details className="more"><summary>{t("story.plan.steps")}</summary><PlanSection plan={plan} heading={t("sec.plan")} kind="change" /></details>
      </>
    ),
    approve: cr.approved_at ? (
      <>
        <p><Prov code />{t("story.approve.done", { by: who(cr.approved_by) || "—", t: utcStamp(cr.approved_at, frame.now) })}</p>
        {cr.approval_reason && <Quote text={cr.approval_reason} cite={`${who(cr.approved_by)}　${utcStamp(cr.approved_at, frame.now)} UTC`} />}
      </>
    ) : sub === "awaitingApproval" ? <p>{t(frame.mine ? "story.approve.you" : "story.approve.person")}</p> : null,
    run: (
      <>
        {lane?.kind === "change_run" && <p className="back" role="status">{t("story.run.running")}</p>}
        {sub === "notQueued" && <p><Prov code />{t("story.run.notStarted")}</p>}
        {sub === "failed" && <p><Prov code />{t("story.change.failed")}</p>}
        {sub === "rolledBack" && <p><Prov code />{t("story.change.rolledBack")}</p>}
        <RunList runs={model.runs} planOf={planOf} now={frame.now} />
      </>
    ),
    accept: (
      <>
        {sub === "awaitingAcceptance" && <p><Prov code />{cr.needs_review_reason ? t("story.accept.need", { reason: cr.needs_review_reason }) : t("story.accept.needPlain")}</p>}
        {sub === "completed" && <p><Prov code />{t("story.change.completed", { t: utcStamp(cr.closed_at, frame.now) })}</p>}
      </>
    ),
  };
  const heads: Record<ChangeStep, { at?: string | null; who?: string | null }> = {
    request: { at: cr.requested_at ?? cr.created_at, who: who(cr.requested_by) },
    review: { at: cr.reviewed_at, who: cr.reviewed_by },
    plan: { at: plan?.created_at, who: plan ? t("by.sre") : null },
    approve: { at: cr.approved_at, who: cr.approved_at ? who(cr.approved_by) : null },
    run: { at: latest?.started_at ?? latest?.created_at, who: latest?.executed_by },
    accept: { at: sub === "completed" ? cr.closed_at : latest?.accepted_at, who: who(latest?.accepted_by) || null },
  };
  const view: StepView[] = steps.map((s) => ({
    ...s, ...heads[s.id],
    body: (
      <>
        {body[s.id]}
        {s.id === closedAt && (
          <>
            <p><Prov code />{t(`story.change.closed.${sub === "cancelled" ? "cancelled" : "rejected"}`)}</p>
            {cr.rejection_reason && <Quote text={cr.rejection_reason} cite={`${who(cr.rejected_by)}　${utcStamp(cr.rejected_at, frame.now)} UTC`} />}
          </>
        )}
      </>
    ),
  }));

  const rows: FactView[] = [
    ...(accountName ? [{ label: t("fact.account"), value: accountName }] : []),
    ...(cr.risk_level ? [{ label: t("fact.risk"), value: cr.risk_level }] : []),
    ...(cr.effective_change_type ? [{ label: t("fact.changeType"), value: cr.effective_change_type }] : []),
    ...(cr.action_type ? [{ label: t("fact.action"), value: cr.action_type }] : []),
    { label: t("fact.requester"), value: who(cr.requested_by) },
    ...(sourceLabel(cr.source, classic) ? [{ label: t("fact.source"), value: sourceLabel(cr.source, classic)! }] : []),
    ...(cr.requested_at ?? cr.created_at ? [{ label: t("fact.requested"), value: (cr.requested_at ?? cr.created_at)!, kind: "date" as const }] : []),
    ...(cr.trace_id ? [{ label: t("fact.trace"), value: cr.trace_id, kind: "mono" as const }] : []),
  ];
  const state = t(`state.change.${cr.status}`) === `state.change.${cr.status}` ? cr.status : t(`state.change.${cr.status}`);
  return (
    <>
      <article className="story card" aria-label={t("story.label")}>
        <StoryHead frame={frame} refText={`C#${id}`} tone={TONE[cr.risk_level ?? ""] ?? ""}
                   sev={`${t("sev.change")}${cr.risk_level ? ` ${cr.risk_level}` : ""}`} title={cr.title}
                   state={state} wait={wait} stuck={!!lane?.overdue} liveLane={lane?.id}
                   since={waitSince(wait, cr.waiting_since, lane?.since)} place={[accountName, region].filter(Boolean).join("　")} />
        <Spine steps={view} now={frame.now} />
        <WholeRecord events={timeline.data ? toPipelineEvents(timeline.data) : undefined} failed={timeline.isError} now={frame.now} />
      </article>
      <aside className="facts card">
        <FactList status={cr.status} rows={rows} classicTo={`/app/changes/${id}`} now={frame.now} />
      </aside>
    </>
  );
}
