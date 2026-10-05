import { useState } from "react";
import type { ChangeRequestDetail } from "@/api/types";
import { Spinner } from "@/components/ui/Spinner";
import { LocalGraph } from "@/components/graph/LocalGraph";
import { policyActionLabel, policySummary, verdictLabel } from "@/lib/changeDetail";
import { formatFullDate } from "@/lib/formatDate";

type T = (key: string) => string;

const SHOWN_REASONS = 3;

/** ② Review: who reviewed it and the verdict, the action and the policy decision, the first reasons (the rest
 *  folded), a raised risk, the shadow impact count and its graph (folded; marked for reference only while the
 *  policy does not use it). Waiting for clarification, the answer box is here. */
export function ReviewBody({
  cr, quietReasons, impactNote, clarify, onClarifyChange, onSendClarify, sending, t,
}: {
  cr: ChangeRequestDetail;
  quietReasons: boolean;           // the review's reasons ARE the status line's rejection sentence
  impactNote: string | undefined;
  clarify: string;
  onClarifyChange: (v: string) => void;
  onSendClarify: () => void;
  sending: boolean;
  t: T;
}) {
  const p = policySummary(cr.policy_decision, cr.review_reasons);
  const reasons = [...(quietReasons ? [] : cr.review_reasons), ...p.reasons];
  const rest = reasons.slice(SHOWN_REASONS);
  const shadowImpact = cr.policy_decision?.shadow_blast_radius;
  const verdict = verdictLabel(cr.review_verdict, t);
  const muted = "text-muted-foreground";
  return (
    <div className="space-y-4 text-sm">
      {cr.status === "under_review" && <Spinner label={t("changes.todo.review")} />}
      {(cr.reviewed_by || verdict || cr.action_type || cr.policy_rule) && (
        <dl className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {cr.reviewed_by && (
            <div>
              <dt className={muted}>{t("changes.reviewedBy")}</dt>
              <dd className="font-mono break-all">
                {cr.reviewed_by}
                {cr.reviewed_at && <span className={`${muted} font-sans`}> · {formatFullDate(cr.reviewed_at)}</span>}
              </dd>
            </div>
          )}
          {verdict && (
            <div>
              <dt className={muted}>{t("changes.verdict")}</dt>
              <dd>{verdict}</dd>
            </div>
          )}
          {cr.action_type && (
            <div>
              <dt className={muted}>{t("changes.actionType")}</dt>
              <dd className="font-mono">{cr.action_type}</dd>
            </div>
          )}
          {cr.policy_rule && (
            <div>
              <dt className={muted}>{t("changes.policy")}</dt>
              <dd className="break-all"><span className="font-mono">{cr.policy_rule}</span> → {policyActionLabel(cr.policy_action, t)}</dd>
            </div>
          )}
        </dl>
      )}
      {reasons.length > 0 && (
        <div className="space-y-1">
          <ul className={`list-disc list-inside ${muted}`}>
            {reasons.slice(0, SHOWN_REASONS).map((r, i) => <li key={i}>{r}</li>)}
          </ul>
          {rest.length > 0 && (
            <details>
              <summary className="cursor-pointer text-xs text-primary">
                {t("workitem.moreReasons").replace("{n}", String(rest.length))}
              </summary>
              <ul className={`mt-1 list-disc list-inside ${muted}`}>
                {rest.map((r, i) => <li key={i}>{r}</li>)}
              </ul>
            </details>
          )}
        </div>
      )}
      {p.escalatedFrom && p.effectiveRisk && (
        <p className="text-amber-600">
          {t("changes.riskEscalated").replace("{from}", p.escalatedFrom).replace("{to}", p.effectiveRisk)}
        </p>
      )}
      {typeof shadowImpact === "number" && (
        <p className={muted}>
          {t("changes.shadowImpact").replace("{n}", String(shadowImpact))}
          {/* the count is visible unfolded, so its "for reference only" goes with it, not only with the graph */}
          {impactNote && <span className="block text-xs">{impactNote}</span>}
        </p>
      )}
      <ImpactGraph changeRequestId={cr.id} note={impactNote} t={t} />
      {cr.status === "needs_clarification" && (
        <div className="space-y-2 border-t border-border pt-4">
          <label htmlFor="change-clarify" className={`${muted} block`}>{t("changes.clarifyLabel")}</label>
          <textarea
            id="change-clarify"
            rows={3}
            maxLength={4000}
            value={clarify}
            onChange={(e) => onClarifyChange(e.target.value)}
            placeholder={t("changes.clarifyPlaceholder")}
            className="w-full border border-border bg-background rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
          />
          {/* outlined: the page's one filled button is the status line's */}
          <button disabled={!clarify.trim() || sending} onClick={onSendClarify}
                  className="px-4 py-2 text-sm font-medium rounded-lg border border-primary/40 text-primary hover:bg-primary/10 disabled:opacity-50 transition-colors">
            {t("changes.clarify")}
          </button>
        </div>
      )}
    </div>
  );
}

/** The change's impact graph, folded; mounted only once opened so a folded card fetches and lays out nothing. */
function ImpactGraph({ changeRequestId, note, t }: { changeRequestId: number; note: string | undefined; t: T }) {
  const [open, setOpen] = useState(false);
  return (
    <details onToggle={(e) => setOpen(e.currentTarget.open)}>
      <summary className="cursor-pointer text-sm font-semibold text-foreground">{t("changes.impactGraph")}</summary>
      {open && (
        <div className="mt-3">
          <LocalGraph subject={{ changeRequestId }} note={note} height={300} />
        </div>
      )}
    </details>
  );
}
