import { useEffect, useRef, useState } from "react";
import { useAuth } from "@/hooks/useAuth";
import { Prov } from "../decide/widgets/Cause";
import { useLaneSteps, type StepsOf } from "../hooks/useLaneSteps";
import { useNfT, type NfT } from "../i18n";
import { whoText } from "../lib/activity";
import { runTally, stepVm, type LiveStepVm, type StepRow } from "../lib/steps";
import { utcStamp } from "../lib/time";

const STATE_CLASS: Record<LiveStepVm["state"], string> = { now: "now", done: "done", bad: "done bad", refused: "skip", unended: "skip",
                                                           waiting: "", missed: "skip" };

/** A step's time to the second (steps follow each other within seconds): "03:52:07"; "—" when it cannot be read. */
function clock(at: string): string {
  const d = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(at) ? at : `${at}Z`);
  return Number.isNaN(d.getTime()) ? "—" : d.toISOString().slice(11, 19);
}

function planTag(v: LiveStepVm, t: NfT): string | null {
  if (!v.plan) return null;
  return v.plan.part === "off" ? t("steps.plan.off") : t(`steps.plan.${v.plan.part}`, { n: v.plan.n });
}

function Step({ v, t, me }: { v: LiveStepVm; t: NfT; me: string | null | undefined }) {
  const tag = planTag(v, t);
  // a tool call reads «what it ran» first, then what came back (the start of it); words are just the words.
  // A read-only account is not sent a result (nor a command's own line): that is said — it is not «no output».
  const came = v.state === "now" ? t("steps.running") : v.state === "unended" ? t("steps.unended")
    : v.state === "refused" ? t("steps.refused", { why: v.say || "—" })
    : v.withheld ? t(v.tier ? "steps.withheld.command" : "steps.withheld.result") : v.say || t("steps.noOutput");
  return (
    <li className={`${STATE_CLASS[v.state]}${v.mark === "you" ? " you" : ""}`.trim() || undefined}>
      <span className="say">
        {v.mark === "fact" ? <Prov code /> : v.mark === "say" ? <Prov code={false} /> : v.mark === "act" ? <span className="actm" aria-hidden="true">▸</span>
          : <b className="youtag">{whoText(v.by, me, t) || t("who.someone")}</b>}
        {v.cmd ? <code className="what">{v.cmd}</code> : v.say}
        {v.mark === "you" && <small className={v.state === "missed" ? "note err" : "note"}>{"　"}{t(v.state === "waiting" ? "steps.you.waiting" : v.state === "missed" ? "steps.you.missed" : "steps.you.read")}</small>}
        {v.tier && v.tier !== "readonly" && <span className="tier w">{t(`tier.${v.tier}`)}</span>}
        {tag && <span className={`tier${v.plan?.part === "off" ? " w" : ""}`}>{tag}</span>}
      </span>
      {v.cmd && <span className={`res${v.state === "bad" || v.state === "refused" ? " err" : ""}`}>{came}</span>}
      {v.at && <span className="cmd num">{clock(v.at)} UTC</span>}
    </li>
  );
}

/** The steps of one agent run, as the code recorded them: ◆ a fact a tool fetched, ▸ something the agent did, ◇ the
 *  model's own words, and a person's notes. While `live` the list follows the newest step — until the person scrolls
 *  up to read. `executor` = it is an execution: its commands are counted against its plan. */
export function LiveSteps({ of, live, executor = false, now, heading, onSteps }: {
  of: StepsOf | null; live: boolean; executor?: boolean; now: number;
  /** the section's heading; null = no section of its own (it sits inside another one) */
  heading?: string | null;
  /** the steps as they are read (a run page marks its plan from them) */
  onSteps?: (steps: StepRow[]) => void;
}) {
  const t = useNfT();
  const { user } = useAuth();
  const q = useLaneSteps(of, live);
  const steps = q.data?.steps;
  const end = useRef<HTMLDivElement>(null);            // just below the newest step
  const follow = useRef(true);                        // follow the newest step until the person scrolls up
  const count = steps?.length ?? 0;
  const report = useRef(onSteps);
  report.current = onSteps;
  useEffect(() => { if (steps) report.current?.(steps); }, [steps]);

  // Following = the end of the list is in view (or above the fold's edge): the person is reading the newest steps.
  // Scrolling up until that end leaves the view stops it; scrolling back down to it starts it again. What sits
  // below the list (the item's timeline, the sticky controls) does not count — only where the list's end is.
  const hasList = count > 0;
  useEffect(() => {
    const mark = end.current, box = mark?.closest<HTMLElement>(".stream");
    if (!mark || !box || !live) return;
    const onScroll = () => { follow.current = mark.getBoundingClientRect().top <= box.getBoundingClientRect().bottom + 4; };
    box.addEventListener("scroll", onScroll, { passive: true });
    return () => box.removeEventListener("scroll", onScroll);
  }, [live, hasList]);
  useEffect(() => {
    if (live && follow.current && count > 0) end.current?.scrollIntoView({ block: "end" });
  }, [live, count]);

  const tally = executor && steps ? runTally(steps) : null;
  return (
    <div className={heading === null ? undefined : "sec"}>
      {heading !== null && <h2>{heading ?? t("steps.title")}</h2>}
      {q.isPending && of ? <div className="skel" style={{ height: 54 }} />
        : q.isError && !q.data ? <p className="note err">{t("sec.failedLoad")}</p>
        : !q.data?.run ? <p className="note"><Prov code />{t(live ? "steps.none.live" : "steps.none.ended")}</p>
        : (
          <>
            <p className="note">
              <Prov code />{t("steps.since", { t: utcStamp(q.data.run.started_at, now), n: count })}
              {tally && tally.acts > 0 && `　${t("steps.tally", { acts: tally.acts, verbatim: tally.verbatim })}`}
              {tally && tally.refused > 0 && `　${t("steps.tally.refused", { n: tally.refused })}`}
            </p>
            <ol className="lsteps">
              {steps!.map((s) => <Step key={s.id} v={stepVm(s, live)} t={t} me={user?.email} />)}
            </ol>
            <div ref={end} className="lsteps-end" aria-hidden="true" />
            <p className="note">{t("steps.legend")}</p>
          </>
        )}
    </div>
  );
}

/** A run's recorded steps under its summary, read when the person opens them: what the CODE saw the executor run —
 *  beside what the executor itself reported. */
export function RecordedSteps({ item, executionId, now }: { item: string | null; executionId: number; now: number }) {
  const t = useNfT();
  const [open, setOpen] = useState(false);
  if (!item) return null;
  return (
    <details className="more" onToggle={(e) => setOpen(e.currentTarget.open)}>
      <summary>{t("steps.recorded")}</summary>
      {open && <LiveSteps of={{ item, agent: "executor", execution: executionId }} live={false} executor now={now} heading={null} />}
    </details>
  );
}
