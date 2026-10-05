import { describe, it, expect } from "vitest";
import { openableCards, seedOpenCards, toggledCardHash } from "@/lib/phaseCards";
import { CHANGE_PHASES, type ChangePhaseId } from "@/lib/changePhases";
import { ISSUE_PHASES, type IssuePhaseId } from "@/lib/issuePhases";
import type { PhaseView } from "@/lib/issuePhases";

const issuePhases: PhaseView<IssuePhaseId>[] = [
  { id: "diagnose", state: "done" }, { id: "plan", state: "failed" }, { id: "run", state: "current" }, { id: "accept", state: "future" },
];
// a change that ended at ④: ⑤ is not drawn
const endedChange: PhaseView<ChangePhaseId>[] = [
  { id: "request", state: "done" }, { id: "review", state: "done" }, { id: "plan", state: "done" }, { id: "run", state: "failed" },
];

describe("seedOpenCards", () => {
  it("opens the current and every failed card; a done or future card stays closed", () => {
    expect([...seedOpenCards(issuePhases, ISSUE_PHASES, null)]).toEqual(["plan", "run"]);
  });
  it("also opens the card a link's hash names, done or not", () => {
    expect([...seedOpenCards(issuePhases, ISSUE_PHASES, "diagnose")].sort()).toEqual(["diagnose", "plan", "run"]);
  });
  it("a hash that is no card (the activity, an unknown anchor) opens nothing more", () => {
    expect([...seedOpenCards(issuePhases, ISSUE_PHASES, "activity")]).toEqual(["plan", "run"]);
    expect([...seedOpenCards(endedChange, CHANGE_PHASES, "bogus")]).toEqual(["run"]);
  });
});

describe("openableCards", () => {
  it("every reached card can be opened; a future one cannot", () => {
    expect(openableCards(issuePhases)).toEqual(["diagnose", "plan", "run"]);
    expect(openableCards(endedChange)).toEqual(["request", "review", "plan", "run"]);
    expect(openableCards<IssuePhaseId>([])).toEqual([]);
  });
});

describe("toggledCardHash", () => {
  it("opening a card names it in the hash", () => {
    expect(toggledCardHash("", "plan", true)).toBe("#plan");
    expect(toggledCardHash("#run", "plan", true)).toBe("#plan");
  });
  it("closing clears the hash only when it named that card", () => {
    expect(toggledCardHash("#plan", "plan", false)).toBe("");
    expect(toggledCardHash("#run", "plan", false)).toBe("#run");
    expect(toggledCardHash("", "plan", false)).toBe("");
  });
});
