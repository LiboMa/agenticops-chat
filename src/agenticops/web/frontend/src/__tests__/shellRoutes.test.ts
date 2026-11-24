import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { CLASSIC_EXIT, ROUTE_KINDS, frameMode, nativeTarget, sectionOf, stayClassic } from "@/lib/shellRoutes";

const app = readFileSync(resolve(__dirname, "../App.tsx"), "utf8");
const paths = [...app.matchAll(/<Route\b[^>]*?\bpath="([^"]+)"/g)].map((m) => m[1]);

describe("ROUTE_KINDS — every route of the app is accounted for in the new interface", () => {
  it("App.tsx declares routes (the test reads something)", () => {
    expect(paths.length).toBeGreaterThan(25);
    expect(paths).toContain("reports/:id");
    expect(paths).toContain("new/*");
  });
  it("every path= in App.tsx has a row", () => {
    const missing = [...new Set(paths)].filter((p) => !(p in ROUTE_KINDS));
    expect(missing).toEqual([]);
  });
  it("no row names a route that is gone", () => {
    const stale = Object.keys(ROUTE_KINDS).filter((p) => !paths.includes(p));
    expect(stale).toEqual([]);
  });
  it("a row is one of the four kinds", () => {
    for (const k of Object.values(ROUTE_KINDS)) expect(["hosted", "native", "lens", "outside"]).toContain(k);
  });
});

describe("frameMode — a lens, or a classic page under the new frame", () => {
  it("NewUI's own addresses are lenses", () => {
    for (const p of ["/app/new", "/app/new/decide", "/app/new/story/I12", "/app/new/items"]) expect(frameMode(p)).toBe("lens");
  });
  it("everything else is hosted", () => {
    for (const p of ["/app", "/app/reports", "/app/issues/12", "/app/chat/abc", "/app/newer"]) expect(frameMode(p)).toBe("hosted");
  });
});

describe("nativeTarget — a classic address that NewUI has its own page for", () => {
  it("an issue and a change open their story; the link keeps what it named", () => {
    expect(nativeTarget("/app/issues/12", "", "")).toBe("/app/new/story/I12");
    expect(nativeTarget("/app/issues/12", "?q=x&view=all", "#plan")).toBe("/app/new/story/I12");
    expect(nativeTarget("/app/issues/12/", "", "")).toBe("/app/new/story/I12");
    expect(nativeTarget("/app/changes/3", "", "#review")).toBe("/app/new/story/C3");
  });
  it("only a real number is an item", () => {
    for (const p of ["/app/issues/abc", "/app/issues/0", "/app/issues/12/extra", "/app/issues/1e3", "/app/changes/-1", "/app/changes/03"]) {
      expect(nativeTarget(p, "", "")).toBeNull();
    }
  });
  it("«waiting on me» is the Decide lens, with the item it had open", () => {
    expect(nativeTarget("/app/issues", "", "")).toBe("/app/new/decide");
    expect(nativeTarget("/app/issues", "?view=waiting", "")).toBe("/app/new/decide");
    expect(nativeTarget("/app/issues", "?view=mine", "")).toBe("/app/new/decide");
    expect(nativeTarget("/app/issues", "?view=waiting&item=I12", "")).toBe("/app/new/decide/I12");
    expect(nativeTarget("/app/issues", "?item=C3", "")).toBe("/app/new/decide/C3");
    expect(nativeTarget("/app/inbox", "", "")).toBe("/app/new/decide");
    expect(nativeTarget("/app/inbox", "?item=I7&q=x", "")).toBe("/app/new/decide/I7");
    expect(nativeTarget("/app/issues", "?item=%3Cscript%3E", "")).toBe("/app/new/decide");
  });
  it("the list of everything opens the «all items» table, with the filters the table can say (N18)", () => {
    // the classic «all» list with no status in its address is EVERY status (N27, review): so is the table it opens
    expect(nativeTarget("/app/issues", "?view=all", "")).toBe("/app/new/items?st=all");
    expect(nativeTarget("/app/issues", "?view=all&status=active", "")).toBe("/app/new/items");
    expect(nativeTarget("/app/issues", "?view=all&q=ssh&item=I12&status=all&sort=severity", "")).toBe("/app/new/items?st=all&q=ssh&sort=severity");
  });
  it("the «failed» view is the Decide lens with that filter; «waited long» is the lens itself (it has no such filter)", () => {
    expect(nativeTarget("/app/issues", "?view=failed", "")).toBe("/app/new/decide?f=failed");
    expect(nativeTarget("/app/issues", "?view=long_wait", "")).toBe("/app/new/decide");
  });
  it("a view NewUI has nothing for stays the classic page's to handle (the old ?view=resources / signals redirects)", () => {
    for (const view of ["resources", "signals", "whatever"]) expect(nativeTarget("/app/issues", `?view=${view}`, "")).toBeNull();
  });
  it("the map opens World, on the resource the link focused", () => {
    expect(nativeTarget("/app/galaxy", "", "")).toBe("/app/new/world");
    for (const focus of ["12", "R12", "R%2312", "res:12", "r12"]) expect(nativeTarget("/app/galaxy", `?focus=${focus}`, "")).toBe("/app/new/world?sel=12");
    expect(nativeTarget("/app/galaxy", "?focus=nope", "")).toBe("/app/new/world");
  });
  it("every other page is hosted as it is", () => {
    for (const p of ["/app", "/app/reports", "/app/reports/7", "/app/plans", "/app/plans/7", "/app/changes", "/app/audit", "/app/chat",
                     "/app/chat/abc", "/app/schedules/4", "/app/resources/12", "/app/signals", "/app/settings", "/app/users",
                     "/app/account/api-keys", "/app/overview", "/app/security", "/app/skills/x", "/app/agent-metrics", "/app/nope"]) {
      expect(nativeTarget(p, "", "")).toBeNull();
    }
  });
});

describe("stayClassic — the way out to a classic page stays open while the person is in that section", () => {
  const at = (pathname: string, state: unknown = null) => ({ pathname, state });
  it("a section is the issues, one change, or the map", () => {
    expect(sectionOf("/app/issues")).toBe("issues");
    expect(sectionOf("/app/issues/12")).toBe("issues");
    expect(sectionOf("/app/inbox")).toBe("issues");
    expect(sectionOf("/app/changes/3")).toBe("changes");
    expect(sectionOf("/app/galaxy")).toBe("galaxy");
    for (const p of ["/app/changes", "/app/reports", "/app/plans/3", "/app/new/decide", "/app/issuesx"]) expect(sectionOf(p)).toBeNull();
  });
  it("a link that says «classic» enters; a plain link does not", () => {
    expect(stayClassic(null, at("/app/issues/12", { classic: true }))).toBe("issues");
    expect(stayClassic(null, at("/app/galaxy", { classic: true }))).toBe("galaxy");
    expect(stayClassic(null, at("/app/issues/12"))).toBeNull();
    expect(stayClassic(null, at("/app/issues/12", { classic: "yes" }))).toBeNull();
    expect(stayClassic(null, at("/app/reports", { classic: true }))).toBeNull();
  });
  it("inside the section the classic pages keep linking to each other", () => {
    expect(stayClassic("issues", at("/app/issues"))).toBe("issues");
    expect(stayClassic("issues", at("/app/issues/13", { other: 1 }))).toBe("issues");
    expect(stayClassic("issues", at("/app/issues/13"))).toBe("issues");
  });
  it("leaving the section closes it: the next link opens NewUI's page again", () => {
    expect(stayClassic("issues", at("/app/changes/3"))).toBeNull();
    expect(stayClassic("issues", at("/app/reports"))).toBeNull();
    expect(stayClassic("galaxy", at("/app/issues/12"))).toBeNull();
    expect(stayClassic("issues", at("/app/new/decide"))).toBeNull();
  });
  it("asking twice gives the same answer (a render may run twice)", () => {
    const first = stayClassic(null, at("/app/issues/12", { classic: true }));
    expect(stayClassic(first, at("/app/issues/12", { classic: true }))).toBe(first);
  });
});

describe("NewUI's own exits to a classic page say so", () => {
  const read = (rel: string) => readFileSync(resolve(__dirname, "..", rel), "utf8");
  it("the state an exit carries is the one stayClassic reads", () => {
    expect(stayClassic(null, { pathname: "/app/issues/12", state: CLASSIC_EXIT })).toBe("issues");
  });
  // without it the link would be turned straight back to NewUI's own page: «open the classic page» on a story led to
  // the story, an item kind this client does not know could not be handled at all
  it.each([
    ["newui/story/StoryBits.tsx", "to={classicTo}"], ["newui/decide/GenericBrief.tsx", "to={route}"],
    ["newui/live/Stream.tsx", "to={classicRoute}"], ["newui/world/WorldPanels.tsx", 'to="/app/galaxy"'],
  ])("%s — the link %s", (file, to) => {
    const tags = [...read(file).matchAll(/<Link\b[^>]*>/g)].map((m) => m[0]).filter((tag) => tag.includes(to));
    expect(tags.length).toBeGreaterThan(0);
    for (const tag of tags) expect(tag).toContain("state={CLASSIC_EXIT}");
  });
});
