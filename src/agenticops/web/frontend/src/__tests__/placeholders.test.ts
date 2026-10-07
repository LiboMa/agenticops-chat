import { describe, it, expect } from "vitest";
import { fillPlaceholders } from "@/lib/placeholders";

describe("fillPlaceholders", () => {
  it("fills each {name} from params", () => {
    expect(fillPlaceholders("RCA {conf} is below the gate {threshold}", { conf: "57%", threshold: "60%" }))
      .toBe("RCA 57% is below the gate 60%");
  });
  it("no params, or a placeholder params do not name, leaves the template as it is", () => {
    expect(fillPlaceholders("Run #{n} failed")).toBe("Run #{n} failed");
    expect(fillPlaceholders("Run #{n} by {by}", { n: "4" })).toBe("Run #4 by {by}");
  });
  it("a value is inserted as text: no $-patterns, and a placeholder inside a value is not filled again", () => {
    expect(fillPlaceholders("cost {v}", { v: "$& $1" })).toBe("cost $& $1");
    expect(fillPlaceholders("{a} / {b}", { a: "{b}", b: "x" })).toBe("{b} / x");
  });
});
