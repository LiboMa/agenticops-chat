import type { PipelineEvent } from "@/api/types";

export interface HumanVerdict { verdict: "correct" | "incorrect"; by: string; note: string; at: string }

const detailOf = (e: PipelineEvent): Record<string, unknown> => {
  let d: unknown = e.detail;
  if (typeof d === "string") { try { d = JSON.parse(d); } catch { return {}; } }
  return d !== null && typeof d === "object" && !Array.isArray(d) ? (d as Record<string, unknown>) : {};
};

/** What a person made of this diagnosis: the newest `rca_human_feedback` on the timeline that names it and carries
 *  a verdict (one that judged only the location is not a verdict on the diagnosis). */
export function humanVerdict(events: PipelineEvent[] | undefined, rcaId: number | null | undefined): HumanVerdict | null {
  let best: HumanVerdict | null = null;
  for (const e of events ?? []) {
    if (e.event_type !== "rca_human_feedback") continue;
    const d = detailOf(e);
    if (d.rca_id !== rcaId || (d.verdict !== "correct" && d.verdict !== "incorrect")) continue;
    const at = e.created_at ?? "";
    if (!best || at > best.at) best = { verdict: d.verdict, by: typeof d.by === "string" ? d.by : e.actor, note: typeof d.note === "string" ? d.note : "", at };
  }
  return best;
}
