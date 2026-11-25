/**
 * What the Chat page says about a message's dispatch (MVP-2.7.0 S5): an interrupted reply is labelled as such, a
 * failed one by its kind of failure — never the raw exception text. Pure, so node can test it.
 */
import type { ChatMessage, ChatSession } from "@/api/types";

const ERROR_CODES = new Set(["throttled", "model_unavailable", "context_too_long", "timeout", "max_tokens",
  "request_rejected", "internal"]);

export function messageStatusKey(m: Pick<ChatMessage, "role" | "dispatch_state" | "token_usage">): string | null {
  if (m.role !== "assistant") return null;
  if (m.dispatch_state === "interrupted") return "chat.status.interrupted";
  const code = m.token_usage?.error_code;
  if (m.dispatch_state === "failed" || code || m.token_usage?.error) {
    return `chat.error.${code && ERROR_CODES.has(code) ? code : "internal"}`;
  }
  return null;
}

/** The model's own reason for a rejected request (2026-11-08), or which model could not be used and why (MVP-2.9.0
 *  N35) — the server's `error_detail`, shown under the failure label; every other failure shows no detail (never the
 *  raw exception). */
const DETAILED = new Set(["request_rejected", "model_unavailable"]);

export function messageErrorDetail(m: Pick<ChatMessage, "role" | "token_usage">): string | null {
  if (m.role !== "assistant" || !DETAILED.has(m.token_usage?.error_code ?? "")) return null;
  const detail = m.token_usage?.error_detail;
  return typeof detail === "string" && detail ? detail : null;
}

/** The empty state's starter prompts: chat.starter.<id>.label / .prompt — they fill the composer, never send. */
export const STARTERS = ["investigate", "change", "report"] as const;

/** A session row's second line: the linked object's ref, or "independent request". */
export function sessionRowLabel(s: Pick<ChatSession, "context">): { key: string | null; text: string | null } {
  const ref = s.context?.primary?.ref;
  return ref ? { key: null, text: ref } : { key: "chat.independent", text: null };
}
