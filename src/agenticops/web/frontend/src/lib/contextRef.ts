/**
 * What the Chat context panel shows (MVP-2.6.1 spec §3.E.5): an issue or a change request, picked by the
 * clicked ref's route. Pure, so node can test it.
 */
export type ContextRef = { kind: "issue"; id: number } | { kind: "change"; id: number };

/** `/app/issues/N` → the issue, `/app/changes/N` → the change; any other route navigates instead. */
export function contextRefFromPath(pathname: string): ContextRef | null {
  const m = pathname.match(/^\/app\/(issues|changes)\/(\d+)$/);
  if (!m) return null;
  return { kind: m[1] === "issues" ? "issue" : "change", id: Number(m[2]) };
}

/** `I#12` / `C#3`. */
export const refLabel = (ref: ContextRef) => `${ref.kind === "issue" ? "I" : "C"}#${ref.id}`;
