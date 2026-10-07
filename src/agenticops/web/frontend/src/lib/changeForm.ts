/**
 * NewChangeDialog's optional fields (MVP-2.6.1 spec §3.E.4): the requester's own steps and the external ticket,
 * cleaned the way the API validates them (web/schemas.ChangeProposedStep / ChangeExternalRef) so a bad row is
 * named in the form instead of coming back as a 422.
 */
import type { ChangeExternalRef, ChangeProposedStep } from "@/api/types";

export const MAX_PROPOSED_STEPS = 50; // services/change_steps.MAX_STEPS

export type Cleaned<T, E> = { ok: true; value: T | undefined } | ({ ok: false } & E);

/** Trimmed steps without the blank rows; undefined when none are left. A row with only a description is refused. */
export function cleanProposedSteps(
  rows: ChangeProposedStep[],
): Cleaned<ChangeProposedStep[], { error: "noCommand"; row: number }> {
  const steps: ChangeProposedStep[] = [];
  for (const [i, r] of rows.entries()) {
    const [action, command] = [r.action.trim(), r.command.trim()];
    if (!action && !command) continue;
    if (!command) return { ok: false, error: "noCommand", row: i + 1 };
    steps.push({ action, command });
  }
  return { ok: true, value: steps.length ? steps : undefined };
}

/** The external ticket, or undefined when every field is blank. */
export function cleanExternalRef(
  f: { system: string; ticket_id: string; url: string },
): Cleaned<ChangeExternalRef, { error: "badSystem" | "noTicket" | "badUrl" }> {
  const [system, ticket_id, url] = [f.system.trim(), f.ticket_id.trim(), f.url.trim()];
  if (!system && !ticket_id && !url) return { ok: true, value: undefined };
  if (!/^[a-z0-9_-]{1,50}$/.test(system)) return { ok: false, error: "badSystem" };
  if (!ticket_id) return { ok: false, error: "noTicket" };
  if (url && !/^https?:\/\//i.test(url)) return { ok: false, error: "badUrl" };
  return { ok: true, value: url ? { system, ticket_id, url } : { system, ticket_id } };
}
