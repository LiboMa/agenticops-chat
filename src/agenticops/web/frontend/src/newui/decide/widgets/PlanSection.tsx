import type { ReactNode } from "react";
import type { FixPlan } from "@/api/types";
import { useNfT } from "../../i18n";
import { planHead, postChecksVm, rollbackVm, stepsVm } from "../../lib/briefs/plan";
import { Prov } from "./Cause";
import { Steps } from "./Steps";

/** A plan in a brief: its version, hash and risk in the heading, each step with what the code makes of its command,
 *  and the rollback — whatever shape the plan wrote it in. */
export function PlanSection({ plan, heading, kind, rollback = true, children }: {
  plan: FixPlan; heading: string; kind: "fix" | "change"; rollback?: boolean; children?: ReactNode;
}) {
  const t = useNfT();
  const head = planHead(plan);
  const steps = stepsVm(plan);
  const rb = rollbackVm(plan);
  return (
    <div className="sec">
      <h2>
        {heading}　<span className="num" style={{ color: "var(--dim)" }}>
          {t("plan.version", { label: t(`plan.label.${kind}`), v: head.version })}　{head.hash8 && t("plan.hash", { hash: head.hash8 })}　{head.risk}
        </span>
      </h2>
      {steps.length ? <Steps steps={steps} /> : <p className="note">{t("plan.noSteps")}</p>}
      {steps.some((s) => s.tier) && <p className="note"><Prov code />{t("plan.tierNote")}</p>}
      {children}
      {rollback && (
        <>
          <p className="note">{t("plan.rollback")}{rb.trigger ? `　${t("plan.rollback.trigger", { t: rb.trigger })}` : ""}</p>
          {rb.steps.length > 0 && <Steps steps={rb.steps} />}
          {rb.notes.length > 0 && <dl className="res rb">{rb.notes.map((n) => <div key={n.label}><dt>{n.label}</dt><dd>{n.text}</dd></div>)}</dl>}
          {!rb.steps.length && !rb.notes.length && <p className="note">{t("plan.rollback.none")}</p>}
        </>
      )}
    </div>
  );
}

/** «How we know it worked»: the plan's declared checks, named as the executor reports them. */
export function ChecksSection({ plan }: { plan: FixPlan }) {
  const t = useNfT();
  const checks = postChecksVm(plan);
  return (
    <div className="sec">
      <h2>{t("sec.done")}</h2>
      {checks.length > 0 ? (
        <>
          <ul className="checks">
            {checks.map((c) => <li key={c.id}><span className="pc">{c.id}</span><span>{c.text}</span><span className="st">{t("checks.after")}</span></li>)}
          </ul>
          <p className="note">{t("checks.note")}</p>
        </>
      ) : <p className="note">{t("checks.none")}</p>}
    </div>
  );
}
