/**
 * A chat's context on the frontend (MVP-2.7.0 S5): what a new chat is created with, and the one line the page shows
 * about it. The server resolves and checks the context (services/chat_context); a linked object's account is the
 * object's own, so the client never sends one with a link. Pure, so node can test it.
 */
import type { ChatContextView } from "@/api/types";
import type { ContextRef } from "@/lib/contextRef";

export interface NewChatContext {
  primary: { entity_type: "health_issue" | "change_request"; entity_id: number } | null;
  account_id: number | null;
}

export function contextForNewChat(ref: ContextRef | null, scopeAccountId: number | null): NewChatContext {
  if (ref) return { primary: { entity_type: ref.kind === "issue" ? "health_issue" : "change_request", entity_id: ref.id }, account_id: null };
  return { primary: null, account_id: scopeAccountId };
}

export function contextLineKey(ctx: ChatContextView | null | undefined): { key: string; params: Record<string, string> } {
  if (ctx?.primary) return { key: "chat.context.linked", params: { ref: ctx.primary.ref, title: ctx.primary.title ?? "", account: ctx.account_name ?? "" } };
  if (ctx?.account_id) return { key: "chat.context.bound", params: { account: ctx.account_name ?? `#${ctx.account_id}` } };
  return { key: "chat.context.all", params: {} };
}
