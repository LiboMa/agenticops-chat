import { describe, it, expect } from "vitest";
import { CHANGE_HASHES, ISSUE_HASHES, legacyInboxRedirect, legacyIssuesViewRedirect, legacyIssueTabHash, parseHash } from "@/lib/workitemRoutes";

describe("legacyIssueTabHash", () => {
  it("maps every old ?tab= to its phase; the pre-2.6.1 'issue' tab to diagnose; unknown → null", () => {
    expect(["investigate", "fixPlan", "execution", "verification", "timeline", "issue"].map(legacyIssueTabHash))
      .toEqual(["diagnose", "plan", "run", "accept", "activity", "diagnose"]);
    expect(legacyIssueTabHash("bogus")).toBeNull();
    expect(legacyIssueTabHash(null)).toBeNull();
  });
});
describe("parseHash", () => {
  it("accepts a known anchor with or without '#'; anything else is null", () => {
    expect(parseHash("#accept", ISSUE_HASHES)).toBe("accept");
    expect(parseHash("review", CHANGE_HASHES)).toBe("review");
    expect(parseHash("#review", ISSUE_HASHES)).toBeNull();
    expect(parseHash("#foo", ISSUE_HASHES)).toBeNull();
    expect(parseHash("", ISSUE_HASHES)).toBeNull();
  });
});
describe("legacyIssuesViewRedirect", () => {
  it("?view=resources|signals → the new page, other params kept; anything else stays", () => {
    expect(legacyIssuesViewRedirect("?view=resources&type=EC2")).toBe("/app/resources?type=EC2");
    expect(legacyIssuesViewRedirect("view=signals")).toBe("/app/signals");
    expect(legacyIssuesViewRedirect("?scope=security")).toBeNull();
    expect(legacyIssuesViewRedirect("?view=issues")).toBeNull();
    expect(legacyIssuesViewRedirect("")).toBeNull();
  });
});

describe("legacyInboxRedirect — the old workbench address lands on Issues · 在等我 (MVP-2.8.0)", () => {
  it("keeps the search and a valid item, drops the workbench's own tab and layout", () => {
    expect(legacyInboxRedirect("?decision=failed&q=web&item=C3&layout=compact")).toBe("/app/issues?view=waiting&q=web&item=C3");
    expect(legacyInboxRedirect("?item=X9")).toBe("/app/issues?view=waiting");
    expect(legacyInboxRedirect("")).toBe("/app/issues?view=waiting");
  });
});

