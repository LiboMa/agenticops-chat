import { describe, it, expect } from "vitest";
import { confidenceBreakdown, qualityBadges, unmatchedRefs } from "@/lib/rcaQuality";

describe("confidenceBreakdown", () => {
  it("I#1: 0.95 × 0.6 (evidence not verified) = 0.57, below 0.6 → gate not passed; a weak critic costs nothing", () => {
    const b = confidenceBreakdown({ confidence: 0.57, evidence_verified: false, critic_verdict: "weak" }, 0.6);
    expect(b).toEqual({ raw: 0.95, final: 0.57, evidencePenalty: true, criticPenalty: false, threshold: 0.6, gatePassed: false });
  });
  it("a refuted critic halves the confidence and fails the gate whatever the number", () => {
    const b = confidenceBreakdown({ confidence: 0.45, evidence_verified: true, critic_verdict: "refuted" }, 0.3);
    expect(b.raw).toBe(0.9);
    expect(b.criticPenalty).toBe(true);
    expect(b.gatePassed).toBe(false);
  });
  it("both penalties stack; raw is capped at 1", () => {
    expect(confidenceBreakdown({ confidence: 0.3, evidence_verified: false, critic_verdict: "refuted" }, 0.6).raw).toBe(1);
  });
  it("no penalty: raw = final; at the threshold the gate passes", () => {
    const b = confidenceBreakdown({ confidence: 0.6, evidence_verified: true, critic_verdict: "supported" }, 0.6);
    expect(b.raw).toBe(0.6);
    expect(b.gatePassed).toBe(true);
  });
  it("unknown threshold (settings not loaded) → gatePassed null; a missing confidence reads 0", () => {
    const b = confidenceBreakdown({ confidence: undefined as unknown as number, evidence_verified: null, critic_verdict: null }, undefined);
    expect(b.final).toBe(0);
    expect(b.threshold).toBeNull();
    expect(b.gatePassed).toBeNull();
  });
});

describe("qualityBadges", () => {
  it("plain-language keys and tones, the critic's notes as the hint", () => {
    expect(qualityBadges({ evidence_verified: false, critic_verdict: "weak", critic_notes: "thin evidence" })).toEqual([
      { key: "rca.quality.evidenceUnverified", tone: "bad", hint: null },
      { key: "rca.quality.critic.weak", tone: "warn", hint: "thin evidence" },
    ]);
    expect(qualityBadges({ evidence_verified: true, critic_verdict: "supported", critic_notes: null })).toEqual([
      { key: "rca.quality.evidenceVerified", tone: "ok", hint: null },
      { key: "rca.quality.critic.supported", tone: "ok", hint: null },
    ]);
  });
  it("an unknown or absent critic verdict adds no badge", () => {
    expect(qualityBadges({ evidence_verified: null, critic_verdict: "maybe", critic_notes: null })).toEqual([]);
  });
});

describe("unmatchedRefs", () => {
  it("the newest rca_evidence_check's unmatched_refs; a JSON-string detail is parsed; junk is ignored", () => {
    expect(unmatchedRefs([
      { event_type: "rca_evidence_check", detail: { unmatched_refs: ["old"] }, created_at: "2026-10-03T03:40:00" },
      { event_type: "rca_critic", detail: { verdict: "weak" }, created_at: "2026-10-03T03:41:00" },
      { event_type: "rca_evidence_check", detail: JSON.stringify({ unmatched_refs: ["PATCH …/scale", 7] }) as unknown as Record<string, unknown>, created_at: "2026-10-03T03:41:30" },
    ])).toEqual(["PATCH …/scale"]);
    expect(unmatchedRefs(undefined)).toEqual([]);
    expect(unmatchedRefs([{ event_type: "rca_evidence_check", detail: null, created_at: "x" }])).toEqual([]);
  });
});
