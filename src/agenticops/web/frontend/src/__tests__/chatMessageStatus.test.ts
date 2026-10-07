import { describe, it, expect } from "vitest";
import { messageStatusKey, STARTERS, sessionRowLabel } from "@/lib/chatMessageStatus";
import type { ChatMessage, ChatSession } from "@/api/types";

const m = (x: Partial<ChatMessage>) => ({ role: "assistant", ...x }) as ChatMessage;

describe("chat message status (MVP-2.7.0 S5)", () => {
  it("an interrupted reply says so", () => {
    expect(messageStatusKey(m({ dispatch_state: "interrupted" }))).toBe("chat.status.interrupted");
  });
  it("a failed reply says what kind of failure, never the raw exception", () => {
    expect(messageStatusKey(m({ dispatch_state: "failed", token_usage: { input: 0, output: 0, error: "boto: x", error_code: "throttled" } }))).toBe("chat.error.throttled");
    expect(messageStatusKey(m({ dispatch_state: "failed", token_usage: { input: 0, output: 0, error_code: "weird" } }))).toBe("chat.error.internal");
    expect(messageStatusKey(m({ dispatch_state: "failed" }))).toBe("chat.error.internal");
  });
  it("an older failed row (error, no code) reads as internal", () => {
    expect(messageStatusKey(m({ token_usage: { input: 0, output: 0, error: "old raw text" } }))).toBe("chat.error.internal");
  });
  it("user messages and completed replies have no label", () => {
    expect(messageStatusKey(m({ role: "user", dispatch_state: "interrupted" }))).toBeNull();
    expect(messageStatusKey(m({ dispatch_state: "completed" }))).toBeNull();
    expect(messageStatusKey(m({}))).toBeNull();
  });
  it("three starters, each with a label and a prompt key", () => {
    expect(STARTERS).toEqual(["investigate", "change", "report"]);
  });
  it("a session row names what it is about, or that it is an independent request", () => {
    const s = (context: ChatSession["context"]) => ({ context }) as ChatSession;
    expect(sessionRowLabel(s({ primary: { entity_type: "health_issue", entity_id: 3, ref: "I#3", title: "x" },
      account_id: 1, account_name: "p", region: null, scope_locked: true }))).toEqual({ key: null, text: "I#3" });
    expect(sessionRowLabel(s(null))).toEqual({ key: "chat.independent", text: null });
    expect(sessionRowLabel(s(undefined))).toEqual({ key: "chat.independent", text: null });
  });
});
