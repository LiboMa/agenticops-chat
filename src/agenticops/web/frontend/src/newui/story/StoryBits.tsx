import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import type { FixExecution, FixPlan, PipelineEvent } from "@/api/types";
import { useAuth } from "@/hooks/useAuth";
import { useLocale } from "@/i18n/LocaleContext";
import { toActivity } from "@/lib/activity";
import type { AttentionItem } from "@/lib/attention";
import { executionStatusLabel } from "@/lib/issueDetail";
import { fillPlaceholders } from "@/lib/placeholders";
import { Prov } from "../decide/widgets/Cause";
import { Quote, RunSteps, StopLine } from "../decide/widgets/RunSteps";
import { RecordedSteps } from "../live/LiveSteps";
import { useNfT } from "../i18n";
import { whoText } from "../lib/activity";
import { briefKind } from "../lib/briefKind";
import { lanePath } from "../lib/live";
import { failedVm, runStepsVm, stopOf } from "../lib/briefs/run";
import { waitedParts } from "../lib/queue";
import { runLine, type SpineState, type WaitKey } from "../lib/story";
import { utcStamp } from "../lib/time";
import { CLASSIC_EXIT } from "@/lib/shellRoutes";

/** What the page of one item is given, whichever kind it is. */
export interface StoryFrame {
  /** "I12" / "C3" */
  item: string;
  /** the item as it stands on this person's own list; null = it does not wait on them */
  mine: AttentionItem | null;
  now: number;
  readOnly: boolean;
  /** the lens the page was opened from: its way back */
  from: "decide" | "live" | "world" | "items";
  onBack: () => void;
  onDecide: () => void;
  /** «ask the agent about this item»: the conversation's address (N19); null when the address is no item */
  askTo?: string | null;
}

/** The top of the page: the way back, which item, where it stands and who it waits on — and, when it waits on this
 *  person, what is asked of them and the way to the decision. */
export function StoryHead({ frame, refText, tone, sev, title, state, wait, stuck, liveLane, since, place, children }: {
  frame: StoryFrame; refText: string; tone: string; sev: string; title: string;
  /** the lane of «现场» where this item is being worked on right now, if any */
  liveLane?: string | null;
  /** the status in words */
  state: string;
  wait: WaitKey | null;
  /** the work on record has outlived its own time limit */
  stuck?: boolean;
  /** since when it has waited; null = nothing on record says */
  since: string | null | undefined;
  place: string;
  children?: ReactNode;
}) {
  const t = useNfT();
  const w = since ? waitedParts(since, frame.now) : null;      // the caller decides whether there is a duration to show (lib/story.waitSince)
  const kind = frame.mine ? briefKind(frame.mine) : null;
  return (
    <>
      <button type="button" className="back" onClick={frame.onBack}>← {t(`story.back.${frame.from}`)}<kbd>Esc</kbd></button>
      <div className="meta" style={{ marginTop: 10 }}>
        <span className="ref">{refText}</span>
        {sev && <span className={`sev ${tone}`}>{sev}</span>}
        {frame.askTo && <Link className="story-link" to={frame.askTo}>{t("act.ask")}<kbd>Q</kbd></Link>}
      </div>
      <h1>{title}</h1>
      <div className="statusline">
        <b>{state}</b>
        {wait && (
          <span className={wait === "wait.you" ? "wait" : undefined}>
            {t(wait)}{w && w.unit !== "now" ? `　${t("wait.since", { t: t(`unit.${w.unit}`, { n: w.n }) })}` : ""}
          </span>
        )}
        {stuck && wait !== "wait.agentOverdue" && <span className="wait">{t("lane.overdue")}</span>}
        {liveLane && <Link className="story-link" to={lanePath(liveLane)}>{t("story.watchLive")}</Link>}
        {place && <span>{place}</span>}
      </div>
      {frame.mine && (
        <p className="ask">
          <b>{t("ask.lead")}</b>{t(`story.ask.${kind ?? "generic"}`)}{"　"}
          <button type="button" className="btn sm" style={{ verticalAlign: "middle" }} onClick={frame.onDecide}>
            <span className="t">{t("story.goDecide")}</span><kbd>↵</kbd>
          </button>
        </p>
      )}
      {children}
    </>
  );
}

export interface StepView {
  id: string;
  state: SpineState;
  /** when this step happened; null = nothing on record says */
  at?: string | null;
  who?: string | null;
  body?: ReactNode;
}

/** The six steps down the page. A step not reached yet is only its name. */
export function Spine({ steps, now }: { steps: StepView[]; now: number }) {
  const t = useNfT();
  return (
    <ol className="spine">
      {steps.map((s) => {
        const reached = s.state !== "todo" && s.state !== "skipped";     // a step never taken is its name and «not taken», nothing else
        return (
          <li key={s.id} className={s.state}>
            <h3>
              {t(`phase.${s.id}`)}<span className="sr">{t(`spine.${s.state}`)}</span>
              {s.state === "skipped" && <span className="who">{t("spine.skipped.note")}</span>}
              {reached && s.at && <time>{utcStamp(s.at, now)} UTC</time>}
              {reached && s.who && <span className="who">{s.who}</span>}
            </h3>
            {reached && s.body}
          </li>
        );
      })}
    </ol>
  );
}

/** «全部记录»: every event on the item's timeline, one sentence each (the classic page's own sentences), under a fold. */
export function WholeRecord({ events, failed, now }: { events: PipelineEvent[] | undefined; failed: boolean; now: number }) {
  const t = useNfT();
  const { t: classic } = useLocale();
  if (events === undefined) return failed ? <p className="note err">{t("sec.failedLoad")}</p> : <div className="skel" style={{ height: 18, marginTop: 14 }} />;
  const entries = toActivity(events);
  return (
    <details className="more whole">
      <summary>{t("story.all", { n: events.length })}</summary>
      {entries.length === 0 ? <p className="note">{t("story.all.none")}</p> : (
        <ol className="rec">
          {entries.map((e, i) => (
            <li key={i} className={e.tone}>
              <time>{utcStamp(e.ts, now)} UTC</time>
              <span>{fillPlaceholders(classic(e.labelKey), e.labelParams)}{e.count > 1 ? ` ×${e.count}` : ""}{e.summary ? ` — ${e.summary}` : ""}</span>
              {e.note != null && <span className="said">{e.note}</span>}
              <small>{e.actor}</small>
            </li>
          ))}
        </ol>
      )}
    </details>
  );
}

export interface FactView { label: string; value: string; kind?: "date" | "mono"; href?: string }

/** The facts beside the story: the backend's own status name first, then the item's facts, then the way to its
 *  classic page. */
export function FactList({ status, rows, classicTo, now }: { status: string; rows: FactView[]; classicTo: string; now: number }) {
  const t = useNfT();
  return (
    <>
      <h2>{t("story.facts")}</h2>
      <dl>
        <dt>{t("fact.state")}</dt><dd className="mono">{status}</dd>
        {rows.map((r) => (
          <FactRowView key={r.label} label={r.label}>
            {r.href ? <Link to={r.href}>{r.value}</Link> : r.kind === "date" ? `${utcStamp(r.value, now)} UTC` : <span className={r.kind === "mono" ? "mono" : undefined}>{r.value}</span>}
          </FactRowView>
        ))}
        <dt>{t("fact.classic")}</dt><dd><Link to={classicTo} state={CLASSIC_EXIT}>{t("fact.classic.open")}</Link></dd>
      </dl>
    </>
  );
}

function FactRowView({ label, children }: { label: string; children: ReactNode }) {
  return <><dt>{label}</dt><dd>{children}</dd></>;
}

/** The way back, for a page that has nothing else to show yet. */
export function BackOnly({ frame }: { frame: StoryFrame }) {
  const t = useNfT();
  return <button type="button" className="back" onClick={frame.onBack}>← {t(`story.back.${frame.from}`)}<kbd>Esc</kbd></button>;
}

/** Every run of the item, newest first: one line each (its steps under a fold), what it reported when it failed,
 *  which declared checks failed, what was rolled back, and what a person said at its acceptance. */
export function RunList({ runs, planOf, now }: { runs: FixExecution[]; planOf: (run: FixExecution) => FixPlan | null; now: number }) {
  const t = useNfT();
  const { t: classic } = useLocale();
  const { user } = useAuth();
  const who = (actor: string | null | undefined) => whoText(actor, user?.email, t);
  return (
    <>
      {runs.map((run) => {
        const runPlan = planOf(run);
        const r = runLine(run, runPlan);
        const f = r.bad || run.verification_status === "failed" ? failedVm(run, runPlan) : null;
        return (
          <div key={run.id} className="box">
            <details className="more">
              <summary>
                <Prov code />
                {t(r.duration ? "story.run.line" : "story.run.line.noTime",
                   { run: r.id, state: executionStatusLabel(r.status, classic), done: r.done, total: r.total, duration: r.duration })}
              </summary>
              <RunSteps steps={runStepsVm(run, runPlan)} />
            </details>
            <RecordedSteps item={run.health_issue_id ? `I${run.health_issue_id}` : runPlan?.change_request_id ? `C${runPlan.change_request_id}` : null}
                           executionId={run.id} now={now} />
            <StopLine stop={stopOf(run)} now={now} />
            {run.error_message && <p className="note err"><Prov code />{t("ran.error", { msg: run.error_message })}</p>}
            {f && f.failedChecks.length > 0 && (
              <ul className="checks" style={{ marginTop: 8 }}>
                {f.failedChecks.map((c) => <li key={c.id ?? c.label}><span className="pc">{c.id}</span><span>{c.label}</span><span className="st bad">{t("st.failed")}</span></li>)}
              </ul>
            )}
            {f && f.rollback.ran > 0 && <p className="note"><Prov code />{t(f.rollback.failed ? "rollback.failed" : "rollback.ran", { n: f.rollback.ran, f: f.rollback.failed })}</p>}
            {run.accepted_by && (
              <>
                <p><Prov code />{t("story.accept.by", { by: who(run.accepted_by), t: utcStamp(run.accepted_at, now),
                                                     verdict: t(`story.accept.verdict.${run.verification_status === "passed" ? "accepted" : "rejected"}`) })}</p>
                {run.acceptance_note && <Quote text={run.acceptance_note} cite={`${who(run.accepted_by)}　${utcStamp(run.accepted_at, now)} UTC`} />}
              </>
            )}
          </div>
        );
      })}
    </>
  );
}
