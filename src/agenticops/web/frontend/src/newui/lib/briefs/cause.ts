import type { RCAResult } from "@/api/types";
import { confidenceBreakdown } from "@/lib/rcaQuality";

/** The diagnosis as a brief shows it: the root cause, the evidence it cites, and how far to trust it. */

export interface EvidenceVm { label: string; type: string; ref: string; summary: string }

export interface CauseVm {
  text: string;
  /** the model's own confidence (0–1), as it reported it — before the code's penalties (the classic page's figure) */
  self: number | null;
  /** the stored value: the model's confidence after the code's penalties (a failed evidence check, a refuting
   *  second model) — the figure the auto-fix gate judges */
  gated: number | null;
  /** the two differ: a penalty was applied */
  penalized: boolean;
  /** `gated` is below the auto-fix gate: this is why it waits on a person. False when the gate is unknown. */
  belowGate: boolean;
  critic: "supported" | "weak" | "refuted" | null;
  location: "valid" | "partial" | "invalid" | "absent" | null;
  /** the cited evidence was matched to the run's own tool results (code-checked); null = not checked */
  evidenceGrounded: boolean | null;
  evidence: EvidenceVm[];
}

const CRITIC = ["supported", "weak", "refuted"] as const;
const LOCATION = ["valid", "partial", "invalid", "absent"] as const;
const oneOf = <T extends string>(list: readonly T[], v: unknown): T | null => (list.includes(v as T) ? (v as T) : null);

export function causeVm(rca: RCAResult | null | undefined, gate: number | null | undefined): CauseVm | null {
  if (!rca) return null;
  const gated = typeof rca.confidence === "number" && Number.isFinite(rca.confidence) ? rca.confidence : null;
  const b = gated === null ? null : confidenceBreakdown(rca, gate);
  return {
    text: rca.root_cause ?? "",
    self: b ? b.raw : null,
    gated,
    penalized: !!b && (b.evidencePenalty || b.criticPenalty),
    belowGate: gated !== null && typeof gate === "number" && gated < gate,
    critic: oneOf(CRITIC, rca.critic_verdict),
    location: oneOf(LOCATION, rca.location_status),
    evidenceGrounded: typeof rca.evidence_verified === "boolean" ? rca.evidence_verified : null,
    evidence: (rca.evidence ?? []).map((e, i) => ({ label: `E${i + 1}`, type: e.type, ref: e.ref, summary: e.summary })),
  };
}

/** 0.824 → "82%"; unknown → "—". */
export function pct(share: number | null | undefined): string {
  return typeof share === "number" && Number.isFinite(share) ? `${Math.round(share * 100)}%` : "—";
}
