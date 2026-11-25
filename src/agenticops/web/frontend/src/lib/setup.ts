/**
 * The setup overview and the sign-in page's errors (MVP-2.9.0 N23 — the 2.8.0 spec's S6). Pure, so node can test it.
 */
import { ApiError } from "@/api/client";
import type { Readiness } from "@/api/types";
import type { Draft } from "@/lib/chatDrafts";
import type { StatusTone } from "@/components/ui/StatusText";

// ── signing in ────────────────────────────────────────────────────────────────────────────────────────────────

/** What to say when signing in failed: a wrong name / password as that (401); a server that is down or cannot be
 *  reached as «unavailable» — never as a wrong password; anything else as the server said it, or a plain «failed». */
export function loginError(err: unknown): { key: string | null; message: string | null } {
  if (err instanceof ApiError) {
    if (err.status === 401) return { key: "login.invalid", message: null };
    if (err.status >= 500) return { key: "login.unavailable", message: null };
    return err.message ? { key: null, message: err.message } : { key: "login.failed", message: null };
  }
  if (err instanceof TypeError) return { key: "login.unavailable", message: null };    // fetch: the network, or no server
  return { key: "login.failed", message: null };
}

// ── the overview ──────────────────────────────────────────────────────────────────────────────────────────────

export type SetupItemId = "accounts" | "model" | "execution" | "notifications";
export const SETUP_ITEMS: readonly SetupItemId[] = ["accounts", "model", "execution", "notifications"];

export interface SetupItemView {
  id: SetupItemId;
  /** the state in words: «configured» and «verified» are different words */
  stateKey: string;
  tone: StatusTone;
  /** where the next step is — null for someone who may not open Settings (they are told to ask an administrator) */
  next: { to: string } | null;
  /** the model item, for an administrator: the verification can be run from here */
  canVerify: boolean;
  /** something is still to do here before a first task: an account or the model that is missing, failed or was
   *  never checked. How approvals work and whether messages go out are choices — never owed. */
  owed: boolean;
}

const STATE: Record<SetupItemId, Record<string, [string, StatusTone]>> = {
  accounts: { connected: ["connected", "ok"], configured: ["pending", "warn"], failed: ["failed", "danger"], missing: ["missing", "danger"] },
  model: { verified: ["verified", "ok"], configured: ["pending", "warn"], failed: ["failed", "danger"] },
  execution: { manual: ["manual", "info"], partly_automatic: ["partly_automatic", "warn"], read_only: ["read_only", "neutral"] },
  notifications: { optional: ["optional", "neutral"] },
};
const DONE: Partial<Record<SetupItemId, string>> = { accounts: "connected", model: "verified" };
const NEXT: Record<SetupItemId, string> = {
  accounts: "/app/settings?tab=accounts", model: "/app/settings#settings-models",
  execution: "/app/settings#settings-automation", notifications: "/app/settings?tab=messaging",
};

/** The four items, in order. `can.settings` = this person may open Settings (default: yes). */
export function itemViews(r: Readiness, can: { settings: boolean } = { settings: true }): SetupItemView[] {
  return SETUP_ITEMS.map((id) => {
    const [word, tone] = STATE[id][r[id].state] ?? ["pending", "warn"];
    return { id, stateKey: `setup.state.${word}`, tone, next: can.settings ? { to: NEXT[id] } : null,
             canVerify: id === "model" && r.can_verify, owed: id in DONE && r[id].state !== DONE[id] };
  });
}

/** From the bare /app: an administrator of an installation with no enabled account is shown the overview first.
 *  Nobody else is, and nobody when the answer is not known. */
export function needsSetup(isAdmin: boolean, r: Readiness | undefined): boolean {
  return isAdmin && r !== undefined && r.accounts.enabled === 0;
}

/** «Try a read-only patrol»: the request, put into the NEW conversation's draft — never sent from here. What was
 *  already written there stays, the request after it; a draft that already holds the request is left as it is. */
export function patrolDraft(draft: Draft, request: string): Draft {
  if (draft.text.includes(request)) return draft;
  const before = draft.text.trim() ? `${draft.text.trimEnd()}\n\n` : "";
  return { text: before + request, attachmentIds: draft.attachmentIds };
}

// ── Settings ──────────────────────────────────────────────────────────────────────────────────────────────────

export const SETTINGS_TABS = ["general", "accounts", "providers", "messaging", "audit", "kb", "skills", "mcp", "memory"] as const;
export type SettingsTab = (typeof SETTINGS_TABS)[number];

/** The Settings tab an address names (`?tab=`), else the first. */
export function settingsTab(value: string | null): SettingsTab {
  return SETTINGS_TABS.find((tab) => tab === value) ?? "general";
}
