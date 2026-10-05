import { useState } from "react";
import { Link } from "react-router-dom";
import type { PipelineEvent, RCAResult } from "@/api/types";
import { Spinner } from "@/components/ui/Spinner";
import { LocalGraph } from "@/components/graph/LocalGraph";
import { VerdictBlock } from "@/components/issue/VerdictBlock";
import { formatFullDate } from "@/lib/formatDate";
import { renderMarkdown } from "@/lib/renderMarkdown";
import { confidenceBreakdown, gateSentenceKey, qualityBadges, unmatchedRefs, type QualityTone } from "@/lib/rcaQuality";

type T = (key: string) => string;

const TONE: Record<QualityTone, string> = {
  ok: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300",
  warn: "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300",
  bad: "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300",
};

const pct = (x: number) => `${Math.round(x * 100)}%`;

/** ① Diagnose: the RCA, where it located the cause, the local graph and "your verdict" (not on a closed issue).
 *  Without an RCA the card only says so — running one is the status line's or the ⋯ menu's job (P10). */
export function DiagnoseBody({ issueId, rca, loading, threshold, timelineEvents, closed, onVerdictDone, t }: {
  issueId: number;
  rca: RCAResult | null | undefined;
  loading: boolean;
  threshold: number | null | undefined;
  timelineEvents: PipelineEvent[] | undefined;
  closed: boolean;
  onVerdictDone: () => void;
  t: T;
}) {
  if (loading) return <Spinner label={t("common.loading")} />;
  if (!rca) {
    return (
      <div className="space-y-1">
        <p className="font-medium text-foreground">{t("issues.noRca")}</p>
        <p className="text-sm text-muted-foreground">{t("issues.rcaHint")}</p>
      </div>
    );
  }
  return (
    <div className="space-y-6">
      <RcaSection rca={rca} threshold={threshold} timelineEvents={timelineEvents} showVerdict={closed} t={t} />
      <LocationSection rca={rca} t={t} />
      <GraphDetails issueId={issueId} rca={rca} t={t} />
      {!closed && (
        <div id="verdict" className="scroll-mt-4">
          <VerdictBlock issueId={issueId} rca={rca} onDone={onVerdictDone} />
        </div>
      )}
    </div>
  );
}

/** The one-line summary of a collapsed ① card: the confidence, then the strongest verdict there is. */
export function diagnoseSummary(rca: RCAResult | null | undefined, t: T): string | null {
  if (!rca) return null;
  const verdict = rca.human_verdict ? `${t("issues.rcaHumanVerdict")}: ${t(`location.verdict.${rca.human_verdict}`)}`
    : qualityBadges(rca).map((q) => t(q.key)).pop() ?? "";
  const tpl = t("workitem.summary.diagnose").replace("{conf}", pct(confidenceBreakdown(rca, null).final));
  return verdict ? tpl.replace("{verdict}", verdict) : tpl.replace(/\s*·\s*\{verdict\}/, "");
}

/* ================================================================== */
/*  RCA                                                                */
/* ================================================================== */

function RcaSection({ rca: r, threshold, timelineEvents, showVerdict, t }: {
  rca: RCAResult;
  threshold: number | null | undefined;
  timelineEvents: PipelineEvent[] | undefined;
  showVerdict: boolean;
  t: T;
}) {
  const b = confidenceBreakdown(r, threshold);
  const steps = [
    ...(b.evidencePenalty ? [t("rca.confidence.stepEvidence")] : []),
    ...(b.criticPenalty ? [t("rca.confidence.stepCritic")] : []),
  ];
  const explain = [
    ...(steps.length ? [t("rca.confidence.breakdown").replace("{raw}", pct(b.raw))
      .replace("{steps}", steps.join(" → ")).replace("{final}", pct(b.final))] : []),
    ...(r.critic_verdict === "weak" ? [t("rca.confidence.criticWeakFree")] : []),
  ];
  const gate = gateSentenceKey(b);
  const refs = unmatchedRefs(timelineEvents);
  const model = r.model_id?.trim();
  const factors = r.contributing_factors ?? [];
  const recs = r.recommendations ?? [];
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-lg font-semibold text-foreground">{t("issues.rcaResults")}</h3>
        {qualityBadges(r).map((q) => (
          <span key={q.key} title={q.hint ?? undefined} className={`text-xs font-medium px-2 py-0.5 rounded-full ${TONE[q.tone]}`}>
            {t(q.key)}
          </span>
        ))}
        {/* on a closed issue VerdictBlock is not rendered, so the recorded verdict is shown here */}
        {showVerdict && r.human_verdict && (
          <span className="ml-auto text-xs text-muted-foreground">
            {t("issues.rcaHumanVerdict")}: <span className="text-foreground">{t(`location.verdict.${r.human_verdict}`)}</span>
          </span>
        )}
      </div>

      {/* Root cause */}
      <div>
        <h4 className="font-semibold text-foreground">{t("issues.rootCause")}</h4>
        <p className="mb-2 text-xs text-muted-foreground">
          {model && <>{t("issues.rcaModel")}: {model} · </>}
          {t("issues.rcaAnalyzed")} {formatFullDate(r.created_at)}
        </p>
        <div className="text-foreground report-content" dangerouslySetInnerHTML={{ __html: renderMarkdown(r.root_cause) }} />
      </div>

      {/* Confidence bar, the auto-fix threshold, and how the stored number was reached */}
      <div>
        <div className="flex justify-between text-sm mb-1">
          <span className="text-muted-foreground">{t("issues.confidence")}</span>
          <span className="font-medium text-foreground">{pct(b.final)}</span>
        </div>
        <div className="relative w-full bg-secondary rounded-full h-2">
          <div className="bg-primary h-2 rounded-full transition-all" style={{ width: `${b.final * 100}%` }} />
          {b.threshold !== null && (
            <div
              className="absolute top-1/2 -translate-y-1/2 w-px h-3 bg-foreground/60"
              style={{ left: `${b.threshold * 100}%` }}
              title={t("rca.confidence.threshold").replace("{threshold}", pct(b.threshold))}
            />
          )}
        </div>
        {explain.length > 0 && <div className="mt-1 text-xs text-muted-foreground">{explain.join(" · ")}</div>}
        {gate && <div className="mt-1 text-xs text-amber-600 dark:text-amber-400">{t(gate)}</div>}
        {refs.length > 0 && (
          <div className="mt-3">
            <div className="text-xs font-medium text-foreground mb-1">{t("rca.unmatchedRefs")}</div>
            <ul className="space-y-0.5">
              {refs.map((ref, i) => <li key={i} className="font-mono text-xs break-all text-muted-foreground">{ref}</li>)}
            </ul>
          </div>
        )}
      </div>

      {factors.length > 0 && (
        <details>
          <summary className="cursor-pointer text-sm font-semibold text-foreground">
            {t("issues.contributingFactors")} ({factors.length})
          </summary>
          <ul className="mt-2 list-disc list-inside text-muted-foreground space-y-1">
            {factors.map((f, i) => <li key={i}>{f}</li>)}
          </ul>
        </details>
      )}
      {recs.length > 0 && (
        <details>
          <summary className="cursor-pointer text-sm font-semibold text-foreground">
            {t("issues.recommendations")} ({recs.length})
          </summary>
          <ol className="mt-2 list-decimal list-inside text-muted-foreground space-y-1">
            {recs.map((rec, i) => <li key={i}>{rec}</li>)}
          </ol>
        </details>
      )}
    </div>
  );
}

/* ================================================================== */
/*  Root-cause location (display only — the verdict is VerdictBlock's) */
/* ================================================================== */

const LOCATION_CHIP: Record<string, string> = {
  valid: "bg-green-500/20 text-green-600 dark:text-green-400",
  partial: "bg-amber-500/20 text-amber-600 dark:text-amber-400",
  invalid: "bg-red-500/20 text-red-600 dark:text-red-400",
  absent: "bg-secondary text-muted-foreground",
};

function LocationSection({ rca: r, t }: { rca: RCAResult; t: T }) {
  const status = r.location_status ?? "absent";
  const loc = r.location;
  return (
    <div className="rounded-lg border border-border p-4">
      <div className="flex items-center gap-2 mb-3">
        <h3 className="font-semibold text-foreground">{t("location.title")}</h3>
        <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${LOCATION_CHIP[status] ?? LOCATION_CHIP.absent}`}>
          {t(`location.status.${status}`)}
        </span>
      </div>

      {loc && loc.candidates.length > 0 ? (
        <ol className="space-y-2 mb-3">
          {loc.candidates.map((c) => (
            <li key={c.ref} className="flex flex-wrap items-center gap-2 text-sm">
              <span className="font-mono text-xs text-muted-foreground">#{c.rank}</span>
              <Link to={`/app/resources/${c.ref}`} className="font-medium text-primary hover:underline">
                {c.name || c.resource_id || `#${c.ref}`}
              </Link>
              {c.type && <span className="text-xs text-muted-foreground">{c.type}</span>}
              {c.supporting.length > 0 && (
                <span className="text-xs text-green-600 dark:text-green-400">
                  {t("location.supporting")} {c.supporting.join(", ")}
                </span>
              )}
              {c.refuting.length > 0 && (
                <span className="text-xs text-red-600 dark:text-red-400">
                  {t("location.refuting")} {c.refuting.join(", ")}
                </span>
              )}
            </li>
          ))}
        </ol>
      ) : (
        <p className="text-sm text-muted-foreground mb-3">{t("location.noCandidates")}</p>
      )}

      {loc && loc.path.length > 0 && (
        <p className="text-xs text-muted-foreground mb-3">
          {t("location.path")}:{" "}
          {loc.path.map((e) => `${e.src_name || `#${e.src_ref}`} → ${e.dst_name || `#${e.dst_ref}`} (${e.relation_type})`).join(" · ")}
        </p>
      )}
      {loc && loc.dropped.length > 0 && (
        <div className="text-xs text-muted-foreground mb-3">
          <span>{t("location.dropped")}:</span>
          <ul className="list-disc list-inside">
            {loc.dropped.map((d, i) => <li key={i}>{d}</li>)}
          </ul>
        </div>
      )}

      {/* a recorded location verdict stays visible read-only; judging it is VerdictBlock's */}
      {r.location_verdict && (
        <p className="text-sm border-t border-border pt-3">
          <span className="text-muted-foreground">{t("location.verdict")}:</span>{" "}
          <span className="text-foreground">{t(`location.verdict.${r.location_verdict}`)}</span>
          <span className="text-xs text-muted-foreground">
            {r.location_verdict_by && ` · ${r.location_verdict_by}`}
            {r.location_verdict_at && ` · ${formatFullDate(r.location_verdict_at)}`}
          </span>
        </p>
      )}
    </div>
  );
}

/** The local graph, folded; mounted only once opened so a folded card fetches and lays out nothing. */
function GraphDetails({ issueId, rca, t }: { issueId: number; rca: RCAResult; t: T }) {
  const [open, setOpen] = useState(false);
  return (
    <details onToggle={(e) => setOpen(e.currentTarget.open)}>
      <summary className="cursor-pointer text-sm font-semibold text-foreground">{t("graph.title")}</summary>
      {open && (
        <div className="mt-3">
          <LocalGraph subject={{ issueId }} path={rca.location?.path} compact />
        </div>
      )}
    </details>
  );
}
