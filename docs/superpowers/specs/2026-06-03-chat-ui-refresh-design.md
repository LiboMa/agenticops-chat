# Design: Chat + Session UI Refresh (open-webui style, blue/white minimal)

**Date:** 2026-06-03
**Status:** Approved design → ready for implementation plan
**Scope:** Pure visual refresh of the web Chat experience (composer + session sidebar +
message list). **No logic, hooks, backend, state, or persistence changes.**

## Goal

Make the WebUI chat look and feel like open-webui — clean, spacious, minimal — using a
**blue/white** palette, so the experience is simpler, more pleasant, and stays fast. Guiding
words (user's): 简约、大方、易用、流畅 (simple, generous, usable, smooth).

## Visual direction (locked via visual companion)

- **Layout:** open-webui structure (grouped session list, roomy message area, floating pill composer).
- **Palette:** blue/white. Reuse the EXISTING `--primary-*` tokens (already blue, hue 217–224) — minimal token work; the change is layout + spacing + organization, not a new color system.
- **Session sidebar:** **minimal — neutral gray active-fill + blue accents** (blue used only for `+ New`, the streaming dot, links). Largest white space, most restrained.
- **Message area:** **open-webui original — user = soft-blue bubble (right); assistant = no bubble, flat text (left) + avatar.** Best for reading long answers / logs / configs.
- **Composer:** floating **pill** (rounded, soft shadow, round blue send ↑).

## Decisions (locked)

| Decision | Choice |
|----------|--------|
| Scope boundary | **Pure visual refactor** — only `SessionFlyout`, `ChatInput`, `MessageList`, `index.css`. No hook/backend/state logic. |
| Time grouping | **Yes** — Pinned / Today / Yesterday / Previous 7 days / Older. Pure frontend render via a new `groupSessions` function (unit-testable). Layers on top of existing `sortSessions`/`filterArchived`. |
| Composer ⚙ icon | **Keep the detail-level dropdown** (Concise/Medium/Detailed) — relocated into the pill, no new feature. |
| Dark mode | **Both light + dark verified** — reuse existing `.dark` CSS variables (already defined). |

## Non-goals (YAGNI / out of scope)

- Message actions (copy / regenerate / 👍👎) — these are **later phases**, only *positioned* in the mockup, NOT built here.
- Tool-call expandable input/result detail — that's the separate Phase-2 backend work; this refresh only restyles the existing tool chip.
- Any change to streaming, concurrency (`chatStream`), pagination (`useChatMessages`), attachments (the just-shipped paste/drop), pin/star/archive backend, search, or the SSE protocol.
- Global theme rollout to other pages (Dashboard, etc.) — chat only.
- Syntax highlighting / mermaid / markdown engine changes — separate phases.

## Architecture (what changes, by file)

All changes are presentational. The data, hooks, and handlers stay exactly as they are.

### Unit 1 — `lib/groupSessions.ts` (new, pure, testable)

The only new "logic", and it's pure rendering organization (no IO):

```
SessionGroup = { label: string; sessions: ChatSession[] }

groupSessions(sessions: ChatSession[]): SessionGroup[]
  // Input is the ALREADY sorted+filtered list (from sortSessions/filterArchived).
  // Buckets, in order, skipping empties:
  //   "Pinned"          → pinned === true (regardless of date)
  //   "Starred"         → starred && !pinned
  //   "Today"           → last_activity_at within today (local)
  //   "Yesterday"       → previous calendar day
  //   "Previous 7 days" → within 7 days, older than yesterday
  //   "Previous 30 days"→ within 30 days
  //   "Older"           → everything else
  // A session appears in exactly one bucket (pinned/starred take precedence over date).
```

Takes a "now" timestamp parameter (or reads `Date.now()` at call site) so it's deterministically testable. Pure — no React, unit-tested in the node vitest env like `sortSessions`.

### Unit 2 — `components/chat/SessionFlyout.tsx` (restyle + group render)

- Render `groupSessions(...)` output: each group = a small uppercase gray label + its rows.
- **Row:** neutral — `hover:bg-muted` only; **active session = subtle gray fill** (`bg-muted`/`bg-slate-100`) + slightly bolder text, **blue streaming dot** when that session is in `useActiveStreamingSessions()` (already wired). No left bar, no solid-blue fill.
- **Remove always-on emoji** (📌⭐ prefix + the 📌📍⭐☆📁🗑 action cluster). Pin/star state shown by a small muted icon only when set; the action buttons (pin/star/archive/delete/rename) move into a **hover-revealed** row (the handlers already exist — `useUpdateChatSession`, `useDeleteChatSession`, `useRenameChatSession`, double-click rename). No handler changes.
- Header: `Chats` title + a blue **`+ New`** button (replaces the bare `＋`). Search box restyled (rounded, `bg-muted`).
- Footer: keep `Show archived` toggle + `N sessions` count, restyled.

### Unit 3 — `pages/Chat.tsx` (toolbar + spacing only)

- Session toolbar: center the session name, lighten borders, restyle the `Save as Report` button as a quiet outline chip. No behavior change (flyout toggle, save dialog, context panel all unchanged).
- Spacing/container tweaks to match the roomier feel. The three-zone layout (flyout / chat / context panel) and all resizing logic are **unchanged**.

### Unit 4 — `components/chat/MessageList.tsx` (bubble restyle)

- **User message:** soft-blue bubble, right-aligned, rounded (`bg-primary-50 border-primary-100`, already close — refine radius/spacing).
- **Assistant message:** **no bubble** — flat text on the page background, left-aligned, with the existing `AI` avatar. Increase inter-message spacing for breathing room.
- Tool-call chip restyled to the blue accent (still the existing `ToolCallChip` — no new expand behavior here).
- Streaming bubble + "Thinking…" indicator + virtualization + scroll-anchoring (just shipped) — **untouched logic**, only color/spacing classes.
- Markdown rendering (`renderMarkdown` / `renderMessageMarkdown` memo) — **unchanged**; only the surrounding container styling. Inline code/commands get a light gray chip style via CSS.

### Unit 5 — `components/chat/ChatInput.tsx` (pill composer)

- Wrap the existing controls in a **floating pill**: rounded-full container, soft shadow, `bg-background`. Left: 📎 attach (round, muted). The detail-level `<select>` becomes a compact control inside the pill. Right: a **round blue send button** (↑) / red stop when streaming.
- **All existing behavior preserved**: paste/drag-drop, multi-attachment badges, validation errors, Cmd+Enter, disabled-while-streaming, the capture-phase drag `useEffect`. Only the wrapper markup/classes change; the attachment badges restyle to match but keep id-keyed removal.

### Unit 6 — `index.css` (token/utility touch-ups, minimal)

- The blue `--primary-*` tokens already exist (light + dark). Add only what's missing: a couple of utility classes if needed for the pill shadow / group label / inline-code chip, and verify dark-mode values for the new surfaces. **No restructuring of the token system.**

## Data flow

Unchanged. `useChatSessions` → `sortSessions` → `filterArchived` → **`groupSessions`** (new,
render-only) → grouped render. Everything downstream of the session list (selection,
streaming via `chatStream`, messages via `useChatMessages`, attachments) is identical.

## Error handling

No new error paths — this is presentational. Existing error banner, validation messages, and
empty/welcome states are restyled but functionally unchanged.

## Performance (a stated goal — 流畅)

- `groupSessions` is O(n) over a small session list (tens), called on the already-memoized
  list — negligible. Memoize with `useMemo` keyed on the sorted+filtered array.
- No new dependencies, no new network calls, no new re-render triggers. Virtualized message
  list and the per-session streaming store are untouched, so streaming stays smooth.
- CSS-only visual changes don't affect render cost; avoid heavy shadows/blurs (use a single
  subtle box-shadow on the pill).

## Testing

**Frontend (vitest, node env — pure logic only, matching existing style):**
- `groupSessions.test.ts`: pinned/starred precedence over date; Today/Yesterday/7-day/30-day/Older bucketing given a fixed "now"; empty buckets omitted; a session lands in exactly one bucket; stable order within a bucket (preserves input order from `sortSessions`).

**Manual (Playwright smoke, both themes):**
- Light + dark: session groups render with labels; active session has gray fill + blue dot when streaming; hover reveals pin/star/archive/delete; `+ New` works; search/filter unchanged.
- Message area: user blue bubble vs assistant flat text; tool chip; streaming bubble; scroll-anchored older-page load still works.
- Composer pill: paste image → badge; drag files; detail-level select; send/stop; Cmd+Enter. (Re-run the existing paste/drop smoke checks to confirm no regression.)
- Verify `npx tsc --noEmit && npm run build && npm run test` clean.

## Scope guardrails

- **Touched:** `lib/groupSessions.ts` (new) + `__tests__/groupSessions.test.ts` (new);
  `components/chat/SessionFlyout.tsx`, `MessageList.tsx`, `ChatInput.tsx`, `pages/Chat.tsx`,
  `index.css` (restyle only).
- **Untouched:** all hooks (`useChatSessions`, `useChatMessages`, `useSessionStream`,
  `useLazySessionCreate`, `chatStream`), backend, `models.py`, SSE, pagination, attachments
  logic, pin/star/archive/search behavior, `sortSessions`/`filterArchived`.
- **No new dependencies.** **No new features** (message actions / tool-detail / highlighting
  are out of scope).

## Documentation (per CLAUDE.md rule 7)

After implementation, note the chat UI refresh in `docs/WORKFLOW.md` and the next release notes.
