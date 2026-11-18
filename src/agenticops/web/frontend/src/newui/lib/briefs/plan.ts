import type { FixPlan } from "@/api/types";
import { findAction } from "@/lib/approval";
import { shortHash } from "@/lib/plans";

/** A plan as a brief shows it. The columns are free-form JSON written by an agent; every reader here takes each
 *  shape the classic plan view takes (components/plans/RunbookStep, CheckItem, RollbackPlan). */

export type Tier = "write" | "readonly" | "blocked" | "unknown";
const TIERS: readonly string[] = ["write", "readonly", "blocked", "unknown"];

export interface StepVm {
  /** what the step says it does; empty when it is a bare command */
  say: string;
  cmd: string | null;
  /** how the CODE classifies the command (the server's step_tiers); null = the server did not say — claim nothing */
  tier: Tier | null;
  /** a step written with keys this reader does not know: the step as it is. The approval's hash covers it, so it is
   *  shown, never «—» */
  raw?: string;
}

const obj = (v: unknown): Record<string, unknown> | null =>
  (typeof v === "object" && v !== null && !Array.isArray(v) ? (v as Record<string, unknown>) : null);
const str = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v.trim() : null);

function step(raw: unknown, tier: Tier | null): StepVm {
  const o = obj(raw);
  if (!o) return { say: typeof raw === "string" ? raw.trim() : raw == null ? "" : String(raw), cmd: null, tier };
  const say = str(o.action) ?? str(o.description) ?? str(o.step) ?? "", cmd = str(o.command);
  return say || cmd ? { say, cmd, tier } : { say, cmd, tier, raw: JSON.stringify(raw) };
}

export function stepsVm(plan: Pick<FixPlan, "steps" | "step_tiers">): StepVm[] {
  const steps = Array.isArray(plan.steps) ? plan.steps : [];
  const tiers = Array.isArray(plan.step_tiers) && plan.step_tiers.length === steps.length ? plan.step_tiers : null;
  return steps.map((s, i) => step(s, tiers && TIERS.includes(tiers[i]) ? (tiers[i] as Tier) : null));
}

/** What the database's secret scrub leaves in place of a value (security/redaction.PLACEHOLDER). */
export const SCRUBBED = "[REDACTED-SECRET]";

/** How many places of a plan — a step, a rollback line, a check — lost a value when the plan was stored. The stored
 *  text is what the approver is shown, what the approval's hash covers and what the executor is handed; it does not
 *  say which value. The server marks such a command «unknown» (so it is never approved without a person); the brief
 *  says why. */
export function scrubbedCount(plan: { steps?: unknown; rollback_plan?: unknown; pre_checks?: unknown; post_checks?: unknown }): number {
  const held = (v: unknown): boolean => (v == null ? false : (typeof v === "string" ? v : JSON.stringify(v)).includes(SCRUBBED));
  const list = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
  const r = obj(plan.rollback_plan);
  const rollback = r ? [...list(r.steps), ...list(r.commands), ...Object.entries(r).filter(([k]) => k !== "steps" && k !== "commands").map(([, v]) => v)]
    : list(plan.rollback_plan).length ? list(plan.rollback_plan) : [plan.rollback_plan];
  return [...list(plan.steps), ...rollback, ...list(plan.pre_checks), ...list(plan.post_checks)].filter(held).length;
}

export interface CheckVm { id: string; text: string; cmd: string | null }

/** The declared checks of one list, each with its command. A post-check's id is its position (pc-1 … pc-n): the id
 *  the executor reports against; a pre-check is numbered the same way (pre-1 …). Both lists are part of what an
 *  approval's hash covers, so both are shown whole. */
export function checksVm(plan: Pick<FixPlan, "pre_checks" | "post_checks">, which: "pre" | "post"): CheckVm[] {
  const list = which === "pre" ? plan.pre_checks : plan.post_checks;
  return (Array.isArray(list) ? list : []).map((c, i) => {
    const o = obj(c);
    const text = o ? str(o.check) ?? str(o.description) ?? str(o.action) ?? JSON.stringify(c) : typeof c === "string" ? c.trim() : JSON.stringify(c);
    return { id: `${which === "pre" ? "pre" : "pc"}-${i + 1}`, text, cmd: o ? str(o.command) : null };
  });
}

/** The declared post-checks, as the acceptance reads them. */
export function postChecksVm(plan: Pick<FixPlan, "post_checks">): { id: string; text: string }[] {
  return checksVm({ pre_checks: [], post_checks: plan.post_checks }, "post").map(({ id, text }) => ({ id, text }));
}

export interface RollbackVm {
  trigger: string | null;
  steps: StepVm[];
  /** everything else the rollback says. Its shape is free-form (an agent wrote it): each further key with its text,
   *  the key's underscores as spaces — never dropped, or a plan that does describe its rollback would read as none */
  notes: { label: string; text: string }[];
}

export function rollbackVm(plan: Pick<FixPlan, "rollback_plan">): RollbackVm {
  const r = obj(plan.rollback_plan) ?? {};
  const list = Array.isArray(r.steps) ? r.steps : Array.isArray(r.commands) ? r.commands : [];
  const notes = Object.entries(r)
    .filter(([k, v]) => !["trigger", "steps", "commands"].includes(k) && v != null && v !== "")
    .map(([k, v]) => ({ label: k.replace(/_/g, " "), text: typeof v === "string" ? v.trim() : JSON.stringify(v) }))
    .filter((n) => n.text);
  return { trigger: str(r.trigger), steps: list.map((s) => step(s, null)), notes };
}

export function planHead(plan: Pick<FixPlan, "plan_version" | "content_hash" | "risk_level">): { version: number; hash8: string | null; risk: string } {
  return { version: plan.plan_version || 1, hash8: plan.content_hash ? shortHash(plan.content_hash) : null, risk: plan.risk_level };
}

export interface ApproveState {
  /** the button works: the server allows it and there is a content hash to bind the approval to */
  can: boolean;
  /** approving queues the run (auto-fix and the executor are on); false = it only approves */
  runs: boolean;
  /** the same, as the page may word it: "unknown" when the server's effect is one this client does not know (or
   *  there is none) — then the page says the server's settings decide, never «does not run» */
  effect: "run" | "only" | "unknown";
  /** why it cannot: the server's reason code, "no_hash", or "state" when the plan offers no approval */
  why: string | null;
  /** allowed only because the access policy is in shadow mode */
  shadow: boolean;
}

/** What «approve» does for this plan, from the server's own available_actions — never guessed from the status. */
export function approveState(plan: Pick<FixPlan, "available_actions" | "content_hash">): ApproveState {
  const a = findAction(plan.available_actions, "approve");
  if (!a) return { can: false, runs: false, effect: "unknown", why: "state", shadow: false };
  const runs = a.effect === "approve_and_queue_execution";
  const effect = runs ? "run" : a.effect === "approve_only" ? "only" : "unknown";
  if (!a.allowed) return { can: false, runs, effect, why: a.reason_code ?? "forbidden", shadow: false };
  if (!plan.content_hash) return { can: false, runs, effect, why: "no_hash", shadow: false };
  return { can: true, runs, effect, why: null, shadow: a.reason_code === "policy_shadow" };
}

/** The toast after an approval: what the server's answer says happened (`queued`), and the page's belief only when
 *  the answer does not say — the executor may have been switched on or off while the person was reading. */
export function approvedToastKey(queued: boolean | undefined, effect: ApproveState["effect"]): string {
  const what = queued === undefined ? effect : queued ? "run" : "only";
  return `toast.approved.${what}`;
}
