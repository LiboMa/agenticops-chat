/** Where the chat list goes (MVP-2.8.0 S2 rework, owner 2026-11-09). The chat page keeps the full sidebar, so the
 *  list sits beside the conversation only where there is room: ≥ 1280 px (the width the issue queue splits at),
 *  and 768–800 px, where the sidebar is the top-bar menu. Elsewhere it slides over the conversation — below 768 px
 *  the phone drawer, 801–1279 px beside the full sidebar (it would leave the conversation ~370 px at 801 px). */
export function chatListAsDrawer(width: number): boolean {
  return width < 768 || (width > 800 && width < 1280);
}

/** The same boundaries for `useMediaQuery`. */
export const CHAT_LIST_DRAWER_MEDIA = "(max-width: 767px), (min-width: 801px) and (max-width: 1279px)";
