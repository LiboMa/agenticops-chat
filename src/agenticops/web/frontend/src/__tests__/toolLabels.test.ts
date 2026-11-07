import { describe, it, expect } from "vitest";
import { toolLabelKey } from "@/lib/toolLabels";

describe("toolLabelKey", () => {
  it("names the known steps, leaves the rest to their raw name", () => {
    expect(toolLabelKey("rca_agent")).toBe("chat.tool.rca_agent");
    expect(toolLabelKey("enhanced_task")).toBe("chat.tool.enhanced_task");
    expect(toolLabelKey("get_health_issue")).toBeNull();
  });
});
