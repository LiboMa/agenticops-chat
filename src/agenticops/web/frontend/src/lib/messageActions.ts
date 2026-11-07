import type { ChatMessage } from "@/api/types";

export type RegenCheck = { ok: true; text: string }
  | { ok: false; reason: "not_last" | "streaming" | "attachments" | "no_question" };

/** «Regenerate» is offered on the last answer only, by sending its question again (a new answer follows, the
 *  history stays linear). A question that carried attachments cannot be resent: attachments bind to one message. */
export function canRegenerate(messages: ChatMessage[], index: number, streaming: boolean): RegenCheck {
  if (index !== messages.length - 1 || messages[index]?.role !== "assistant") return { ok: false, reason: "not_last" };
  let q = -1;
  for (let i = index - 1; i >= 0; i--) if (messages[i].role === "user") { q = i; break; }
  if (q === -1) return { ok: false, reason: "no_question" };
  if (streaming) return { ok: false, reason: "streaming" };
  if ((messages[q].attachments?.length ?? 0) > 0) return { ok: false, reason: "attachments" };
  return { ok: true, text: messages[q].content };
}
