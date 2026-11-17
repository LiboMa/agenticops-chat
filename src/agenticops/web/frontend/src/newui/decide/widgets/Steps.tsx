import { useNfT } from "../../i18n";
import type { StepVm } from "../../lib/briefs/plan";

/** A plan's steps: what each says it does, how the code classifies its command, and the command itself. */
export function Steps({ steps }: { steps: StepVm[] }) {
  const t = useNfT();
  return (
    <ol className="steps">
      {steps.map((s, i) => (
        <li key={i}>
          <span className="say">
            {s.say || (s.cmd ? "" : "—")}
            {s.tier && <span className={`tier${s.tier === "write" || s.tier === "blocked" || s.tier === "unknown" ? " w" : ""}`}>{t(`tier.${s.tier}`)}</span>}
          </span>
          {s.cmd && <code className="cmd">{s.cmd}</code>}
        </li>
      ))}
    </ol>
  );
}
