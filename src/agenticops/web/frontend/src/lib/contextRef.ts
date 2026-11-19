/**
 * What the Chat context panel shows (MVP-2.6.1 spec §3.E.5): an issue or a change request, picked by the
 * clicked ref's route. Pure, so node can test it.
 */
export type ContextRef = { kind: "issue"; id: number } | { kind: "change"; id: number };

/** `/app/issues/N` → the issue, `/app/changes/N` → the change (N a positive integer); any other route navigates instead. */
export function contextRefFromPath(pathname: string): ContextRef | null {
  const m = pathname.match(/^\/app\/(issues|changes)\/([1-9]\d*)$/);
  if (!m) return null;
  return { kind: m[1] === "issues" ? "issue" : "change", id: Number(m[2]) };
}

/** `I#12` / `C#3`. */
export const refLabel = (ref: ContextRef) => `${ref.kind === "issue" ? "I" : "C"}#${ref.id}`;

/** `?ref=I12` / `?ref=C3` (or `I#12`) → the record «Ask Agent» opened Chat with (MVP-2.7.0 S4); anything else → null. */
export function contextRefFromQuery(search: string): ContextRef | null {
  const m = (new URLSearchParams(search).get("ref") ?? "").match(/^([IC])#?([1-9]\d*)$/);
  if (!m) return null;
  return { kind: m[1] === "I" ? "issue" : "change", id: Number(m[2]) };
}

export const contextRefQuery = (ref: ContextRef) => `?ref=${ref.kind === "issue" ? "I" : "C"}${ref.id}`;

/** The router state of a link that means «a new conversation» (`navigate("/app/chat", { state: FRESH_CHAT })`). */
export const FRESH_CHAT = { fresh: true } as const;

/** Whether /app/chat opens a NEW conversation instead of resuming the last one: it was opened about a record
 *  (`?ref=`), or the link says so (MVP-2.9.0 N19 — NewUI's command bar brings a sentence into the new conversation's
 *  draft; resuming the last conversation would leave that draft where nobody sees it). */
export function startsFresh(search: string, state: unknown): boolean {
  if (contextRefFromQuery(search)) return true;
  return !!state && typeof state === "object" && (state as { fresh?: unknown }).fresh === true;
}

/** What /app/chat does when no conversation is in its address: `resume` the last one, show the `welcome` page of a
 *  new one, or `stay` as it is (a conversation is in the address, or the page has looked already). Whether a new
 *  conversation is asked for is read from the link that led HERE, NOW — the page keeps its instance between
 *  /app/chat/<id> and /app/chat, so a value taken when it first opened was of another address: opened on a
 *  conversation (a reload, Back), «ask an agent» from the command bar sent the person back into that conversation
 *  and the sentence sat in a draft nobody saw (MVP-2.9.0 N27, review). */
export function chatLanding(at: { sessionInAddress: boolean; attempted: boolean; freshAtMount: boolean; search: string; state: unknown }):
  "stay" | "welcome" | "resume" {
  if (at.sessionInAddress || at.attempted) return "stay";
  return at.freshAtMount || startsFresh(at.search, at.state) ? "welcome" : "resume";
}
