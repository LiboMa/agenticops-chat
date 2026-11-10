import type { NavCounts } from "@/api/types";

/** The sidebar's numbers (MVP-2.8.0, owner 2026-11-10: direction A — «简约、易用、交互性好»). Each entry shows at most one
 *  number, only when something waits for someone to act; red only when it is urgent (a critical issue waiting, a
 *  failed schedule); never 0, never a number that could not be counted (a failed request says so in the hint), and
 *  none at all for a viewer, who can act on nothing. The hint line under the name says what the number is. */

export type NavQuery = { status: "pending" | "error" | "success"; data?: NavCounts };
export type BadgeTone = "solid" | "solidDanger" | "muted" | "danger";
export interface NavBadge { count: number | null; tone: BadgeTone | null; hint: { key: string; vars?: Record<string, string> } }

type Counted = { value: (d: NavCounts) => number | null | undefined; tone: (d: NavCounts) => BadgeTone; hint: (d: NavCounts) => NavBadge["hint"] };

const COUNTED: Record<string, Counted> = {
  issues: {
    value: (d) => d.attention?.total,
    tone: (d) => ((d.attention?.critical ?? 0) > 0 ? "solidDanger" : "solid"),
    hint: (d): NavBadge["hint"] => {
      const n = String(d.attention?.total ?? 0);
      const critical = d.attention?.critical ?? 0;
      return critical > 0 ? { key: "nav.hint.issuesWaitingCritical", vars: { n, c: String(critical) } }
        : { key: "nav.hint.issuesWaiting", vars: { n } };
    },
  },
  security: { value: (d) => d.security_high, tone: () => "muted", hint: (d) => ({ key: "nav.hint.securityHigh", vars: { n: String(d.security_high) } }) },
  schedules: { value: (d) => d.schedules_failed, tone: () => "danger", hint: (d) => ({ key: "nav.hint.schedulesFailed", vars: { n: String(d.schedules_failed) } }) },
  skills: { value: (d) => d.skill_drafts, tone: () => "muted", hint: (d) => ({ key: "nav.hint.skillDrafts", vars: { n: String(d.skill_drafts) } }) },
};

const quiet = (id: string): NavBadge => ({ count: null, tone: null, hint: { key: `nav.hint.${id}` } });

export function navBadge(id: string, q: NavQuery, readOnly: boolean): NavBadge {
  const c = COUNTED[id];
  if (!c || readOnly || q.status === "pending") return quiet(id);
  if (q.status === "error" || !q.data) return { count: null, tone: null, hint: { key: "nav.hint.unavailable" } };
  const v = c.value(q.data);
  if (v === null || v === undefined) return { count: null, tone: null, hint: { key: "nav.hint.unavailable" } };
  if (v <= 0) return quiet(id);
  return { count: v, tone: c.tone(q.data), hint: c.hint(q.data) };
}

/** A folded group keeps its red numbers on its heading (a failure is never hidden by folding). */
export function foldedBadge(ids: string[], q: NavQuery, readOnly: boolean): number | null {
  const red = ids.map((id) => navBadge(id, q, readOnly)).filter((b) => b.tone === "danger" || b.tone === "solidDanger");
  const sum = red.reduce((n, b) => n + (b.count ?? 0), 0);
  return sum > 0 ? sum : null;
}

/** The top bar's «需要你处理» number: the same to-do total as the sidebar's «问题»; nothing when it could not be counted. */
export function topBarCount(q: NavQuery): number | null {
  if (q.status !== "success" || !q.data?.attention) return null;
  return q.data.attention.total;
}
