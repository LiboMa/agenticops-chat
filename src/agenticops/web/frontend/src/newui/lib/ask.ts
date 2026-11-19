import type { Draft } from "@/lib/chatDrafts";

/** «问它» (round 3, N19): from an item to a conversation with the agent about it. The chat page already ties a new
 *  conversation to an issue or a change through `?ref=I12` / `?ref=C3` (lib/contextRef) — this is that address. */
export function askPath(item: string): string | null {
  return /^[IC][1-9]\d{0,8}$/.test(item) ? `/app/chat?ref=${item}` : null;
}

/** One chat message may hold this many characters (the server's limit on a message's content). */
export const MESSAGE_MAX = 10_000;

/** A sentence typed into the command bar, put into the NEW conversation's draft — not sent: one Enter in the command
 *  bar must not start an agent run. What the person had already written in that draft stays, the sentence after it. */
export function withAsk(draft: Draft, sentence: string): Draft {
  const text = sentence.trim();
  if (!text) return draft;
  const before = draft.text.trim() ? `${draft.text.trimEnd()}\n\n` : "";
  return { text: (before + text).slice(0, MESSAGE_MAX), attachmentIds: draft.attachmentIds };
}
