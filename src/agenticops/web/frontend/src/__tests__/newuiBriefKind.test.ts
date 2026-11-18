import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { BRIEF_KINDS, briefKind, itemKind } from "@/newui/lib/briefKind";

const shared = JSON.parse(readFileSync(resolve(__dirname, "../../../../../../tests/fixtures/attention_brief_kinds.json"), "utf8")) as
  { briefs: string[]; rows: { kind: "issue" | "change"; reason: string; reason_detail: string | null; brief: string }[] };
const entity = (kind: "issue" | "change", reason: string) => ({
  entity_type: kind === "change" ? "change_request" : reason === "approval_required" || reason === "execution_not_started" ? "fix_plan" : "health_issue",
  entity_id: 1, content_version: null,
});

describe("briefKind — which page a waiting item gets (shared table with services/attention)", () => {
  it("knows the same briefs as the table", () => {
    expect([...BRIEF_KINDS]).toEqual(shared.briefs);
  });

  it("gives every row the server can send its brief", () => {
    expect(shared.rows.length).toBe(18);
    for (const r of shared.rows) {
      const item = { entity: entity(r.kind, r.reason), reason: r.reason, reason_detail: r.reason_detail };
      expect(itemKind(item), JSON.stringify(r)).toBe(r.kind);
      expect(briefKind(item), JSON.stringify(r)).toBe(r.brief);
    }
  });

  it("gives a row it does not know no brief (the page then shows the generic one)", () => {
    expect(briefKind({ entity: entity("issue", "x"), reason: "something_new", reason_detail: null })).toBeNull();
    expect(briefKind({ entity: entity("issue", "review_required"), reason: "review_required", reason_detail: "a_new_detail" })).toBeNull();
    expect(briefKind({ entity: entity("change", "review_required"), reason: "review_required", reason_detail: "rca_gate" })).toBeNull();
    expect(briefKind({ entity: entity("issue", "approval_required"), reason: "approval_required", reason_detail: "odd" })).toBeNull();
  });

  it("reads an issue's fix-plan rows as the issue's", () => {
    expect(itemKind({ entity: { entity_type: "fix_plan", entity_id: 9, content_version: 2 } })).toBe("issue");
    expect(itemKind({ entity: { entity_type: "health_issue", entity_id: 9, content_version: null } })).toBe("issue");
    expect(itemKind({ entity: { entity_type: "change_request", entity_id: 9, content_version: null } })).toBe("change");
  });
});
