import { describe, it, expect } from "vitest";
import { canRegenerate } from "@/lib/messageActions";
import type { ChatMessage } from "@/api/types";

const u = (o: Partial<ChatMessage> = {}) => ({ id: 1, role: "user", content: "q", created_at: "", ...o }) as ChatMessage;
const a = (o: Partial<ChatMessage> = {}) => ({ id: 2, role: "assistant", content: "ans", created_at: "", ...o }) as ChatMessage;

describe("canRegenerate", () => {
  it("only the last answer, with its question's text", () => {
    expect(canRegenerate([u(), a()], 1, false)).toEqual({ ok: true, text: "q" });
    expect(canRegenerate([u(), a(), u({ id: 3 }), a({ id: 4 })], 1, false)).toEqual({ ok: false, reason: "not_last" });
  });
  it("not while streaming, not after a question with attachments, not without a question", () => {
    expect(canRegenerate([u(), a()], 1, true)).toEqual({ ok: false, reason: "streaming" });
    expect(canRegenerate([u({ attachments: [{ id: "x", filename: "f", size: 1, kind: "image" }] as any }), a()], 1, false))
      .toEqual({ ok: false, reason: "attachments" });
    expect(canRegenerate([a()], 0, false)).toEqual({ ok: false, reason: "no_question" });
  });
});
