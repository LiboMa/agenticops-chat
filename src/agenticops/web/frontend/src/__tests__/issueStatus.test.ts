import { describe, it, expect } from "vitest";
import en from "@/locales/en.json";
import zh from "@/locales/zh.json";
import { ISSUE_STATUSES } from "@/lib/issueStatus";

describe("ISSUE_STATUSES", () => {
  it("lists every IssueStatus once, and each has a label in both locales", () => {
    expect(new Set(ISSUE_STATUSES).size).toBe(ISSUE_STATUSES.length);
    expect([...ISSUE_STATUSES].sort()).toEqual([
      "acknowledged", "dismissed", "fix_approved", "fix_executed", "fix_executing", "fix_planned",
      "investigating", "open", "resolved", "root_cause_identified",
    ]);
    for (const s of ISSUE_STATUSES) {
      expect((en as Record<string, string>)[`issues.status.${s}`], s).toBeTruthy();
      expect((zh as Record<string, string>)[`issues.status.${s}`], s).toBeTruthy();
    }
  });
});
