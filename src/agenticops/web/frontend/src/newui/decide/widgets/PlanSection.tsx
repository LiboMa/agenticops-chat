import type { ReactNode } from "react";
import type { FixPlan } from "@/api/types";
import { useNfT } from "../../i18n";
import { checksVm, planHead, rollbackVm, stepsVm, type CheckVm } from "../../lib/briefs/plan";
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

function CheckList({ checks, when }: { checks: CheckVm[]; when: string }) {
  return (
    <ul className="checks">
      {checks.map((c) => (
        <li key={c.id}>
          <span className="pc">{c.id}</span>
          <span>{c.text}{c.cmd && <code className="cmd">{c.cmd}</code>}</span>
          <span className="st">{when}</span>
        </li>
      ))}
    </ul>
  );
}

/** «How we know it worked» — and what is checked before anything runs: the plan's declared checks of both lists,
 *  each with its command. Both are part of what an approval's hash covers, so an approver sees both, whole. */
export function ChecksSection({ plan }: { plan: FixPlan }) {
  const t = useNfT();
  const pre = checksVm(plan, "pre"), post = checksVm(plan, "post");
  return (
    <div className="sec">
      <h2>{t("sec.done")}</h2>
      {pre.length > 0 && (
        <>
          <p className="note" style={{ marginTop: 0 }}>{t("checks.preNote")}</p>
          <CheckList checks={pre} when={t("checks.before")} />
        </>
      )}
      {post.length > 0 ? (
        <>
          <CheckList checks={post} when={t("checks.after")} />
          <p className="note">{t("checks.note")}</p>
        </>
      ) : <p className="note">{t("checks.none")}</p>}
    </div>
  );
}
