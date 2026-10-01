import { describe, it, expect } from "vitest";
import { isSecurityIssue, resolveIssueScope } from "@/lib/issueScope";

describe("resolveIssueScope", () => {
  it.each([
    { param: null, scope: "ops" },
    { param: "ops", scope: "ops" },
    { param: "security", scope: "security" },
    { param: "all", scope: "all" },
    { param: "bogus", scope: "ops" },
  ])("$param -> $scope", ({ param, scope }) => {
    expect(resolveIssueScope(param)).toBe(scope);
  });
});

describe("isSecurityIssue", () => {
  it.each([
    { source: "security_poll", security: true },
    { source: "security_posture", security: true },
    { source: "securityXpoll", security: false },
    { source: "vuln_scan", security: false },
    { source: "", security: false },
    { source: undefined, security: false },
  ])("$source -> $security", ({ source, security }) => {
    expect(isSecurityIssue(source)).toBe(security);
  });
});
