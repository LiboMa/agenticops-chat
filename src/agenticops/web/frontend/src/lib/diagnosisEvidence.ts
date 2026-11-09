import type { RCAResult } from "@/api/types";
import { confidenceBreakdown } from "@/lib/rcaQuality";

export type EvidenceTone = "ok" | "warn" | "danger" | "info" | "neutral";
export interface EvidenceRow { key: string; tone: EvidenceTone; text: string }

/** The first screen before any run (MVP-2.8.0 S2): what the diagnosis rests on — the resource anchor, the model's
 *  own confidence (before the evidence / critic penalties), the critic's conclusion and the human verdict, each its
 *  own line; never one folded number (spec; S2 review). While the RCA loads or after it failed, say so instead of
 *  «no verdict yet». `rca` null = no RCA yet. */
export function diagnosisRows(
  { anchorStatus, rca, rcaState }: {
    anchorStatus: string | null | undefined;
    rca: Pick<RCAResult, "confidence" | "evidence_verified" | "critic_verdict" | "human_verdict"> | null | undefined;
    rcaState: "loading" | "failed" | "ready";
  },
  t: (k: string) => string,
): EvidenceRow[] {
  const rows: EvidenceRow[] = [anchorStatus === "anchored"
    ? { key: "anchor", tone: "ok", text: t("workitem.evidence.anchored") }
    : { key: "anchor", tone: "warn", text: t("workitem.evidence.unanchored") }];
  if (rcaState === "loading") return [...rows, { key: "rca", tone: "neutral", text: t("workitem.evidence.rcaLoading") }];
  if (rcaState === "failed") return [...rows, { key: "rca", tone: "danger", text: t("workitem.evidence.rcaFailed") }];
  if (rca && typeof rca.confidence === "number") {
    const { raw } = confidenceBreakdown(rca, null);
    rows.push({ key: "confidence", tone: "info",
                text: t("workitem.evidence.confidence").replace("{pct}", String(Math.round(raw * 100))) });
    const v = rca.critic_verdict;
    if (v === "supported" || v === "weak" || v === "refuted") {
      rows.push({ key: "critic", tone: v === "supported" ? "ok" : v === "weak" ? "warn" : "danger",
                  text: t(`rca.quality.critic.${v}`) });
    }
  }
  const verdict = rca?.human_verdict;
  rows.push(verdict === "correct" ? { key: "verdict", tone: "ok", text: t("workitem.evidence.verdictCorrect") }
    : verdict === "incorrect" ? { key: "verdict", tone: "danger", text: t("workitem.evidence.verdictIncorrect") }
    : { key: "verdict", tone: "neutral", text: t("workitem.evidence.noVerdict") });
  return rows;
}
