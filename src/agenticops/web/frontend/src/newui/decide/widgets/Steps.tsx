import { useNfT } from "../../i18n";
import type { StepVm } from "../../lib/briefs/plan";

const MARK_CLASS = { done: "ok", bad: "bad", refused: "skip", now: "now" } as const;

/** A plan's steps: what each says it does, how the code classifies its command, and the command itself. `marks` =
 *  how each step went in a run in flight, read from the run's recorded steps (lib/steps.planMarks); none = a plan
 *  that is only being read. */
export function Steps({ steps, marks }: { steps: StepVm[]; marks?: ("done" | "now" | "bad" | "refused" | null)[] }) {
  const t = useNfT();
  return (
    <ol className="steps">
      {steps.map((s, i) => (
        <li key={i} className={marks?.[i] ? MARK_CLASS[marks[i]!] : undefined}>
          <span className="say">
            {s.say || (s.cmd || s.raw ? "" : "—")}
            {s.tier && <span className={`tier${s.tier === "write" || s.tier === "blocked" || s.tier === "unknown" ? " w" : ""}`}>{t(`tier.${s.tier}`)}</span>}
          </span>
          {s.cmd && <code className="cmd">{s.cmd}</code>}
          {s.raw && <><code className="cmd">{s.raw}</code><span className="note">{t("plan.rawStep")}</span></>}
        </li>
      ))}
    </ol>
  );
}
