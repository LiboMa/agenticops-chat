/**
 * The phase cards of the two work-item pages (IssueDetail, ChangeDetail): which open on arrival, which can be
 * opened, and the hash a card header writes. Pure; hooks/usePhaseCards holds the state.
 */
import type { PhaseView } from "@/lib/issuePhases";

/** The cards open on arrival: the current phase, any failed one, and the one a link's hash names. */
export function seedOpenCards<Id extends string>(
  phases: readonly PhaseView<Id>[], ids: readonly Id[], target: string | null,
): Set<Id> {
  const open = phases.filter((p) => p.state === "current" || p.state === "failed").map((p) => p.id);
  if (target && (ids as readonly string[]).includes(target)) open.push(target as Id);
  return new Set(open);
}

/** The cards a reader can open: every phase reached, not a future one. */
export function openableCards<Id extends string>(phases: readonly PhaseView<Id>[]): Id[] {
  return phases.filter((p) => p.state !== "future").map((p) => p.id);
}

/** The hash after a card header is toggled: opening names the card; closing clears the hash only if it named it. */
export function toggledCardHash(hash: string, id: string, open: boolean): string {
  return open ? `#${id}` : hash === `#${id}` ? "" : hash;
}
