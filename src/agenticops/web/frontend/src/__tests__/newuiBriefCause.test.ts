import { describe, expect, it } from "vitest";
import { causeVm, pct } from "@/newui/lib/briefs/cause";
import type { RCAResult } from "@/api/types";

const rca = (over: Partial<RCAResult> = {}): RCAResult => ({
  id: 5, anomaly_id: 12, analysis_type: "rca", root_cause: "The group allows all traffic from anywhere.", confidence: 0.82,
  contributing_factors: [], recommendations: [], related_resources: [], model_id: "m", created_at: "2026-11-01T00:00:00Z", ...over,
});

describe("causeVm — the diagnosis as a brief shows it", () => {
  it("numbers the evidence E1 … En and keeps what the server stored: the kind, where it came from, the summary", () => {
    const vm = causeVm(rca({ evidence: [{ type: "aws_cli", ref: "describe-security-groups", summary: "0.0.0.0/0 on all ports" }, { type: "cloudtrail", ref: "evt-1", summary: "opened in March" }] }), 0.6)!;
    expect(vm.evidence).toEqual([
      { label: "E1", type: "aws_cli", ref: "describe-security-groups", summary: "0.0.0.0/0 on all ports" },
      { label: "E2", type: "cloudtrail", ref: "evt-1", summary: "opened in March" },
    ]);
    expect(vm.text).toBe("The group allows all traffic from anywhere.");
  });

  it("marks a confidence under the gate, and only then", () => {
    expect(causeVm(rca({ confidence: 0.59 }), 0.6)!.belowGate).toBe(true);
    expect(causeVm(rca({ confidence: 0.6 }), 0.6)!.belowGate).toBe(false);
    expect(causeVm(rca({ confidence: 0.3 }), null)!.belowGate).toBe(false);     // the gate is unknown: nothing is claimed
  });

  it("names the critic's verdict and the location's status only when it knows the value", () => {
    expect(causeVm(rca({ critic_verdict: "refuted", location_status: "partial" }), 0.6)).toMatchObject({ critic: "refuted", location: "partial" });
    expect(causeVm(rca({ critic_verdict: "brand_new", location_status: null }), 0.6)).toMatchObject({ critic: null, location: null });
    expect(causeVm(rca({}), 0.6)).toMatchObject({ critic: null, location: null, evidence: [], evidenceGrounded: null });
  });

  it("says whether the cited evidence was matched to the run's tool results", () => {
    expect(causeVm(rca({ evidence_verified: true }), 0.6)!.evidenceGrounded).toBe(true);
    expect(causeVm(rca({ evidence_verified: false }), 0.6)!.evidenceGrounded).toBe(false);
  });

  it("is null without a diagnosis", () => {
    expect(causeVm(null, 0.6)).toBeNull();
    expect(causeVm(undefined, 0.6)).toBeNull();
  });
});

describe("pct", () => {
  it("rounds a share to a whole percent; unknown is a dash", () => {
    expect(pct(0.824)).toBe("82%");
    expect(pct(1)).toBe("100%");
    expect(pct(null)).toBe("—");
    expect(pct(Number.NaN)).toBe("—");
  });
});
