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

/** Until 2026-11-17 the timeline kept only the first 200 characters of a verdict's reason (the box takes 2,000).
 *  A note that is exactly that long is, almost certainly, one of those: the page says the record holds only part of
 *  it instead of quoting it as the whole reason. A reason written since is kept whole. */
const OLD_NOTE_LIMIT = 200;
export function noteWasCut(note: string): boolean {
  return note.length === OLD_NOTE_LIMIT;
}

