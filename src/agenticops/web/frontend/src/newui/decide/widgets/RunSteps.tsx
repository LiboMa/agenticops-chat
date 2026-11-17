import { useNfT } from "../../i18n";
import type { RunStepVm } from "../../lib/briefs/run";
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
