/** Old links into the work-item pages (spec §3): IssueDetail's ?tab= and the Issues hub's ?view=. */
export const ISSUE_HASHES = ["diagnose", "plan", "run", "accept", "activity"] as const;
export const CHANGE_HASHES = ["request", "review", "plan", "run", "accept", "activity"] as const;

const ISSUE_TAB_TO_HASH: Record<string, string> = {
  investigate: "diagnose", issue: "diagnose", fixPlan: "plan", execution: "run", verification: "accept", timeline: "activity",
};

export function legacyIssueTabHash(tab: string | null): string | null {
  return tab != null && Object.prototype.hasOwnProperty.call(ISSUE_TAB_TO_HASH, tab) ? ISSUE_TAB_TO_HASH[tab] : null;
}

export function parseHash(hash: string, allowed: readonly string[]): string | null {
  const h = hash.replace(/^#/, "");
  return allowed.includes(h) ? h : null;
}

export function legacyIssuesViewRedirect(search: string): string | null {
  const q = new URLSearchParams(search);
  const v = q.get("view");
  if (v !== "resources" && v !== "signals") return null;
  q.delete("view");
  const rest = q.toString();
  return `/app/${v}${rest ? `?${rest}` : ""}`;
}
