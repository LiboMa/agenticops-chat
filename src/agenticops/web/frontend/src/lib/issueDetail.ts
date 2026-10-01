/**
 * IssueDetail view logic (MVP-2.6.1 spec §3.E.2): the tab in the URL, the three status labels, the anchor badge,
 * the execution evidence rows, when to poll and when a plan can be approved. Pure, so node can test it.
 */
import type { FixExecution, FixPlan, FixPlanStatus, HealthIssue, IssueStatus, VerificationStatus } from "@/api/types";

export const ISSUE_TABS = ["investigate", "fixPlan", "execution", "verification", "timeline"] as const;
export type IssueTab = (typeof ISSUE_TABS)[number];

/** `?tab=` → a tab; the pre-2.6.1 `issue` tab and anything unknown open Investigate. */
export function parseIssueTab(v: string | null): IssueTab {
  return (ISSUE_TABS as readonly string[]).includes(v ?? "") ? (v as IssueTab) : "investigate";
}

export interface IssueFacts {
  resourceType: string | null;
  region: string | null;
  metricName: string | null;
  expected: unknown;
  actual: unknown;
}

/** The facts the legacy /issues shape lifted out of metric_data, null where the issue carries none. */
export function issueFacts(issue: Pick<HealthIssue, "metric_data">): IssueFacts {
  const md = issue.metric_data ?? {};
  const str = (k: string) => (typeof md[k] === "string" && md[k] ? (md[k] as string) : null);
  return { resourceType: str("resource_type"), region: str("region"), metricName: str("metric_name"),
           expected: md.expected_value ?? null, actual: md.actual_value ?? null };
}

export interface IssueStatuses {
  business: IssueStatus;
  execution: string | null;
  verification: VerificationStatus | null;
  latest: FixExecution | null;
  pending: FixExecution | null; // the newest run, while it waits for a human to accept or reject it
}

/** Runs newest first, by created_at then id (the API already sends them so; this does not rely on it). */
export function newestFirst(executions: FixExecution[] | undefined): FixExecution[] {
  return [...(executions ?? [])].sort((a, b) => b.created_at.localeCompare(a.created_at) || b.id - a.id);
}

/** The newest run. */
export function latestExecution(executions: FixExecution[] | undefined): FixExecution | null {
  return newestFirst(executions)[0] ?? null;
}

/** Business status from the issue; execution and verification from its newest run. Acceptance is offered only
 *  while the issue still sits at fix_executed — the accept endpoint refuses (409) once it has moved on. */
export function issueStatuses(issue: Pick<HealthIssue, "status">, executions: FixExecution[] | undefined): IssueStatuses {
  const latest = latestExecution(executions);
  const pending = latest?.verification_status === "pending_acceptance" && issue.status === "fix_executed";
  return {
    business: issue.status,
    execution: latest?.status ?? null,
    verification: latest?.verification_status ?? null,
    latest,
    pending: pending ? latest : null,
  };
}

/** The issue statuses a fix is in motion in: the page polls the issue until the run lands its verdict. */
export const ISSUE_IN_FLIGHT: ReadonlySet<IssueStatus> = new Set<IssueStatus>(["fix_approved", "fix_executing"]);

/** A run still queued (pending) or claimed (running); every other status is finished. */
export function hasRunInFlight(executions: Pick<FixExecution, "status">[] | undefined): boolean {
  return !!executions?.some((e) => e.status === "pending" || e.status === "running");
}

const APPROVABLE_PLAN: ReadonlySet<FixPlanStatus> = new Set<FixPlanStatus>(["draft", "pending_approval"]);

/** Why an approvable plan cannot be approved: its issue is closed (the approve endpoint refuses it with 409,
 *  issue_state.closed_issue_refusal). null when the plan is not approvable anyway or its issue is open. */
export function approvalBlockedReason(
  fp: Pick<FixPlan, "status">, issueStatus: string | undefined,
): "resolved" | "dismissed" | null {
  if (!APPROVABLE_PLAN.has(fp.status)) return null;
  return issueStatus === "resolved" || issueStatus === "dismissed" ? issueStatus : null;
}

/** The backend approves a draft or pending plan, and not one whose issue is resolved or dismissed. */
export function canApprovePlan(fp: Pick<FixPlan, "status">, issueStatus: string | undefined): boolean {
  return APPROVABLE_PLAN.has(fp.status) && approvalBlockedReason(fp, issueStatus) === null;
}

export type AnchorBadge =
  | { kind: "resource"; ref: number; label: string }
  | { kind: "ambiguous" | "account_level" | "unanchored"; candidates: number };

/** A link to the anchored resource, or why there is none; null before the resolver has reached the issue. */
export function anchorBadge(
  issue: Pick<HealthIssue, "resource_id" | "resource_ref" | "anchor_status" | "anchor_candidates">,
): AnchorBadge | null {
  if (issue.anchor_status == null) return null;
  if (issue.anchor_status === "anchored" && issue.resource_ref != null) {
    return { kind: "resource", ref: issue.resource_ref, label: issue.resource_id };
  }
  const kind = issue.anchor_status === "anchored" ? "unanchored" : issue.anchor_status;
  return { kind, candidates: kind === "ambiguous" ? issue.anchor_candidates?.candidates?.length ?? 0 : 0 };
}

export type ResultOutcome = "pass" | "warning" | "fail" | "missing";
export interface ResultRow {
  outcome: ResultOutcome;
  title: string;
  output: string;
}

// Mirrors services/verification._PASS / _WARN
const PASS = new Set(["pass", "passed", "ok", "succeeded", "success", "true"]);
const WARN = new Set(["warn", "warning"]);

function text(v: unknown): string {
  if (v == null) return "";
  return typeof v === "string" ? v : JSON.stringify(v);
}

/** One pre-check / step / post-check / rollback result, its outcome read the way verification._outcome reads it. */
export function resultRow(item: unknown): ResultRow {
  const obj = item !== null && typeof item === "object" && !Array.isArray(item) ? (item as Record<string, unknown>) : null;
  const status = obj ? ("status" in obj ? obj.status : "result" in obj ? obj.result : obj.passed) : item;
  const value = status == null ? null : String(status).trim().toLowerCase();
  const outcome: ResultOutcome = value == null ? "missing" : PASS.has(value) ? "pass" : WARN.has(value) ? "warning" : "fail";
  if (!obj) return { outcome, title: text(item), output: "" };
  const pick = (keys: string[]) => text(keys.map((k) => obj[k]).find((v) => v != null && v !== ""));
  return { outcome, title: pick(["check", "name", "description", "command", "step"]),
           output: pick(["output", "detail", "details", "message", "error"]) };
}

export function resultSummary(items: unknown[]): Record<ResultOutcome, number> {
  const counts: Record<ResultOutcome, number> = { pass: 0, warning: 0, fail: 0, missing: 0 };
  for (const item of items) counts[resultRow(item).outcome]++;
  return counts;
}
