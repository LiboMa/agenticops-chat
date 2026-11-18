import type { PipelineEvent } from "@/api/types";
import { toActivity } from "@/lib/activity";
import { fillPlaceholders } from "@/lib/placeholders";
import type { RecentEvent } from "./pulse";

/** One event of the band as one sentence — the classic timeline's own sentence for that event (lib/activity), so the
 *  band, the replay and the item's page say the same thing. `classic` is the classic interface's `t`. */
export function eventSentence(e: RecentEvent, classic: (key: string) => string): string {
  const asEvent = { id: e.id, event_type: e.type, stage: "", status: e.status, detail: e.detail, actor: e.actor,
                    duration_ms: null, created_at: e.at, trace_id: null } as unknown as PipelineEvent;
  const [entry] = toActivity([asEvent]);
  if (!entry) return e.type;
  return `${fillPlaceholders(classic(entry.labelKey), entry.labelParams)}${entry.summary ? ` — ${entry.summary}` : ""}`;
}

/** "I#12" / "C#3" for an item id of the band ("I12" / "C3"); "" when the event names none. */
export const itemRef = (item: string | null): string => (item ? `${item[0]}#${item.slice(1)}` : "");
