import type { ChangeStepsDiff, FixPlan } from "@/api/types";
import { RiskLevelBadge } from "@/components/ui/RiskLevelBadge";
import { FixPlanStatusBadge } from "@/components/ui/FixPlanStatusBadge";
import { RunbookStep } from "@/components/plans/RunbookStep";
import { CheckItem } from "@/components/plans/CheckItem";
import { RollbackPlan } from "@/components/plans/RollbackPlan";
import { planStepMarks } from "@/lib/changeDetail";
import { isBlank } from "@/lib/issueDetail";
import { planCounts, planLabel, shortHash } from "@/lib/plans";
import { formatShortDate } from "@/lib/formatDate";
import { renderMarkdown } from "@/lib/renderMarkdown";

/** A fix plan or a change's implementation plan, one rendering for both: name, version, hash and whether the
 *  approved hash still matches, the four counts, then the steps / checks / rollback. A change also passes its
 *  `steps_diff`; without one (a fix plan, or a request that brought no steps) there is no diff section. */
export function PlanView({ plan, stepsDiff, hideHeader = false, t }: {
  plan: FixPlan; stepsDiff?: ChangeStepsDiff | null; t: (k: string) => string;
  hideHeader?: boolean;  // the page already shows the label, badges and title (PlanDetail): keep only counts + hash
}) {
  const marks = planStepMarks(stepsDiff);
  const n = planCounts(plan);
  const list = (v: unknown) => (Array.isArray(v) ? v : []);
  const [steps, preChecks, postChecks] = [list(plan.steps), list(plan.pre_checks), list(plan.post_checks)];
  const rollback = plan.rollback_plan && typeof plan.rollback_plan === "object" ? plan.rollback_plan : {};
  return (
    <div className="space-y-4">
      <div className="space-y-1">
        {!hideHeader && (
          <>
            <div className="flex items-center gap-2 flex-wrap">
              <RiskLevelBadge level={plan.risk_level} />
              <FixPlanStatusBadge status={plan.status} />
              <span className="text-sm font-medium text-muted-foreground">{planLabel(plan, t)}</span>
            </div>
            <h3 className="text-lg font-semibold text-foreground">{plan.title}</h3>
          </>
        )}
        <p className="text-xs text-muted-foreground">
          {t("plan.counts")
            .replace("{steps}", String(n.steps))
            .replace("{pre}", String(n.preChecks))
            .replace("{post}", String(n.postChecks))
            .replace("{rollback}", String(n.rollback))}
        </p>
        {/* The content identity an approval is bound to: approving sends this hash back (409 if it changed) */}
        <p className="text-xs text-muted-foreground">
          <span className="font-mono" title={plan.content_hash ?? undefined}>
            {t("plans.hash")} {shortHash(plan.content_hash)}
            {plan.approved_hash &&
              ` · ${t("plans.approvedVersion").replace("{n}", String(plan.approved_version ?? plan.plan_version))} ${shortHash(plan.approved_hash)}`}
          </span>
          {plan.approved_hash && (plan.approved_hash === plan.content_hash
            ? <span className="ml-2 text-emerald-600 dark:text-emerald-400">{t("plan.hashMatches")}</span>
            : <span className="ml-2 text-red-500">{t("plan.hashDrifted")}</span>)}
        </p>
      </div>

      <div className="text-muted-foreground report-content" dangerouslySetInnerHTML={{ __html: renderMarkdown(plan.summary) }} />
      <p className="text-xs text-muted-foreground">
        {/* a blank impact is not a fact: no row, never "-" (spec §1-6) */}
        {!isBlank(plan.estimated_impact) && <>{t("issues.impact")}: <span className="text-foreground">{plan.estimated_impact}</span>{" · "}</>}
        {t("issues.created")}: <span className="text-foreground">{formatShortDate(plan.created_at)}</span>
      </p>

      {marks && (
        <p className="text-xs text-muted-foreground">
          {t("changes.stepsDiff")}:{" "}
          {marks.identical
            ? t("changes.stepsDiff.identical")
            : t("changes.stepsDiff.summary")
                .replace("{added}", String(marks.added))
                .replace("{modified}", String(marks.modified))
                .replace("{removed}", String(marks.removed.length))
                .replace("{unchanged}", String(marks.unchanged))}
        </p>
      )}

      {steps.length > 0 && (
        <div>
          <h4 className="font-semibold text-foreground mb-2">{t("issues.steps")}</h4>
          <ol className="space-y-4">
            {steps.map((st, i) => {
              const mark = marks?.byPlanStep.get(i + 1);
              return (
                <div key={i}>
                  {mark && (
                    <p className="mb-1 text-xs text-amber-600 dark:text-amber-400 break-all">
                      {mark.kind === "added"
                        ? t("changes.stepsDiff.added")
                        : t("changes.stepsDiff.modified").replace("{cmd}", mark.proposed)}
                    </p>
                  )}
                  <RunbookStep index={i + 1} step={st} />
                </div>
              );
            })}
          </ol>
        </div>
      )}

      {marks && marks.removed.length > 0 && (
        <div>
          <h4 className="font-semibold mb-1 text-sm">{t("changes.stepsDiff.removed")}</h4>
          <ul className="space-y-1 text-xs">
            {marks.removed.map((r) => (
              <li key={r.proposed_step} className="font-mono break-all text-muted-foreground line-through">
                {r.proposed_step}. {r.command}
              </li>
            ))}
          </ul>
        </div>
      )}

      {preChecks.length > 0 && (
        <div>
          <h4 className="font-semibold text-foreground mb-2">{t("issues.preChecks")}</h4>
          <ul className="space-y-1.5">
            {preChecks.map((c, i) => <CheckItem key={i} item={c} />)}
          </ul>
        </div>
      )}

      {postChecks.length > 0 && (
        <div>
          <h4 className="font-semibold text-foreground mb-2">{t("issues.postChecks")}</h4>
          <ul className="space-y-1.5">
            {postChecks.map((c, i) => <CheckItem key={i} item={c} checkId={`pc-${i + 1}`} />)}
          </ul>
        </div>
      )}

      {Object.keys(rollback).length > 0 && <RollbackPlan plan={rollback} />}
    </div>
  );
}
