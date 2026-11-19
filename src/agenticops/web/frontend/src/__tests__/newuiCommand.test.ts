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
const base = { t, waiting, lens: "decide" as const, canSettings: true, canUsers: true, hosts: true };
const rows = (q: string, f?: SearchResponse) => commandRows(q, { ...base, found: f });
const ids = (list: CommandRow[]) => list.map((r) => r.id);

describe("commandRows — what the command bar offers for what was typed", () => {
  it("with nothing typed: where you can go, and what you can switch", () => {
    expect(ids(rows(""))).toEqual(["go:decide", "go:live", "go:world", "go:items", "do:theme", "do:help", "page:chat", "page:reports"]);
    expect(rows("")).toHaveLength(COMMAND_MAX);
  });

  it("a lens row goes to that lens; a page row to its page — every page the app has", () => {
    const all = commandRows("/", { ...base, found: undefined }, 99);
    expect(all.find((r) => r.id === "go:world")).toMatchObject({ to: "/app/new/world", hint: "3" });
    expect(all.find((r) => r.id === "go:items")).toMatchObject({ to: "/app/new/items" });
    expect(all.filter((r) => r.id.startsWith("page:")).map((r) => r.to)).toEqual(
      ["/app/chat", "/app/reports", "/app/resources", "/app/schedules", "/app/skills", "/app/security", "/app/plans", "/app/overview",
       "/app/agent-metrics", "/app/signals", "/app/users", "/app/settings", "/app/account/api-keys"]);
  });

  it("a page row says «classic» only when the page will open in the classic interface", () => {
    // the person chose the new interface: the page opens under NewUI's frame, there is nothing to warn of
    const hosted = commandRows("/", { ...base, found: undefined, hosts: true }, 99).filter((r) => r.id.startsWith("page:"));
    expect(hosted.length).toBeGreaterThan(10);
    expect(hosted.every((r) => r.hint === undefined)).toBe(true);
    // a visit to NewUI from the classic interface: the row leaves NewUI, and says so
    const leaves = commandRows("/", { ...base, found: undefined, hosts: false }, 99).filter((r) => r.id.startsWith("page:"));
    expect(leaves).toHaveLength(hosted.length);
    expect(leaves.every((r) => r.hint === "cmd.classic")).toBe(true);
  });

  it("does not offer a page the person may not open: Settings and Users", () => {
    const all = (can: { canSettings: boolean; canUsers: boolean }) => ids(commandRows("/", { ...base, found: undefined, ...can }, 99));
    expect(all({ canSettings: true, canUsers: true })).toEqual(expect.arrayContaining(["page:settings", "page:users"]));
    expect(all({ canSettings: false, canUsers: true })).not.toContain("page:settings");
    expect(all({ canSettings: true, canUsers: false })).not.toContain("page:users");
    expect(all({ canSettings: false, canUsers: false })).toContain("page:security");          // every other row stays
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
    expect(ids(rows("scale"))).toEqual(["item:C3", "ask"]);
    expect(ids(rows("12"))).toEqual(["item:I12", "ask"]);
    expect(ids(rows("i#12"))).toEqual(["item:I12", "ask"]);
    expect(ids(rows("cmd.live"))).toEqual(["go:live", "ask"]);
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

describe("the last row of plain text: ask an agent (N19)", () => {
  const all = (q: string, f?: SearchResponse) => commandRows(q, { ...base, found: f }, 99);
  it("plain text of two characters or more ends with «ask an agent», carrying the text as typed", () => {
    const list = all("Why is the web tier slow?");
    // …to a NEW conversation: /app/chat alone resumes the last one, where the draft would not be seen
    expect(list[list.length - 1]).toMatchObject({ id: "ask", to: "/app/chat", state: { fresh: true }, draft: "Why is the web tier slow?" });
    expect(list[list.length - 1].label).toContain("Why is the web tier slow?");
  });
  it("a command, a thing, an empty or one-letter text have no such row", () => {
    for (const q of ["", " ", "x", "/the", "@ssh", "/", "@"]) expect(ids(all(q))).not.toContain("ask");
  });
  it("it keeps its place when the list is cut: the last of the eight", () => {
    const many = found({ issues: Array.from({ length: 20 }, (_, k) => hit("issue", 100 + k, `ssh ${k}`)) });
    const list = rows("ssh", many);
    expect(list).toHaveLength(COMMAND_MAX);
    expect(list[COMMAND_MAX - 1].id).toBe("ask");
  });
  it("it is there even when nothing else matches", () => {
    expect(ids(rows("nothing matches this at all"))).toEqual(["ask"]);
  });
});
