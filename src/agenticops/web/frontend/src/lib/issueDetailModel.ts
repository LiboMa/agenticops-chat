import type { FixExecution, FixPlan, HealthIssue, IssueStatus, RCAResult } from "@/api/types";
import { issueStatuses, latestExecution, newestFirst } from "@/lib/issueDetail";
import { currentFixPlan, issuePhases, type IssuePhaseResult } from "@/lib/issuePhases";
import { confidenceBreakdown } from "@/lib/rcaQuality";

export interface ReasonRef { key: string; params?: Record<string, string> }
export type Reason = ReasonRef | { text: string };
export type IssueMenuItem = "runRca" | "skipReviewGeneratePlan" | "markResolved" | "dismiss" | "reopen" | "cancelRun";

export interface IssueDetailModel {
  phase: IssuePhaseResult;
  statusKey: string;
  tone: "info" | "warn" | "bad" | "ok";
  reason: Reason | null;
  waitingKey: string | null;
  primaryKey: string | null;
  menu: IssueMenuItem[];
  plan: FixPlan | null;
  otherPlans: FixPlan[];
  latestRun: FixExecution | null;
  pendingRun: FixExecution | null;
  quietRunError: boolean;     // the latest run's error_message IS the status line's sentence: ③ does not repeat it
  quietAcceptReason: boolean; // the latest run's verification_reason IS the status line's sentence: ④ does not repeat it
}

const pct = (x: number) => `${Math.round(x * 100)}%`;
// Where an issue stands at these statuses depends on its latest run, so it cannot be told while the runs are unknown
const RUN_DEPENDENT: ReadonlySet<IssueStatus> = new Set<IssueStatus>(["root_cause_identified", "fix_approved", "fix_executed"]);
const runText = (r: FixExecution | null) =>
  r ? r.acceptance_note || r.verification_reason || r.error_message || null : null;

/** IssueDetail's view model: everything the status line and the phase cards say, i18n-free (keys + data). */
export function issueDetailModel(input: {
  issue: Pick<HealthIssue, "status">;
  rca: RCAResult | null | undefined;
  threshold: number | null | undefined;
  plans: FixPlan[] | undefined;
  executions: FixExecution[] | undefined; // undefined = not known (still loading, or the fetch failed): never "no runs"
  runsFailed?: boolean;                   // with executions undefined: the fetch failed rather than still loading
}): IssueDetailModel {
  const { issue, rca, threshold } = input;
  const plan = currentFixPlan(input.plans);
  const latestRun = latestExecution(input.executions);
  // undefined (still loading) keeps list mode — never a flash of "rerun RCA"; null means there is no RCA
  // likewise runs not known yet are undefined, loaded-and-none is null
  const known = issuePhases({ status: issue.status, rca, threshold, plan,
                              latestRun: input.executions === undefined ? undefined : latestRun });
  const phase: IssuePhaseResult = input.executions === undefined && RUN_DEPENDENT.has(issue.status)
    ? { ...known, sub: input.runsFailed ? "runsUnavailable" : "loadingRuns", waitingFor: null, primary: null }
    : known;
  const pendingRun = issueStatuses(issue, input.executions).pending;

  let reason: Reason | null = null;
  switch (phase.sub) {
    case "needsReview":
      if (rca) {
        const b = confidenceBreakdown(rca, threshold);
        reason = b.criticPenalty ? { key: "workitem.reason.rcaRefuted" }
          : { key: "workitem.reason.rcaBelowGate", params: { conf: pct(b.final), threshold: pct(b.threshold ?? 0) } };
      } else reason = { key: "workitem.reason.noRca" };
      break;
    case "rcaRejected": reason = { key: "workitem.reason.rcaRejected" }; break;
    case "needsNewPlan": { const t = runText(latestRun); reason = t ? { text: t } : { key: "workitem.reason.runFailed" }; break; }
    case "notQueued": reason = { key: "workitem.reason.notQueued" }; break;
    case "awaitingAcceptance": { const t = runText(latestRun); reason = t ? { text: t } : null; break; }
    default: reason = null;
  }

  const terminal = issue.status === "resolved" || issue.status === "dismissed";
  const menu: IssueMenuItem[] = terminal ? ["reopen"] : [
    ...(phase.primary === "rerunRca" ? [] : ["runRca" as const]),
    // the backend generates a plan from an RCA: none (or not loaded yet) → not offered
    ...(issue.status === "root_cause_identified" && rca && phase.primary !== "generatePlan" ? ["skipReviewGeneratePlan" as const] : []),
    ...(phase.sub === "executing" && latestRun && (latestRun.status === "pending" || latestRun.status === "running") ? ["cancelRun" as const] : []),
    ...(phase.primary === "markResolved" ? [] : ["markResolved" as const]),
    "dismiss",
  ];

  const tone = phase.sub === "needsNewPlan" ? "bad"
    : ["needsReview", "rcaRejected", "notQueued", "awaitingAcceptance", "awaitingApproval", "unverified", "reviewOrPlan",
       "runsUnavailable"].includes(phase.sub) ? "warn"
    : phase.sub === "passed" || phase.sub === "resolved" ? "ok" : "info";

  const text = reason && "text" in reason ? reason.text : null;
  return {
    phase,
    statusKey: `workitem.sub.${phase.sub}`,
    tone,
    reason,
    waitingKey: phase.waitingFor ? `workitem.wait.${phase.waitingFor}` : null,
    primaryKey: phase.primary ? `workitem.primary.${phase.primary}` : null,
    menu,
    plan,
    otherPlans: newestFirstPlans(input.plans).filter((p) => p.id !== plan?.id),
    latestRun,
    pendingRun,
    quietRunError: text !== null && text === latestRun?.error_message,
    quietAcceptReason: text !== null && text === latestRun?.verification_reason,
  };
}

function newestFirstPlans(plans: FixPlan[] | undefined): FixPlan[] {
  return [...(plans ?? [])].sort((a, b) => b.created_at.localeCompare(a.created_at) || b.id - a.id);
}
// newestFirst (runs) is re-exported for the page's run list
export { newestFirst };
