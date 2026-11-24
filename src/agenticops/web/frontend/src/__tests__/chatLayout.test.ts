import { describe, expect, it } from "vitest";
import { CHAT_LIST_DRAWER_MEDIA, chatListAsDrawer } from "@/lib/chatLayout";

/** MVP-2.8.0 S2 rework (owner 2026-11-09): the chat page keeps the full sidebar; the chat list sits beside the
 *  conversation only where there is room — ≥ 1280 px, and 768–800 px where the sidebar is the top-bar menu —
 *  and slides over it otherwise (below 768 px the phone drawer, 801–1279 px beside the full sidebar). */
describe("chatListAsDrawer", () => {
  it.each([320, 390, 767, 801, 1024, 1100, 1279])("%i px → a drawer over the conversation", (w) => {
    expect(chatListAsDrawer(w)).toBe(true);
  });
  it.each([768, 800, 1280, 1440])("%i px → beside the conversation", (w) => {
    expect(chatListAsDrawer(w)).toBe(false);
  });
  it("the media query says the same boundaries", () => {
    expect(CHAT_LIST_DRAWER_MEDIA).toBe("(max-width: 767px), (min-width: 801px) and (max-width: 1279px)");
  });
});
