import { useAuth } from "@/hooks/useAuth";
import { useNfT } from "../../i18n";
import { whoText } from "../../lib/activity";
import type { RunStepVm, StopVm } from "../../lib/briefs/run";
import { utcStamp } from "../../lib/time";
import { Prov } from "./Cause";

/** A run's steps: done, failed (with what it reported), or never reached. */
export function RunSteps({ steps }: { steps: RunStepVm[] }) {
  const t = useNfT();
  return (
    <ol className="steps">
      {steps.map((s, i) => (
        <li key={i} className={s.mark || undefined}>
          <span className="say">
            {s.say || (s.cmd ? "" : "—")}
            {s.tier && <span className={`tier${s.tier === "readonly" ? "" : " w"}`}>{t(`tier.${s.tier}`)}</span>}
          </span>
          {s.cmd && <code className="cmd">{s.cmd}</code>}
          {s.mark === "bad" && s.output && <p className="note err" style={{ marginTop: 4 }}><Prov code />{s.output}</p>}
        </li>
      ))}
    </ol>
  );
}

/** What a person wrote, with who and when. */
export function Quote({ text, cite }: { text: string; cite: string }) {
  return <blockquote className="quote">{text}<cite>{cite}</cite></blockquote>;
}

/** A person asked this run to stop (N9): who and when, what they wrote — and, when the run was recorded as a
 *  success all the same, that it was. Nothing when nobody asked. */
export function StopLine({ stop, now }: { stop: StopVm | null; now?: number }) {
  const t = useNfT();
  const { user } = useAuth();
  if (!stop) return null;
  const who = whoText(stop.by, user?.email, t) || t("who.someone");
  return (
    <>
      <p className={stop.late ? "note err" : "note"}><Prov code />{t(stop.late ? "run.stopped.late" : "run.stopped", { who, t: utcStamp(stop.at, now) })}</p>
      {stop.note && <Quote text={stop.note} cite={t("stop.cite", { by: who, t: utcStamp(stop.at, now) })} />}
    </>
  );
}
