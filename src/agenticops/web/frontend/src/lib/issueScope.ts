/** The issue list's three views. The filter runs on the server (`GET /api/issues?scope=`) because the list is paged. */
export type IssueScope = "ops" | "security" | "all";
export const ISSUE_SCOPES: readonly IssueScope[] = ["ops", "security", "all"];

// Mirrors web/app.py SECURITY_SOURCE_PREFIX: the security review engine's issues carry a `security_*` source.
const SECURITY_SOURCE_PREFIX = "security_";

/** The view for a `?scope=` value; ops events are the default. */
export function resolveIssueScope(param: string | null): IssueScope {
  return param === "security" || param === "all" ? param : "ops";
}

export const isSecurityIssue = (source: string | null | undefined) =>
  !!source && source.startsWith(SECURITY_SOURCE_PREFIX);
