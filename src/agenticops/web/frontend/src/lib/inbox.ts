import { parseApiDate } from "@/lib/formatDate";

import type { AttentionItem } from "@/lib/attention";

/** The to-do items (MVP-2.8.0: «问题 · 在等我», the to-do workbench merged into Issues): every work item waiting on
 *  you, grouped by the decision it needs. The URL holds the state — `q`, `item`. Never `tab`: the embedded issue
 *  page reads `?tab=` as its legacy card link and would strip it. */

/** The decision groups, in order — the server's services/attention.DECISION_GROUPS / DECISION_OF (shared fixture
 *  tests/fixtures/attention_decision_groups.json). */
export const DECISION_GROUPS = ["approval", "acceptance", "failed", "confirm"] as const;
export type DecisionGroup = (typeof DECISION_GROUPS)[number];
const DECISION_OF: Record<string, DecisionGroup> = {
  approval_required: "approval",
  verification_required: "acceptance",
  execution_failed: "failed", execution_not_started: "failed",
  review_required: "confirm", clarification_required: "confirm",
};

export function groupOf(reason: string): DecisionGroup | null {
  return DECISION_OF[reason] ?? null;
}

/** The loaded items under their decision groups, in the fixed order (the server sorts by group already, so later
 *  pages only append to the last group). A group's count is the server's (`counts` per reason), so it includes rows
 *  not loaded yet; a group with nothing loaded and nothing counted is left out. */
export function groupItems(items: AttentionItem[], counts: Record<string, number> | undefined):
    { group: DecisionGroup; count: number; items: AttentionItem[] }[] {
  return DECISION_GROUPS.map((group) => ({
    group,
    count: Object.entries(counts ?? {}).reduce((n, [reason, c]) => n + (DECISION_OF[reason] === group ? c : 0), 0),
    items: items.filter((i) => DECISION_OF[i.reason] === group),
  })).filter((g) => g.items.length > 0 || g.count > 0);
}

/** "I12" → an issue, "C3" → a change; anything else null. */
export function parseItem(ref: string | null | undefined): { kind: "issue" | "change"; id: number } | null {
  const m = /^([IC])([1-9]\d{0,8})$/.exec(ref ?? "");
  return m ? { kind: m[1] === "I" ? "issue" : "change", id: Number(m[2]) } : null;
}

/** "Waiting 25 min / 3 h / 3 days" from when it started waiting; under a minute (or a clock ahead) "Just now". */
export function waitLabel(sinceIso: string | null | undefined, now: number, t: (k: string) => string): string | null {
  const since = parseApiDate(sinceIso ?? null);
  if (!since) return null;
  const minutes = Math.floor((now - since.getTime()) / 60_000);
  if (minutes < 1) return t("inbox.wait.justNow");
  if (minutes < 60) return t("inbox.wait.minutes").replace("{n}", String(minutes));
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return t("inbox.wait.hours").replace("{n}", String(hours));
  return t("inbox.wait.days").replace("{n}", String(Math.floor(hours / 24)));
}

/** Who counts as a person waited on (services/work_phases.HUMAN); everyone else is a system at work. */
export const WAITING_PEOPLE: ReadonlySet<string> = new Set(["you", "approver", "requester", "acceptor"]);

/** The first screen's wait fact, from the server's `waiting_on`: a duration only while a PERSON is waited on, as the
 *  Cases rows — a completed change shows none, and a run in flight never reads «等执行器 · 已等 2 天» (S2 review). */
export function waitFact(waitingOn: string | null | undefined, sinceIso: string | null | undefined, now: number,
                         t: (k: string) => string): string | null {
  return waitingOn && WAITING_PEOPLE.has(waitingOn) ? waitLabel(sinceIso, now, t) : null;
}

/** Whether the item in the URL is still in the queue: an item just approved or accepted leaves it ("gone") — the
 *  pane says so and offers the next one instead of going blank. `ready` = the list has loaded successfully, `seen` =
 *  the ids this view has shown (an item seen and now missing is gone even while more pages exist — S2 review). */
export function selectionState(
  items: { id: string }[], item: string | null,
  { ready = true, hasMore = false, seen }: { ready?: boolean; hasMore?: boolean; seen?: ReadonlySet<string> } = {},
): "selected" | "gone" | "none" {
  if (!item) return "none";
  if (items.some((i) => i.id === item)) return "selected";
  if (!ready) return "selected";            // not loaded yet / the list failed: show the item, claim nothing about it
  if (seen?.has(item)) return "gone";       // it was in this view and has left it: handled
  return hasMore ? "selected" : "gone";     // a deep link not seen yet may sit on a page not loaded yet
}
