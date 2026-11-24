import { describe, expect, it } from "vitest";
import { reachView } from "@/lib/reachability";

/** A finding's reachability on the security page. E2E (S2 rework): finding #48 carries an object
 *  ({rdp_groups_attached_enis: 0, …_public_ips: 0}); rendered as a React child it blanked the whole app. */
describe("reachView", () => {
  it("the three states are words with their tone", () => {
    expect(reachView("reachable")).toEqual({ key: "security.reach.reachable", text: null, tone: "danger" });
    expect(reachView("not_reachable")).toEqual({ key: "security.reach.not_reachable", text: null, tone: "ok" });
    expect(reachView("undetermined")).toEqual({ key: "security.reach.undetermined", text: null, tone: "warn" });
  });
  it("a string it does not know is shown as written", () => {
    expect(reachView("n/a")).toEqual({ key: null, text: "n/a", tone: "neutral" });
  });
  it("anything that is not a string (an object, a number, a list) reads as undetermined — never rendered raw", () => {
    for (const v of [{ rdp_groups_attached_enis: 0 }, 3, ["a"], true]) {
      expect(reachView(v)).toEqual({ key: "security.reach.undetermined", text: null, tone: "warn" });
    }
  });
  it("nothing → nothing to show", () => {
    expect(reachView(null)).toBeNull();
    expect(reachView(undefined)).toBeNull();
    expect(reachView("")).toBeNull();
  });
});
