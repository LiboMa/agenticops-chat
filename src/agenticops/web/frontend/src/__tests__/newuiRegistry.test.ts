import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { BRIEFS } from "@/newui/decide/briefs/registry";
import { BRIEF_KINDS } from "@/newui/lib/briefKind";

const shared = JSON.parse(readFileSync(resolve(__dirname, "../../../../../../tests/fixtures/attention_brief_kinds.json"), "utf8")) as
  { rows: { kind: "issue" | "change"; reason: string; reason_detail: string | null; brief: keyof typeof BRIEFS }[] };

describe("every situation the server can send has a page of its own", () => {
  it("has a component for each row of the shared table, for the kind of work item it is", () => {
    const missing = shared.rows.filter((r) => typeof BRIEFS[r.brief]?.[r.kind] !== "function").map((r) => `${r.kind} / ${r.reason} / ${r.reason_detail}`);
    expect(missing).toEqual([]);
  });

  it("registers every brief kind, and nothing else", () => {
    expect(Object.keys(BRIEFS).sort()).toEqual([...BRIEF_KINDS].sort());
  });
});
