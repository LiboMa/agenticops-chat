import type { FixPlan } from "@/api/types";
import { useAuth } from "@/hooks/useAuth";
import { usePreviousDiff } from "../../hooks/usePlanReview";
import { useNfT } from "../../i18n";
import { whoText } from "../../lib/activity";
import { prevDiffVm, tallyOf, type DiffPart } from "../../lib/briefs/diff";
import { utcStamp } from "../../lib/time";
import { Prov } from "./Cause";
import { Quote } from "./RunSteps";

const MARK = { add: "+", del: "−", chg: "~" } as const;

/** One list of a plan against the same list of the plan before: first its changes in numbers, then — folded when
 *  there are many — each changed line, said in words (the mark is decoration). Two lists with nothing in them are
 *  «nothing to compare», a list with no changed line is «unchanged»: never the one for the other. */
function Part({ part, which }: { part: DiffPart; which: "steps" | "rollback" }) {
  const t = useNfT();
  const n = tallyOf(part);
  if (!n.comparable) return <p className="note">{t(`diff.${which}.none`)}</p>;
  if (!part.lines.length) return <p className="note">{t(`diff.${which}.same`, { n: n.same })}</p>;
  const said = [n.chg && t("diff.sum.chg", { n: n.chg }), n.add && t("diff.sum.add", { n: n.add }), n.del && t("diff.sum.del", { n: n.del }),
                n.same && t("diff.sum.same", { n: n.same })].filter(Boolean).join(t("diff.sum.join"));
  return (
    <details className="more" open={n.open}>
      <summary>{t(`diff.${which}`)}{said}</summary>
      <ul className="diff">
        {part.lines.map((l, i) => (
          <li key={i} className={l.kind}>
            <b aria-hidden="true">{MARK[l.kind]}</b>
            <span>
              <span className="lbl">{t(`diff.${l.kind}`, { n: l.n })}</span>
              <code>{l.text}</code>
              {l.kind === "chg" && <span className="was">{t(l.wasN === l.n ? "diff.was" : "diff.wasAt", { n: l.wasN ?? l.n })}<code>{l.was}</code></span>}
            </span>
          </li>
        ))}
      </ul>
    </details>
  );
}

/** «What changed since the previous plan (#N)» on the approve brief (N14): what became of the plan before this one
 *  — a person's reason is quoted, a reason code wrote is said as the code's —, then the difference by what would
 *  run. Nothing for an issue's first plan. «No line changed» is never said as «nothing changed»: the plan is word
 *  for word the old one, or something else in it differs, or that is not known. */
export function PrevDiffSection({ plan, now }: { plan: FixPlan; now: number }) {
  const t = useNfT();
  const { user } = useAuth();
  const q = usePreviousDiff(plan.id, plan.content_hash ?? null);
  if (q.isError) {
    return (
      <div className="sec">
        <h2>{t("sec.prevDiff.any")}</h2>
        <p className="note err" role="alert">{t("diff.failed")}</p>
        <p><button type="button" className="btn" onClick={() => void q.refetch()}><span className="t">{t("state.retry")}</span></button></p>
      </div>
    );
  }
  const vm = prevDiffVm(q.data, plan.risk_level);
  if (!vm) return null;
  const n = String(vm.previousId);
  return (
    <div className="sec">
      <h2>{t("sec.prevDiff", { n })}</h2>
      {vm.ended === "feedback"
        ? <Quote text={vm.reason} cite={t("diff.cite", { by: whoText(vm.by, user?.email, t) || t("who.someone"), t: utcStamp(vm.at, now) })} />
        : vm.ended === "byCode" ? <p className="note" style={{ marginTop: 0 }}><Prov code />{t("diff.byCode", { reason: vm.reason })}</p>
        : <p className="note" style={{ marginTop: 0 }}>{t(`diff.ended.${vm.ended}`, { status: vm.status })}</p>}
      {vm.otherDiagnosis && <p className="note">{t("diff.otherDiagnosis")}</p>}
      {vm.verdict === "changed"
        ? <><Part part={vm.steps} which="steps" /><Part part={vm.rollback} which="rollback" /></>
        : <p className={`note${vm.verdict === "identical" ? " warn" : ""}`}>{t(`diff.${vm.verdict}`)}</p>}
      {vm.risk && <p className="note">{t("diff.risk", { from: vm.risk.from, to: vm.risk.to })}</p>}
      <p className="note"><Prov code />{t("diff.how")}</p>
    </div>
  );
}
