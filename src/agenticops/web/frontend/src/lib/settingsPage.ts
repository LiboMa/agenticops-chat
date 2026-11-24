/**
 * The Settings page's General tab (MVP-2.9.0 N25 — the 2.8.0 spec's S8): three sections with anchors, and the
 * high-impact switches — which are staged and saved only after a preview, never by one click. Pure.
 */

// ── the three sections ────────────────────────────────────────────────────────────────────────────────────────

export const SECTIONS = ["basics", "automation", "models"] as const;
export type SectionId = (typeof SECTIONS)[number];

export const sectionAnchor = (id: SectionId): string => "settings-" + id;

/** The section an address's hash names (`#settings-models`), else null. */
export function sectionOfHash(hash: string): SectionId | null {
  return SECTIONS.find((id) => hash === "#" + sectionAnchor(id)) ?? null;
}

// ── the high-impact switches ──────────────────────────────────────────────────────────────────────────────────

/** In the order the page shows them. The first four are stored in the database (`services/exec_switches`: they
 *  survive a restart); the last two are saved in the settings file. All six need an administrator and are audited. */
export const HIGH_IMPACT = [
  "auto_fix_enabled", "executor_enabled", "executor_auto_approve_l0_l1", "executor_hitl_enabled",
  "change_auto_approve_standard", "rbac_enforce",
] as const;
export type HighKey = (typeof HIGH_IMPACT)[number];
const STORED: ReadonlySet<string> = new Set(["auto_fix_enabled", "executor_enabled", "executor_auto_approve_l0_l1", "executor_hitl_enabled"]);

/** The switches on the page: standard-change auto-approval only while change management is on. */
export function highKeys(s: { change_management_enabled?: boolean }): HighKey[] {
  return HIGH_IMPACT.filter((key) => key !== "change_auto_approve_standard" || s.change_management_enabled === true);
}

export type Staged = Partial<Record<HighKey, boolean>>;

/** What the server says about the stored switches (`GET /api/settings` → `execution_switches`). `locked` = the
 *  switches this process's ENVIRONMENT holds at their strict value (MVP-2.9.0 N27): in force whatever is stored. */
export interface SwitchInfo { overridden: string[]; locked?: Record<string, boolean> }

/** The variable that holds a switch, as it is written (`AIOPS_EXECUTOR_ENABLED=false`) — null when nothing does. */
export function heldVar(key: HighKey, info: SwitchInfo | undefined): string | null {
  const value = info?.locked?.[key];
  return typeof value === "boolean" ? `AIOPS_${key.toUpperCase()}=${value}` : null;
}

/** A click on a switch: the value is staged — or un-staged when it is what is saved already. A switch the
 *  environment holds cannot be staged: the server would refuse it. */
export function stage(saved: Record<HighKey, boolean>, staged: Staged, key: HighKey, value: boolean, info?: SwitchInfo): Staged {
  if (heldVar(key, info) !== null) return staged;
  const next = { ...staged };
  if (saved[key] === value) delete next[key]; else next[key] = value;
  return next;
}

/** What a switch shows: the staged value, else the saved one. */
export function shown(saved: Record<HighKey, boolean>, staged: Staged, key: HighKey): boolean {
  return staged[key] ?? saved[key];
}

export interface PendingChange { key: HighKey; from: boolean; to: boolean }

/** What «preview and save» lists: the staged values that differ from the saved ones, of the switches on the page. */
export function pending(saved: Record<HighKey, boolean>, staged: Staged, keys: HighKey[]): PendingChange[] {
  return keys.filter((key) => staged[key] !== undefined && staged[key] !== saved[key])
    .map((key) => ({ key, from: saved[key], to: staged[key] as boolean }));
}

/** Where the value in force comes from: `environment` = this process's environment holds it (whatever is stored);
 *  `stored` = an administrator's value in the database; `default` = the settings file's (or the environment's)
 *  value, nothing stored; `file` = the two toggles saved in the settings file. */
export function sourceOf(key: HighKey, info: SwitchInfo | undefined): "environment" | "stored" | "default" | "file" {
  if (!STORED.has(key)) return "file";
  if (heldVar(key, info) !== null) return "environment";
  return info?.overridden.includes(key) ? "stored" : "default";
}

/** Who may change them: with sign-in on, an administrator; with it off, anyone (the server's own rule). Nobody
 *  until that is known. */
export function canEditHigh(boot: { auth_enabled?: boolean; user?: { is_admin?: boolean } | null } | undefined): boolean {
  if (!boot) return false;
  return boot.auth_enabled === false || !!boot.user?.is_admin;
}

// ── models ────────────────────────────────────────────────────────────────────────────────────────────────────

/** Whether a model id is in the list of available models — read from the list, no model is called. `unknown`
 *  while there is no list (or no id). */
export function modelAvailability(modelId: string, presets: { value: string }[] | undefined): "listed" | "unlisted" | "unknown" {
  if (!modelId || !presets || presets.length === 0) return "unknown";
  return presets.some((p) => p.value === modelId) ? "listed" : "unlisted";
}

/** The tab Settings shows (MVP-2.9.0 N27). The audit log is read by an administrator when sign-in is on
 *  (`lib/plans.auditTabVisible`, the hub's own rule): anyone else who follows a link to it gets the first tab —
 *  never a tab whose every request is refused. */
export function shownTab<T extends string>(requested: T, auditOn: boolean): T | "general" {
  return requested === "audit" && !auditOn ? "general" : requested;
}
