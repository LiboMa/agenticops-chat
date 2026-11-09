import { describe, expect, it } from "vitest";
import zh from "@/locales/zh.json";
import { diagnosisRows } from "@/lib/diagnosisEvidence";

const t = (k: string) => (zh as Record<string, string>)[k] ?? k;
const rca = (over = {}) => ({ confidence: 0.45, evidence_verified: true, critic_verdict: "refuted", human_verdict: null, ...over });

/** The first screen before any run (MVP-2.8.0 S2). Spec: the machine's confidence, the critic's conclusion and the
 *  human verdict are said apart, never folded into one number (S2 review: a refuted 0.9 read «模型置信度 45%»). */
describe("diagnosisRows", () => {
  it("the model's own confidence, the critic and the person — three facts", () => {
    const rows = diagnosisRows({ anchorStatus: "anchored", rcaState: "ready", rca: rca() }, t);
    expect(rows.map((r) => r.text)).toEqual(["已定位到资源", "模型置信度 90%", "评审员：否定", "还没有人工裁决"]);
    expect(rows.map((r) => r.tone)).toEqual(["ok", "info", "danger", "neutral"]);
  });
  it("a supported critic and a human verdict", () => {
    const rows = diagnosisRows({ anchorStatus: "unanchored", rcaState: "ready",
                                 rca: rca({ confidence: 0.8, critic_verdict: "supported", human_verdict: "correct" }) }, t);
    expect(rows.map((r) => r.text)).toEqual(["还没有定位到具体资源", "模型置信度 80%", "评审员：支持", "人工裁决：诊断正确"]);
  });
  it("while the RCA loads, or after it failed: says so — never «还没有人工裁决»", () => {
    const loading = diagnosisRows({ anchorStatus: "anchored", rcaState: "loading", rca: undefined }, t).map((r) => r.text);
    expect(loading).toEqual(["已定位到资源", t("workitem.evidence.rcaLoading")]);
    const failed = diagnosisRows({ anchorStatus: "anchored", rcaState: "failed", rca: undefined }, t);
    expect(failed.map((r) => r.text)).toEqual(["已定位到资源", t("workitem.evidence.rcaFailed")]);
    expect(failed[1].tone).toBe("danger");
  });
  it("no RCA yet: no confidence or critic line; nobody has given a verdict", () => {
    expect(diagnosisRows({ anchorStatus: "anchored", rcaState: "ready", rca: null }, t).map((r) => r.text))
      .toEqual(["已定位到资源", "还没有人工裁决"]);
  });
});
