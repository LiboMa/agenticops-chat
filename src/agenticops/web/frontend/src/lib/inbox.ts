import { parseApiDate } from "@/lib/formatDate";

/** The to-do workbench (/app/inbox, MVP-2.8.0 S2): every work item that waits on you, tabbed by the decision it
 *  needs. The URL holds the state — `decision`, `q`, `item`, `layout`. Never `tab`: the embedded issue page reads
 *  `?tab=` as its legacy card link and would strip it. */
export const INBOX_TABS = ["all", "approval", "acceptance", "failed", "confirm"] as const;
export type InboxTab = (typeof INBOX_TABS)[number];
export type InboxLayout = "split" | "compact";

const REASONS: Record<Exclude<InboxTab, "all">, string[]> = {
  approval: ["approval_required"],
  acceptance: ["verification_required"],
  failed: ["execution_failed", "execution_not_started"],
  confirm: ["review_required", "clarification_required"],
};

/** The decision tabs' keyboard (S2 leftover; WAI-ARIA tabs): ←/→ move and wrap, Home / End go to the ends;
 *  any other key is not the tab bar's (null). */
export function nextTab<T extends string>(tabs: readonly T[], current: T, key: string): T | null {
  const i = Math.max(0, tabs.indexOf(current));
  if (key === "ArrowRight") return tabs[(i + 1) % tabs.length];
  if (key === "ArrowLeft") return tabs[(i - 1 + tabs.length) % tabs.length];
  if (key === "Home") return tabs[0];
  if (key === "End") return tabs[tabs.length - 1];
  return null;
}

export function tabReasons(tab: InboxTab): string[] | null {
  return tab === "all" ? null : REASONS[tab];
}

/** A tab's number from the server's per-reason `counts` (taken before the reason filter, so it never moves with
 *  the selected tab). */
export function tabCount(counts: Record<string, number> | undefined, tab: InboxTab): number {
  if (!counts) return 0;
  const reasons = tabReasons(tab);
  return Object.entries(counts).reduce((n, [reason, c]) => n + (reasons === null || reasons.includes(reason) ? c : 0), 0);
}

export interface InboxParams { decision: InboxTab; q: string; item: string | null; layout: InboxLayout }

export function inboxParams(search: string | URLSearchParams): InboxParams {
  const p = typeof search === "string" ? new URLSearchParams(search) : search;
  const decision = p.get("decision") ?? "all";
  const item = p.get("item");
  return {
    decision: (INBOX_TABS as readonly string[]).includes(decision) ? (decision as InboxTab) : "all",
    q: (p.get("q") ?? "").trim().slice(0, 200),
    item: item && parseItem(item) ? item : null,
    layout: p.get("layout") === "compact" ? "compact" : "split",
  };
}

/** The query string for these params, defaults left out ("" when all are defaults). */
export function inboxSearch(p: InboxParams): string {
  const out = new URLSearchParams();
  if (p.decision !== "all") out.set("decision", p.decision);
  if (p.q) out.set("q", p.q);
  if (p.item) out.set("item", p.item);
  if (p.layout !== "split") out.set("layout", p.layout);
  const qs = out.toString();
  return qs ? `?${qs}` : "";
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
