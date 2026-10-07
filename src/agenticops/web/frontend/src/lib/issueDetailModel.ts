import type { FixExecution, FixPlan, HealthIssue, IssueStatus, PipelineEvent, RCAResult } from "@/api/types";
import { inFlightAutoRun, issueStatuses, latestExecution, newestFirst, notQueuedFrom } from "@/lib/issueDetail";
import { currentFixPlan, issuePhases, type IssuePhaseResult } from "@/lib/issuePhases";
import { confidenceBreakdown } from "@/lib/rcaQuality";

export interface ReasonRef { key: string; params?: Record<string, string> }
export type Reason = ReasonRef | { text: string };
export type IssueMenuItem = "runRca" | "skipReviewGeneratePlan" | "markResolved" | "dismiss" | "reopen" | "cancelRun"
  | "retryExecution" | "askAgent";

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
  autoRun: { startedAt: string } | null; // the approval's auto-run under way (no run row until it ends)
  recheckAt: number | null;              // checking whether the run started: the moment (epoch ms) the grace ends
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
  plansFailed?: boolean;                  // with plans undefined: the fetch failed rather than still loading
  executions: FixExecution[] | undefined; // undefined = not known (still loading, or the fetch failed): never "no runs"
  runsFailed?: boolean;                   // with executions undefined: the fetch failed rather than still loading
  rcaFailed?: boolean;                    // with rca undefined: the fetch failed rather than still loading (I1)
  timeline?: PipelineEvent[];             // the issue's events: an approval's auto-run is seen there; undefined = not known
  timelineFetchedAt?: number;             // when that copy was fetched (epoch ms; default now)
  timelineFailed?: boolean;               // the timeline's last fetch failed: none loaded, or a cached copy that may be old
  executorTimeout?: number | null;        // seconds a started auto-run counts as under way (settings)
  autoFixEnabled?: boolean;               // settings.auto_fix_enabled (who generates a plan for a passing RCA)
  now?: number;
}): IssueDetailModel {
  const { issue, rca, threshold } = input;
  const plan = currentFixPlan(input.plans);
  const latestRun = latestExecution(input.executions);
  const autoRun = plan?.status === "approved"
    ? inFlightAutoRun(input.timeline, plan.id, { timeoutSeconds: input.executorTimeout, now: input.now })
    : null;
  // undefined (still loading) keeps list mode — never a flash of "rerun RCA"; null means there is no RCA
  // likewise runs not known yet are undefined, loaded-and-none is null
  const known = issuePhases({ status: issue.status, rca, threshold, plan, autoRunInFlight: !!autoRun, autoFixEnabled: input.autoFixEnabled,
                              latestRun: input.executions === undefined ? undefined : latestRun });
  const unknown = (failed: boolean | undefined): IssuePhaseResult =>
    ({ ...known, sub: failed ? "runsUnavailable" : "loadingRuns", waitingFor: null, primary: null });
  // No run row: whether the approval's auto-run is under way is on the timeline (matched to the plan). "Not queued"
  // needs both loaded and a timeline fetched from notQueuedFrom on — the plan's approval + the grace, unless a run of
  // it already showed (C1(c)); until then the run state is unknown, and recheckAt is when to look again.
  const notQueuedAt = input.timeline === undefined || input.plans === undefined ? null
    : plan?.status === "approved" ? notQueuedFrom(input.timeline, plan) : 0;
  const timelineReady = notQueuedAt !== null && (input.timelineFetchedAt ?? input.now ?? Date.now()) >= notQueuedAt;
  const runStateFailed = (input.plans === undefined && input.plansFailed) || (!timelineReady && input.timelineFailed);
  const phase: IssuePhaseResult = input.executions === undefined && RUN_DEPENDENT.has(issue.status) ? unknown(input.runsFailed)
    : known.sub === "notQueued" && (input.plans === undefined || !timelineReady)
      ? { ...known, sub: runStateFailed ? "runStateUnavailable" : "checkingRun", waitingFor: null, primary: null }
    // the RCA decides root_cause_identified: one that failed to load is not "none"
    : known.sub === "reviewOrPlan" && rca === undefined && input.rcaFailed
      ? { ...known, sub: "rcaUnavailable", waitingFor: null, primary: null }
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
    case "planRejected": reason = plan?.rejection_reason ? { text: plan.rejection_reason } : { key: "workitem.reason.planRejected" }; break;
    case "notQueued": reason = { key: "workitem.reason.notQueued" }; break;
    case "awaitingAcceptance": { const t = runText(latestRun); reason = t ? { text: t } : null; break; }
    default: reason = null;
  }

  const terminal = issue.status === "resolved" || issue.status === "dismissed";
  // «Ask Agent» (MVP-2.7.0 S4): open or closed, a case can always be talked over
  const menu: IssueMenuItem[] = terminal ? ["reopen", "askAgent"] : [
    ...(phase.primary === "rerunRca" ? [] : ["runRca" as const]),
    // the backend generates a plan from an RCA: none (or not loaded yet) → not offered
    ...(issue.status === "root_cause_identified" && rca && phase.primary !== "generatePlan" ? ["skipReviewGeneratePlan" as const] : []),
    ...(phase.sub === "executing" && latestRun && (latestRun.status === "pending" || latestRun.status === "running") ? ["cancelRun" as const] : []),
    // an auto-run has no row to cancel, and one not known to have started may never have: either can be queued
    // again here — never stuck — and the backend refuses (409) while a run is under way
    ...(issue.status === "fix_approved" && plan?.status === "approved"
        && ((phase.sub === "executing" && autoRun) || phase.sub === "checkingRun" || phase.sub === "runStateUnavailable")
      ? ["retryExecution" as const] : []),
    ...(phase.primary === "markResolved" ? [] : ["markResolved" as const]),
    "dismiss",
    "askAgent",
  ];

  const tone = phase.sub === "needsNewPlan" ? "bad"
    : ["needsReview", "rcaRejected", "planRejected", "notQueued", "awaitingAcceptance", "awaitingApproval", "unverified", "reviewOrPlan",
       "runsUnavailable", "rcaUnavailable", "runStateUnavailable"].includes(phase.sub) ? "warn"
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
    autoRun,
    recheckAt: phase.sub === "checkingRun" && notQueuedAt ? notQueuedAt : null,
    quietRunError: text !== null && text === latestRun?.error_message,
    quietAcceptReason: text !== null && text === latestRun?.verification_reason,
  };
}

function newestFirstPlans(plans: FixPlan[] | undefined): FixPlan[] {
  return [...(plans ?? [])].sort((a, b) => b.created_at.localeCompare(a.created_at) || b.id - a.id);
}
// newestFirst (runs) is re-exported for the page's run list
export { newestFirst };
