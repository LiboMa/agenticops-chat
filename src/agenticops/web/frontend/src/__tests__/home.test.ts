import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { allowedRoute, homeTarget, loginPath, probeFor, safeNext, userKey } from "@/lib/home";

// The server (services/ui_preferences.allowed_route) reads the same cases: both sides must agree.
const cases = JSON.parse(readFileSync(resolve(__dirname, "../../../../../../tests/fixtures/ui_last_route_cases.json"), "utf8")) as {
  accept: string[]; reject: string[];
};

describe("allowedRoute — the places 'resume' may reopen", () => {
  it.each(cases.accept)("keeps %s", (route) => expect(allowedRoute(route)).toBe(true));
  it.each(cases.reject)("refuses %s", (route) => expect(allowedRoute(route)).toBe(false));
});

describe("safeNext — the login return route", () => {
  const origin = "https://ops.example.com";
  it("keeps an in-app path with its query and hash", () => {
    expect(safeNext("/app/issues/5?tab=x#plan", origin)).toBe("/app/issues/5?tab=x#plan");
    expect(safeNext("/app/changes/1", origin)).toBe("/app/changes/1");
    expect(safeNext("/app", origin)).toBe("/app");
  });
  it.each([
    null, "", "https://evil.example/app/chat", "//evil.example/app/chat", "/\\evil.example", "javascript:alert(1)",
    "/app/login", "/app/login?next=/app", "/api/settings", "/app/../api/settings", "/appx", "app/chat",
  ])("refuses %s", (next) => expect(safeNext(next, origin)).toBeNull());
  it("normalises traversal before deciding", () => {
    expect(safeNext("/app/chat/../issues", origin)).toBe("/app/issues");
    expect(safeNext("/app/%2e%2e/api", origin)).toBeNull();
  });
});

describe("loginPath", () => {
  it("carries where you were", () => {
    expect(loginPath({ pathname: "/app/issues/5", search: "?a=1", hash: "#plan" }))
      .toBe("/app/login?next=%2Fapp%2Fissues%2F5%3Fa%3D1%23plan");
  });
  it("never nests the login page or carries the bare home", () => {
    expect(loginPath({ pathname: "/app/login", search: "?next=x", hash: "" })).toBe("/app/login");
    expect(loginPath({ pathname: "/app", search: "", hash: "" })).toBe("/app/login");
  });
});

describe("homeTarget — what /app opens", () => {
  it("a pinned home wins over the last place", () => {
    expect(homeTarget({ home: "reports" }, "/app/issues/4")).toBe("/app/reports");
    expect(homeTarget({ home: "issues" }, null)).toBe("/app/issues");
    expect(homeTarget({ home: "chat" }, "/app/issues/4")).toBe("/app/chat");
  });
  it("resume reopens the last allow-listed place, else Chat", () => {
    expect(homeTarget({ home: "resume" }, "/app/issues/4")).toBe("/app/issues/4");
    expect(homeTarget({ home: "resume" }, "https://evil.example")).toBe("/app/chat");
    expect(homeTarget({ home: "resume" }, null)).toBe("/app/chat");
    expect(homeTarget(null, null)).toBe("/app/chat");  // first visit, or bootstrap failed
  });
});

describe("probeFor — objects checked before they are reopened", () => {
  it("knows the four reopenable objects and their lists", () => {
    expect(probeFor("/app/issues/4")).toEqual({ api: "/health-issues/4", list: "/app/issues" });
    expect(probeFor("/app/changes/3")).toEqual({ api: "/changes/3", list: "/app/changes" });
    expect(probeFor("/app/plans/12")).toEqual({ api: "/fix-plans/12", list: "/app/plans" });
    expect(probeFor("/app/reports/7")).toEqual({ api: "/reports/7", list: "/app/reports" });
    expect(probeFor("/app/chat/abc-1")).toEqual({ api: "/chat/sessions/abc-1", list: "/app/chat" });
  });
  it("lists and other pages need no probe", () => {
    expect(probeFor("/app/issues")).toBeNull();
    expect(probeFor("/app/resources/12")).toBeNull();
  });
});

describe("userKey", () => {
  it("namespaces a local key by the signed-in user", () => {
    expect(userKey("aiops-last-route", 7)).toBe("aiops-last-route:7");
    expect(userKey("aiops-last-route", null)).toBe("aiops-last-route:anon");
  });
});
