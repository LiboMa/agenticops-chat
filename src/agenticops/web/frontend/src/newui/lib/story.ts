import type { FixExecution, FixPlan, PipelineEvent, RCAResult } from "@/api/types";
import type { ChangePhaseId, ChangeSub } from "@/lib/changePhases";
import { formatElapsed, parseApiDate } from "@/lib/formatDate";
import type { IssueSub, WaitingFor } from "@/lib/issuePhases";
import { runSummary } from "@/lib/runSummary";
import { planHead, stepsVm } from "./briefs/plan";

/** «经过»: one item from the moment it was found to its acceptance, as six steps on a spine. Where the item stands
 *  comes from the classic pages' own rules (lib/issuePhases, lib/changePhases) — this file only lays their answer
 *  out on the six steps of the design (the classic pages draw four and five). */

export type SpineState = "done" | "now" | "bad" | "closed" | "todo";
export interface SpineStep<S extends string = string> { id: S; state: SpineState }

export const ISSUE_STEPS = ["found", "rca", "plan", "approve", "run", "accept"] as const;
export type IssueStep = (typeof ISSUE_STEPS)[number];
export const CHANGE_STEPS = ["request", "review", "plan", "approve", "run", "accept"] as const;
export type ChangeStep = (typeof CHANGE_STEPS)[number];

/** What the issue's own data shows it has reached: a diagnosis, a plan, an approval, a run. */
export interface Reached { rca: boolean; plan: boolean; approved: boolean; run: boolean }

function lay<S extends string>(steps: readonly S[], at: S, state: SpineState): SpineStep<S>[] {
  const i = steps.indexOf(at);
  return steps.map((id, k) => ({ id, state: k < i ? "done" : k === i ? state : "todo" }));
}

const ISSUE_AT: Partial<Record<IssueSub, [IssueStep, SpineState]>> = {
  running: ["rca", "now"], needsReview: ["rca", "now"], reviewOrPlan: ["rca", "now"], rcaUnavailable: ["rca", "now"], rcaRejected: ["rca", "bad"],
  toGenerate: ["plan", "now"], planRejected: ["plan", "bad"],
  awaitingApproval: ["approve", "now"],
  executing: ["run", "now"], checkingRun: ["run", "now"], runStateUnavailable: ["run", "now"], notQueued: ["run", "bad"], needsNewPlan: ["run", "bad"],
  awaitingAcceptance: ["accept", "now"], passed: ["accept", "now"], unverified: ["accept", "now"],
};

const furthest = (r: Reached): IssueStep => (r.run ? "run" : r.approved ? "approve" : r.plan ? "plan" : r.rca ? "rca" : "found");

export function issueSpine(sub: IssueSub, reached: Reached): SpineStep<IssueStep>[] {
  if (sub === "resolved") return ISSUE_STEPS.map((id) => ({ id, state: "done" }));
  if (sub === "dismissed") return lay(ISSUE_STEPS, furthest(reached), "closed");       // it stops where it had got to
  const at = ISSUE_AT[sub];
  if (at) return lay(ISSUE_STEPS, at[0], at[1]);
  // a state this page does not know (a newer server, or data still loading): what there is data for reads done
  const last = ISSUE_STEPS.indexOf(furthest(reached));
  return ISSUE_STEPS.map((id, k) => ({ id, state: k <= last ? "done" : "todo" }));
}

/** `current` is the classic page's phase (its «run» covers the approval); `approved` tells the two apart. */
export function changeSpine(sub: ChangeSub, current: ChangePhaseId, approved: boolean): SpineStep<ChangeStep>[] {
  switch (sub) {
    case "draft": return lay(CHANGE_STEPS, "request", "now");
    case "reviewing":
    case "needsClarification": return lay(CHANGE_STEPS, "review", "now");
    case "awaitingApproval": return lay(CHANGE_STEPS, "approve", "now");
    case "notQueued": return lay(CHANGE_STEPS, "run", "bad");
    case "executing": return lay(CHANGE_STEPS, "run", "now");
    case "awaitingAcceptance": return lay(CHANGE_STEPS, "accept", "now");
    case "completed": return CHANGE_STEPS.map((id) => ({ id, state: "done" }));
    case "failed":
    case "rolledBack": return lay(CHANGE_STEPS, "run", "bad");
    case "rejected":
    case "cancelled": {
      const at: ChangeStep = current === "request" ? "request" : current === "review" ? "review" : approved ? "run" : "approve";
      return lay(CHANGE_STEPS, at, "closed");
    }
    default: return CHANGE_STEPS.map((id, k) => ({ id, state: k === 0 ? "done" : "todo" }));
  }
}

export type WaitKey = "wait.you" | "wait.person" | "wait.agent" | "wait.agentIdle" | "wait.executor" | "wait.none";

/** The status line's «who it waits on». «You» only when the item is on this person's own list — an approval
 *  somebody else must give waits on a person, not on you. «An agent is on it» only when the server's record shows
 *  one at work (`agentAtWork`; null = that record is not loaded, so nothing is said): hundreds of open issues wait
 *  for an agent that nobody started. */
export function waitKey(waitingFor: WaitingFor, mine: boolean, agentAtWork: boolean | null): WaitKey | null {
  if (waitingFor === null) return "wait.none";
  if (waitingFor === "rca_agent" || waitingFor === "sre_agent") return agentAtWork === null ? null : agentAtWork ? "wait.agent" : "wait.agentIdle";
  if (waitingFor === "executor") return "wait.executor";
  return mine ? "wait.you" : "wait.person";
}

/** An item's «经过» page. */
export const storyPath = (item: string): string => `/app/new/story/${encodeURIComponent(item)}`;

export interface StoryOrigin { from: "decide" | "live" | "world"; back: string }

/** Where the page was opened from (the router's state): the lens, and the address its way back leads to. A direct
 *  link has none — and an address that is not NewUI's own is never a way back. */
export function storyOrigin(state: unknown): StoryOrigin | null {
  if (!state || typeof state !== "object") return null;
  const { from, back } = state as { from?: unknown; back?: unknown };
  if (from !== "decide" && from !== "live" && from !== "world") return null;
  return typeof back === "string" && /^\/app\/new\/(decide|live|world)(\/|\?|$)/.test(back) ? { from, back } : null;
}

const WAS_APPROVED: readonly string[] = ["approved", "executing", "executed", "failed"];

export function reachedOf(rca: unknown, plan: Pick<FixPlan, "status" | "approved_at"> | null | undefined, runs: unknown[] | undefined): Reached {
  return { rca: !!rca, plan: !!plan, approved: !!plan && (!!plan.approved_at || WAS_APPROVED.includes(plan.status)), run: !!runs?.length };
}

export interface PlanLine {
  version: number;
  hash8: string | null;
  steps: number;
  /** steps whose command the code classifies as changing something; null = the server sent no classification */
  writes: number | null;
  /** steps the code could not classify, or refuses */
  unclear: number;
}

export function planLine(plan: Pick<FixPlan, "steps" | "step_tiers" | "plan_version" | "content_hash" | "risk_level">): PlanLine {
  const steps = stepsVm(plan);
  const { version, hash8 } = planHead(plan);
  const known = steps.length > 0 && steps.every((s) => s.tier !== null);
  return {
    version, hash8, steps: steps.length,
    writes: known ? steps.filter((s) => s.tier === "write").length : null,
    unclear: known ? steps.filter((s) => s.tier === "unknown" || s.tier === "blocked").length : 0,
  };
}

export interface RunLine {
  id: number;
  /** the run's own status, as the server wrote it */
  status: string;
  /** it ended badly: failed, rolled back or aborted */
  bad: boolean;
  done: number;
  total: number;
  /** null = no duration on record */
  duration: string | null;
  at: string | null;
}

const BAD_RUN: readonly string[] = ["failed", "rolled_back", "aborted"];

export function runLine(run: FixExecution, runPlan: FixPlan | null): RunLine {
  const s = runSummary(run, runPlan);
  return {
    id: run.id, status: run.status, bad: BAD_RUN.includes(run.status), done: s.stepsDone, total: s.stepsTotal,
    duration: run.duration_ms > 0 ? formatElapsed(run.duration_ms) : null, at: run.started_at ?? run.created_at ?? null,
  };
}

const detailOf = (e: PipelineEvent): Record<string, unknown> => {
  let d: unknown = e.detail;
  if (typeof d === "string") { try { d = JSON.parse(d); } catch { return {}; } }
  return d !== null && typeof d === "object" && !Array.isArray(d) ? (d as Record<string, unknown>) : {};
};
const newer = (a: PipelineEvent, b: PipelineEvent) => (a.created_at ?? "").localeCompare(b.created_at ?? "") || a.id - b.id;

export interface Closure { by: string; at: string; reason: string }

/** What the status endpoint records as the reason when the person gave none (web/app.api_update_anomaly_status):
 *  the server's filler, not anybody's words — never quoted. */
const NO_REASON = "anomaly status update";

/** Who moved the issue to `to` last, when, and the reason recorded with the move (the timeline's `status_changed`). */
export function lastMove(events: PipelineEvent[] | undefined, to: string): Closure | null {
  const moves = (events ?? []).filter((e) => e.event_type === "status_changed" && detailOf(e).to === to).sort(newer);
  const last = moves[moves.length - 1];
  if (!last) return null;
  const reason = detailOf(last).reason;
  return { by: last.actor, at: last.created_at ?? "", reason: typeof reason === "string" && reason !== NO_REASON ? reason : "" };
}

/** Who dismissed the issue, when, and the reason they gave: the newest move to `dismissed`. */
export const closure = (events: PipelineEvent[] | undefined): Closure | null => lastMove(events, "dismissed");

export interface Note { id: number; by: string; at: string; text: string }

/** What people wrote on the issue, oldest first, exactly as written. */
export function notesOf(events: PipelineEvent[] | undefined): Note[] {
  return (events ?? []).filter((e) => e.event_type === "note_added").sort(newer).map((e) => {
    const content = detailOf(e).content;
    return { id: e.id, by: e.actor, at: e.created_at ?? "", text: typeof content === "string" ? content : "" };
  });
}

/** How a fix plan stands to the diagnosis the page shows.
 *  - older: the plan names another diagnosis — it was written from an earlier one.
 *  - rewritten: the plan names this diagnosis, yet its record is older than the diagnosis. A draft plan is updated in
 *    place and only a status move stamps `updated_at`, so the plan was rewritten after the diagnosis and nothing on
 *    record says when — its creation time would read as «planned before diagnosed».
 *  - unknown: no diagnosis, or a plan that names none: nothing is claimed. */
export function planBasis(
  plan: Pick<FixPlan, "rca_result_id" | "created_at" | "updated_at">, rca: Pick<RCAResult, "id" | "created_at"> | null | undefined,
): "current" | "older" | "rewritten" | "unknown" {
  if (!rca || plan.rca_result_id == null) return "unknown";
  if (plan.rca_result_id !== rca.id) return "older";
  const planAt = parseApiDate(plan.updated_at ?? plan.created_at)?.getTime(), rcaAt = parseApiDate(rca.created_at)?.getTime();
  return planAt !== undefined && rcaAt !== undefined && planAt < rcaAt ? "rewritten" : "current";
}
