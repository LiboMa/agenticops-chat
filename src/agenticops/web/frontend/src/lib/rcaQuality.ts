import type { PipelineEvent, RCAResult } from "@/api/types";

/** Mirrors services/rca_quality: an RCA whose cited evidence is not grounded is multiplied by 0.6, one the critic
 *  refutes by 0.5; the auto-fix gate is `confidence >= rca_min_confidence_for_autofix` and the critic did not
 *  refute it. The stored confidence is the final one, so the raw one is reconstructed for the explanation. */
export const EVIDENCE_PENALTY = 0.6;
export const CRITIC_PENALTY = 0.5;

export interface ConfidenceBreakdown {
  raw: number;
  final: number;
  evidencePenalty: boolean;
  criticPenalty: boolean;
  threshold: number | null;
  gatePassed: boolean | null;
}

export function confidenceBreakdown(
  rca: Pick<RCAResult, "confidence" | "evidence_verified" | "critic_verdict">,
  threshold: number | null | undefined,
): ConfidenceBreakdown {
  const final = typeof rca.confidence === "number" ? rca.confidence : 0;
  const evidencePenalty = rca.evidence_verified === false;
  const criticPenalty = rca.critic_verdict === "refuted";
  let raw = final;
  if (evidencePenalty) raw /= EVIDENCE_PENALTY;
  if (criticPenalty) raw /= CRITIC_PENALTY;
  raw = Math.min(1, Math.round(raw * 1000) / 1000);
  const t = typeof threshold === "number" ? threshold : null;
  return { raw, final, evidencePenalty, criticPenalty, threshold: t,
           gatePassed: t === null ? null : final >= t && !criticPenalty };
}

export type QualityTone = "ok" | "warn" | "bad";
export interface QualityBadge { key: string; tone: QualityTone; hint: string | null }

export function qualityBadges(
  rca: Pick<RCAResult, "evidence_verified" | "critic_verdict" | "critic_notes">,
): QualityBadge[] {
  const out: QualityBadge[] = [];
  if (rca.evidence_verified === true) out.push({ key: "rca.quality.evidenceVerified", tone: "ok", hint: null });
  if (rca.evidence_verified === false) out.push({ key: "rca.quality.evidenceUnverified", tone: "bad", hint: null });
  const v = rca.critic_verdict;
  if (v === "supported" || v === "weak" || v === "refuted") {
    out.push({ key: `rca.quality.critic.${v}`, tone: v === "supported" ? "ok" : v === "weak" ? "warn" : "bad",
               hint: rca.critic_notes || null });
  }
  return out;
}

function asObject(detail: unknown): Record<string, unknown> | null {
  if (typeof detail === "string") {
    try { return asObject(JSON.parse(detail)); } catch { return null; }
  }
  return detail !== null && typeof detail === "object" && !Array.isArray(detail) ? (detail as Record<string, unknown>) : null;
}

/** The references the newest evidence check could not match to a tool result in the RCA's own run. */
export function unmatchedRefs(
  events: Pick<PipelineEvent, "event_type" | "detail" | "created_at">[] | undefined,
): string[] {
  const checks = (events ?? []).filter((e) => e.event_type === "rca_evidence_check");
  const newest = checks.reduce<(typeof checks)[number] | null>(
    (best, e) => (best === null || (e.created_at ?? "") >= (best.created_at ?? "") ? e : best), null);
  const refs = asObject(newest?.detail)?.unmatched_refs;
  return Array.isArray(refs) ? refs.filter((r): r is string => typeof r === "string") : [];
}

/** The sentence under the confidence bar when the auto-fix gate is shut: a refuted RCA is paused by the reviewer
 *  whatever its number, otherwise it is below the threshold; none while the gate passes or the threshold is unknown. */
export function gateSentenceKey(b: ConfidenceBreakdown): "rca.confidence.refutedGate" | "rca.confidence.below" | null {
  if (b.gatePassed !== false) return null;
  return b.criticPenalty ? "rca.confidence.refutedGate" : "rca.confidence.below";
}
