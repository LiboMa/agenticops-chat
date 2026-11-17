import { describe, expect, it } from "vitest";
import type { SearchResponse, SearchResultItem } from "@/api/types";
import type { AttentionItem } from "@/lib/attention";
import { COMMAND_MAX, commandRows, moveRow, searchText, type CommandRow } from "@/newui/lib/command";

const t = (k: string) => k;
const item = (id: string, title: string): AttentionItem => ({
  id, ref: `${id[0]}#${id.slice(1)}`, reason: "approval_required", reason_detail: null, title,
  entity: { entity_type: id[0] === "C" ? "change_request" : "fix_plan", entity_id: 1, content_version: null },
  account_id: 1, occurred_at: "2026-11-17T08:00:00Z", route: "/app/issues/1", available_actions: [],
});
const hit = (entity_type: SearchResultItem["entity_type"], id: number, title: string, over: Partial<SearchResultItem> = {}): SearchResultItem =>
  ({ id, title, subtitle: "", entity_type, ...over });
const found = (over: Partial<SearchResponse["results"]> = {}): SearchResponse =>
  ({ query: "x", results: { issues: [], fix_plans: [], reports: [], resources: [], ...over } });
const waiting = [item("I12", "SSH open to the world"), item("C3", "Scale out the web tier")];
const rows = (q: string, f?: SearchResponse) => commandRows(q, { t, waiting, found: f, lens: "decide", canSettings: true });
const ids = (list: CommandRow[]) => list.map((r) => r.id);

describe("commandRows — what the command bar offers for what was typed", () => {
  it("with nothing typed: where you can go, and what you can switch", () => {
    expect(ids(rows(""))).toEqual(["go:decide", "go:live", "go:world", "do:theme", "do:help", "classic:chat", "classic:reports", "classic:resources"]);
    expect(rows("")).toHaveLength(COMMAND_MAX);
  });

  it("a lens row goes to that lens; a classic row leaves for the classic page and says so", () => {
    const all = commandRows("/", { t, waiting, found: undefined, lens: "decide", canSettings: true }, 99);
    expect(all.find((r) => r.id === "go:world")).toMatchObject({ to: "/app/new/world", hint: "3" });
    expect(all.find((r) => r.id === "classic:settings")).toMatchObject({ to: "/app/settings", hint: "cmd.classic" });
    expect(all.filter((r) => r.id.startsWith("classic:")).map((r) => r.to)).toEqual(
      ["/app/chat", "/app/reports", "/app/resources", "/app/schedules", "/app/skills", "/app/security", "/app/settings"]);
  });

  it("does not offer a page the person may not open: Settings for a read-only account without it", () => {
    const all = (canSettings: boolean) => ids(commandRows("/", { t, waiting, found: undefined, lens: "decide", canSettings }, 99));
    expect(all(true)).toContain("classic:settings");
    expect(all(false)).not.toContain("classic:settings");
    expect(all(false)).toContain("classic:security");                       // every other row stays
  });

  it("«/» lists commands only, filtered by what follows", () => {
    expect(ids(rows("/全"))).toEqual([]);                                   // the test's words are the keys themselves
    expect(ids(rows("/cmd.world"))).toEqual(["go:world"]);
    expect(rows("/").every((r) => !r.id.startsWith("item:") && !r.id.startsWith("found:"))).toBe(true);
  });

  it("«@» lists things only: what waits on you, then what the search found", () => {
    const list = rows("@ssh", found({ issues: [hit("issue", 12, "SSH open to the world"), hit("issue", 40, "ssh brute force")],
                                     resources: [hit("resource", 7, "ssh-bastion")] }));
    expect(ids(list)).toEqual(["item:I12", "found:issue:40", "found:resource:7"]);      // I#12 once, as the item it is
    expect(list[0]).toMatchObject({ to: "/app/new/decide/I12", label: "I#12　SSH open to the world" });
    expect(list[1]).toMatchObject({ to: "/app/new/story/I40", state: { from: "decide", back: "/app/new/decide" } });
    expect(list[2]).toMatchObject({ to: "/app/new/world?sel=7" });
  });

  it("opens each kind of thing where NewUI has a page for it, the classic page where it has none", () => {
    const list = rows("@x", found({
      issues: [hit("issue", 1, "x")], resources: [hit("resource", 2, "x")], reports: [hit("report", 3, "x")],
      fix_plans: [hit("fix_plan", 4, "x"), hit("change_plan", 5, "x", { parent_id: 9 })], change_requests: [hit("change_request", 6, "x")],
    }));
    expect(list.map((r) => [r.id, r.to])).toEqual([
      ["found:issue:1", "/app/new/story/I1"], ["found:change_request:6", "/app/new/story/C6"], ["found:resource:2", "/app/new/world?sel=2"],
      ["found:fix_plan:4", "/app/plans/4"], ["found:change_plan:5", "/app/new/story/C9"], ["found:report:3", "/app/reports/3"],
    ]);
  });

  it("plain text matches commands and things alike; a number finds the item with that number", () => {
    expect(ids(rows("scale"))).toEqual(["item:C3"]);
    expect(ids(rows("12"))).toEqual(["item:I12"]);
    expect(ids(rows("i#12"))).toEqual(["item:I12"]);
    expect(ids(rows("cmd.live"))).toEqual(["go:live"]);
  });

  it("never lists more than eight rows", () => {
    const many = found({ issues: Array.from({ length: 20 }, (_, k) => hit("issue", 100 + k, `x ${k}`)) });
    expect(rows("@x", many)).toHaveLength(COMMAND_MAX);
  });
});

describe("searchText — what is sent to the search", () => {
  it("is the text without its sign, and nothing for a command or a text too short to mean anything", () => {
    expect(searchText("@ssh")).toBe("ssh");
    expect(searchText("ssh bastion")).toBe("ssh bastion");
    expect(searchText("/theme")).toBe("");
    expect(searchText("@")).toBe("");
    expect(searchText("a")).toBe("");
    expect(searchText("  ")).toBe("");
  });
});

describe("moveRow — the arrow keys in the list", () => {
  it("goes round the ends, and stays put in an empty list", () => {
    expect(moveRow(3, 0, -1)).toBe(2);
    expect(moveRow(3, 2, 1)).toBe(0);
    expect(moveRow(0, 0, 1)).toBe(0);
  });
});
