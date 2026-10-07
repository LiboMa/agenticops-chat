import type { IssueStatus } from "@/api/types";

/** Every HealthIssue status (models.HealthIssue, 10 states); a label lives at `issues.status.<status>`. */
export const ISSUE_STATUSES: readonly IssueStatus[] = [
  "open", "investigating", "acknowledged", "root_cause_identified", "fix_planned",
  "fix_approved", "fix_executing", "fix_executed", "resolved", "dismissed",
];
