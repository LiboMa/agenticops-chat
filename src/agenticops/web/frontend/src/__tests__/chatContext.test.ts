import { describe, it, expect } from "vitest";
import { contextForNewChat, contextLineKey } from "@/lib/chatContext";
import type { ChatContextView } from "@/api/types";

describe("chat context on the frontend (MVP-2.7.0 S5)", () => {
  it("a chat asked about an issue or change links it; the server takes the object's account", () => {
    expect(contextForNewChat({ kind: "issue", id: 12 }, 3)).toEqual({ primary: { entity_type: "health_issue", entity_id: 12 }, account_id: null });
    expect(contextForNewChat({ kind: "change", id: 4 }, null)).toEqual({ primary: { entity_type: "change_request", entity_id: 4 }, account_id: null });
  });
  it("a free chat takes the top bar's account, or none", () => {
    expect(contextForNewChat(null, 3)).toEqual({ primary: null, account_id: 3 });
    expect(contextForNewChat(null, null)).toEqual({ primary: null, account_id: null });
  });
  const view = (x: Partial<ChatContextView>): ChatContextView =>
    ({ primary: null, account_id: null, account_name: null, region: null, scope_locked: false, ...x });
  it("the context line: linked, bound, or all accounts", () => {
    expect(contextLineKey(view({ primary: { entity_type: "health_issue", entity_id: 12, ref: "I#12", title: "cpu" }, account_name: "lab", account_id: 2 })))
      .toEqual({ key: "chat.context.linked", params: { ref: "I#12", title: "cpu", account: "lab" } });
    expect(contextLineKey(view({ account_id: 2, account_name: "lab" }))).toEqual({ key: "chat.context.bound", params: { account: "lab" } });
    expect(contextLineKey(view({}))).toEqual({ key: "chat.context.all", params: {} });
    expect(contextLineKey(undefined)).toEqual({ key: "chat.context.all", params: {} });
    expect(contextLineKey(view({ primary: { entity_type: "change_request", entity_id: 3, ref: "C#3", title: null } })))
      .toEqual({ key: "chat.context.linked", params: { ref: "C#3", title: "", account: "" } });
  });
});
