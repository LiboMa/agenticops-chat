import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { issuePhases } from "@/lib/issuePhases";
import { changePhases } from "@/lib/changePhases";
import { inFlightAutoRun, notQueuedFrom } from "@/lib/issueDetail";

// services/work_phases.py reads the same files: the server's "who it waits on" must be the page's.
const read = (f: string): unknown => JSON.parse(readFileSync(resolve(__dirname, `../../../../../../tests/fixtures/${f}`), "utf8"));
type Exp = { sub: string; waitingFor: string | null; primary: string | null };
type Ev = Parameters<typeof inFlightAutoRun>[0] & Parameters<typeof notQueuedFrom>[0];
const phases = read("work_item_phase_cases.json") as {
  issue: { name: string; input: Parameters<typeof issuePhases>[0]; expect: Exp }[];
  change: { name: string; input: Parameters<typeof changePhases>[0]; expect: Exp }[];
};
const auto = read("auto_run_cases.json") as {
  in_flight: { name: string; events: NonNullable<Ev>; plan_id: number; now: string; timeout_seconds: number; expect: string | null }[];
  not_queued: { name: string; events: NonNullable<Ev>; plan: { id: number; approved_at: string | null }; expect: string | null }[];
};

describe("work-item phases — shared with the server", () => {
  it.each(phases.issue)("issue: $name", (c) => {
    const p = issuePhases(c.input);
    expect({ sub: p.sub, waitingFor: p.waitingFor, primary: p.primary }).toEqual(c.expect);
  });
  it.each(phases.change)("change: $name", (c) => {
    const p = changePhases(c.input);
    expect({ sub: p.sub, waitingFor: p.waitingFor, primary: p.primary }).toEqual(c.expect);
  });
  it.each(auto.in_flight)("auto-run in flight: $name", (c) => {
    expect(inFlightAutoRun(c.events, c.plan_id, { timeoutSeconds: c.timeout_seconds, now: Date.parse(c.now) })?.startedAt ?? null).toBe(c.expect);
  });
  it.each(auto.not_queued)("not queued from: $name", (c) => {
    expect(notQueuedFrom(c.events, c.plan)).toBe(c.expect === null ? 0 : Date.parse(c.expect));
  });
});
