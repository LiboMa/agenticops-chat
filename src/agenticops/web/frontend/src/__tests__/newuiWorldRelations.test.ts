import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { PROPAGATION, dotWays, engineEnds, flow, side } from "@/newui/lib/world/relations";

const shared = JSON.parse(readFileSync(resolve(__dirname, "../../../../../../tests/fixtures/relation_propagation.json"), "utf8")).propagation as Record<string, string>;

describe("the map's relation table is the back end's (tests/fixtures/relation_propagation.json)", () => {
  it("has exactly the same relation types and directions", () => {
    expect(PROPAGATION).toEqual(shared);
  });
});

describe("flow — which way a fault travels along a link written s → t", () => {
  it("follows the registry for a rule relation", () => {
    expect(flow({ r: "contains", p: "rule" })).toBe("forward");        // a VPC's fault reaches its subnets
    expect(flow({ r: "secured_by", p: "rule" })).toBe("reverse");      // a security group's fault reaches the instance it secures
    expect(flow({ r: "manages", p: "rule" })).toBe("both");
  });
  it("knows no direction for a relation a model inferred, whatever it is called", () => {
    expect(flow({ r: "secured_by", p: "llm" })).toBe("none");
    expect(flow({ r: "inferred_group", p: "llm" })).toBe("none");
  });
  it("knows no direction for a relation type the registry does not list", () => {
    expect(flow({ r: "member_of", p: "rule" })).toBe("none");
    expect(flow({ r: "something_new", p: "rule" })).toBe("none");
  });
});

describe("side — what the other end of a link is to the resource being looked at", () => {
  // `out` = the link is written from the resource to the other end
  it("contains: what it holds is downstream, what holds it is upstream", () => {
    expect(side({ r: "contains", p: "rule" }, true)).toBe("down");
    expect(side({ r: "contains", p: "rule" }, false)).toBe("up");
  });
  it("secured_by: its security group is upstream, what a group secures is downstream", () => {
    expect(side({ r: "secured_by", p: "rule" }, true)).toBe("up");
    expect(side({ r: "secured_by", p: "rule" }, false)).toBe("down");
  });
  it("a two-way relation is both; an inferred one is neither", () => {
    expect(side({ r: "manages", p: "rule" }, true)).toBe("both");
    expect(side({ r: "references", p: "llm" }, false)).toBe("inferred");
    expect(side({ r: "member_of", p: "rule" }, true)).toBe("unknown");
  });
});

describe("the moving dots run the way the card says — in both views", () => {
  // final review: the dots' direction lived inside each renderer's draw code, where no test could see it: a flip
  // passed every test. It is a function of its own now, checked against `side` for every relation type and both ends.
  const types = [...Object.keys(PROPAGATION), "member_of"];
  it("flat map: away from the open resource towards what is downstream of it, towards it from what is upstream", () => {
    for (const r of types) for (const out of [true, false]) {
      const e = { r, p: "rule" as const }, where = side(e, out), ways = dotWays(e, out);
      expect([r, out, ways]).toEqual([r, out, where === "down" ? [true] : where === "up" ? [false] : where === "both" ? [true, false] : []]);
    }
    expect(dotWays({ r: "contains", p: "llm" }, true)).toEqual([]);                    // an inferred relation has no direction
  });

  it("3D: the engine's particles run source → target, so a link is handed over in the direction a fault travels", () => {
    // written a → b. forward: a's fault reaches b (a → b). reverse: b's fault reaches a (b → a).
    expect(engineEnds({ r: "contains", p: "rule" }, 3, 9)).toEqual({ source: 3, target: 9, particles: true });
    expect(engineEnds({ r: "secured_by", p: "rule" }, 3, 9)).toEqual({ source: 9, target: 3, particles: true });
    for (const r of types) {
      const e = { r, p: "rule" as const }, ends = engineEnds(e, 3, 9);
      // seen from a (the link is written out of it): b is downstream exactly when the particles leave a
      if (ends.particles) expect([r, side(e, true)]).toEqual([r, ends.source === 3 ? "down" : "up"]);
      else expect([r, ["both", "unknown"].includes(side(e, true))]).toEqual([r, true]);
    }
    expect(engineEnds({ r: "contains", p: "llm" }, 3, 9).particles).toBe(false);
  });
});

