# Design: Concurrent Chat Sessions + Fast Session Open (WebUI)

**Date:** 2026-06-01
**Branch context:** `cycle3-skills-autonomy`
**Status:** Approved design → ready for implementation plan

## Problem

The WebUI chat has three UX defects:

1. **Slow session open.** Opening an existing session blocks for seconds. Root cause:
   `GET /api/chat/sessions/{id}` loads **every** message (`db.query(ChatMessage)...all()`,
   no `LIMIT`/cursor — `app.py:3854`), the frontend renders all of them with
   `messages.map()` (no virtualization — `MessageList.tsx:59`), and `useChatSession`
   **refetches the entire history every 5 s** (`staleTime: 5_000`).

2. **No concurrent conversations.** Opening a second chat while one is streaming "sticks"
   all output to the first conversation. Root cause: the SSE read-loop lives **inside the
   mounted `Chat` page** via `useChat` with a single `AbortController` (`useChat.ts`).
   Navigating away orphans the stream; the input is globally disabled while `streaming`.
   (Same-session double-send hitting Strands' `_invocation_lock` / `ConcurrencyException`
   is *correct* and intentionally preserved — one turn per conversation.)

3. **Markdown re-parse cost.** Streaming appends one token at a time and re-parses the full
   accumulated markdown on every token (`MessageList.tsx:39`) — O(n²) for n tokens.

## Goals (user-selected)

- **Background streaming, Gemini-like**: responses keep generating when you navigate away;
  multiple sessions stream at once; switch back and see live progress. Survives in-app
  navigation; **does not** survive a hard page reload (in-flight stream is lost; history
  shows the persisted partial).
- **Many sessions, one app**: switch freely between conversations inside one browser tab
  with several generating at once. (Cross-tab/window sync is explicitly **out of scope**.)
- **Cursor pagination + virtualization**: future-proof for any history size.
- **Moderate refactor**: contained to the chat layer + one new endpoint + one DB index.

## Non-goals (YAGNI)

- Server-side job model / event buffer (would be needed only for reload-survival or
  cross-tab sync — not chosen).
- Cross-tab / multi-window synchronization.
- New layout, command palette, or chat redesign.
- Changes to the SSE wire protocol, message preprocessor, persistence, or auto-naming.

## Key de-risking findings (from codebase exploration)

- **Backend per-request state is `contextvars`-isolated** (`config.py:803-934`:
  `_detail_level_var`, `_scan_focus_var`, `_trace_id_var`). Concurrent streams to
  *different* sessions do not cross-talk.
- **Streaming is already per-session isolated** on the backend: one `EventSourceResponse`
  + one cached `Agent` per `session_id` (`session_manager.py`, `app.py:4101,4219`).
  → **No backend concurrency rework required.** The concurrency problem is entirely
  frontend: the stream is tied to a component that unmounts on navigation.
- `pendingMessage`/`pendingFile`/`clearPending` in `useLazySessionCreate.ts` are **dead
  code** (set, never consumed). The first-message path goes through navigation + a fresh
  `useChat` bind. The store refactor replaces this with `store.send(newId, ...)` directly.
- `detail?.messages` has exactly **one** consumer: `Chat.tsx:272`. Making the detail
  endpoint metadata-only is a single-callsite migration.

## Architecture

Move the SSE read-loop **out of the React component tree** into a module-level store keyed
by `session_id`. Because the HTTP connection then lives in the store (not an unmounting
component), streams survive navigation and multiple sessions stream simultaneously. Pair
with cursor pagination + virtualization so opening a session paints instantly.

### Frontend units

| Unit | File | Responsibility |
|---|---|---|
| **Stream store** | `lib/chatStream.ts` *(new)* | Framework-agnostic singleton. `Map<sessionId, StreamState>`, owns the `AbortController`s and the SSE parse loop (lifted verbatim from `useChat`). API: `send(sessionId, content, file?, detailLevel?)`, `cancel(sessionId)`, `getSnapshot(sessionId)`, `subscribe(sessionId, cb)`, `subscribeActive(cb)`, `activeSessions()`. Token emit **throttled ~60 ms** (coalesce tokens; fixes O(n²) re-parse). Calls injected callbacks on `done`/`session_renamed` to update the TanStack cache. No new dep — designed for React 18 `useSyncExternalStore`. |
| **Stream hook** | `hooks/useSessionStream.ts` *(new; replaces `useChat`)* | `useSyncExternalStore` adapter reading one session's slice. Returns `{ streaming, content, toolCalls, tokenMetrics, error, send, cancel }`. Same surface as today's `useChat` so `Chat.tsx`/`ChatInput` wiring barely changes. |
| **Paginated messages** | `hooks/useChatMessages.ts` *(new)* | `useInfiniteQuery` (TanStack already installed). Loads the newest page on mount; `fetchOlder()` triggered on scroll-up. Flattens pages oldest→newest. Optimistic append on stream `done` so the completed assistant message appears without a refetch flicker. |
| **Virtualized list** | `components/chat/MessageList.tsx` *(rewrite)* | `@tanstack/react-virtual` (the one new dep). Dynamic row measurement, reverse-infinite-scroll at the top (load older), sticky-to-bottom while streaming, renders the streaming bubble from the store slice. |

`Chat.tsx` changes: drop local stream state; read the per-session slice via
`useSessionStream(selectedId)`; input disabled **only when that session streams** (not
globally). Messages come from `useChatMessages(selectedId)` instead of `detail?.messages`.

`SessionFlyout.tsx`: subscribe to `store.subscribeActive` to render a live ● indicator on
each session that is actively streaming.

Welcome / first-message flow: `create session → store.send(newId, content, file) →
navigate(/app/chat/newId)`. Deletes the dead `pendingMessage` machinery in
`useLazySessionCreate.ts` (hook reduced to create+navigate, or folded into the store call).

### Backend changes

1. **New endpoint** `GET /api/chat/sessions/{id}/messages?limit=50&before=<msg_id>`
   → `{ messages: ChatMessageResponse[], has_more: bool, next_cursor: int | null }`.
   - Cursor = `ChatMessage.id` (monotonic autoincrement; no clock dependency).
   - `before` omitted → newest `limit` rows. `before=<id>` → rows with `id < before`,
     newest-first by query then reversed to chronological for the response.
   - `limit` capped (`le=100`, default 50).
   - New schema `ChatMessagesPage` in `schemas.py`.

2. **`GET /api/chat/sessions/{id}` becomes metadata-only.** Stops shipping the full
   history (removes the multi-second open and the 5 s full refetch). Decision (minimal
   churn): `ChatSessionDetail` **keeps** its `messages: List[ChatMessageResponse] = []`
   field for type stability, but the endpoint **no longer populates it** (always returns
   `[]`). The frontend `ChatSessionDetail` type marks `messages` optional/deprecated and
   no caller reads it — history comes exclusively from `useChatMessages`.

3. **DB index** on `chat_messages (session_id, id)` to make the `before`-cursor range scan
   efficient. Added non-destructively in the `init_db` migration block (`models.py`),
   consistent with existing migration style. Idempotent (`CREATE INDEX IF NOT EXISTS`).

### Data flow — concurrent streams

```
send(A) ─► store.state[A].streaming=true; fetch POST /sessions/A/messages
           (HTTP connection + read-loop owned by the STORE, not a component)
send(B) ─► store.state[B].streaming=true; fetch POST /sessions/B/messages   ← independent

navigate A→B→A : components re-subscribe to a different slice; the read-loops are
                 untouched in the store (no abort on unmount).

on "done"(A)   : optimistic useChatMessages cache append (assistant msg) + clear slice[A]
                 + invalidate ['chat-sessions'] (updates name / last_activity / order).
```

Backend `contextvars` isolate `detail_level` / `scan_focus` / `trace_id` per async task →
no cross-talk between concurrent streams.

### Error handling

- Error is stored per-session; one failing stream never affects another.
- `cancel(sessionId)` aborts only that session's `AbortController`.
- Hard reload loses in-flight streams **by design** (chosen tradeoff); the backend already
  persists partial replies on disconnect/error (`app.py:4146`, `app.py:4209`) so history
  shows what was generated. Unchanged.
- Network/HTTP errors surface in the per-session slice and render in the existing error
  banner.

### Performance

- **Open latency**: metadata-only detail + newest-50 page → first paint independent of
  history size.
- **DOM size**: virtualization keeps ~visible rows mounted regardless of total messages.
- **Streaming CPU**: ~60 ms token coalescing removes the per-token full-markdown re-parse.
- **Refetch churn**: replace the 5 s full-history refetch with optimistic cache append on
  `done`; pages are otherwise static once loaded.

## Testing

**Backend (pytest)**
- `GET /sessions/{id}/messages`: default newest page; `before` cursor returns older rows;
  `has_more`/`next_cursor` correctness; empty session; `limit` cap.
- `GET /sessions/{id}` returns metadata only (no `messages` payload / empty list).
- Index creation is idempotent.

**Frontend (vitest)**
- `chatStream` store: two concurrent sessions remain isolated (tokens, errors, done);
  `cancel` affects only its session; token throttle coalesces; `done` clears the slice and
  fires the cache-append callback.
- `useChatMessages`: page flattening oldest→newest; `fetchOlder` appends older page at top;
  optimistic append ordering.

**Manual**
- Two sessions streaming at once; switch between them mid-stream and confirm both continue
  and show live progress; input enabled/disabled per-session.
- Scroll to top → older page loads; sticky-bottom holds while streaming.
- Open a large session → instant paint.

## Scope guardrails

- **One** new dependency: `@tanstack/react-virtual` (~6 kb, same family as the installed
  `@tanstack/react-query`, no notable transitive deps). Flagged explicitly per project
  preference against unnecessary deps — justified because variable-height chat
  virtualization with reverse-scroll + sticky-bottom is error-prone to hand-roll.
- Touched: `lib/chatStream.ts` (new), `hooks/useSessionStream.ts` (new, replaces
  `useChat.ts`), `hooks/useChatMessages.ts` (new), `components/chat/MessageList.tsx`
  (rewrite), `pages/Chat.tsx`, `components/chat/SessionFlyout.tsx`,
  `hooks/useLazySessionCreate.ts` (simplify), `hooks/useChatSession.ts` (metadata-only
  type), `api/types.ts`; backend `web/app.py` (+1 endpoint, detail trimmed),
  `web/schemas.py` (+`ChatMessagesPage`), `models.py` (index).
- Untouched: SSE protocol, `preprocessor`, persistence writes, auto-naming, session
  TTL/summary, Strands agent lifecycle.

## Documentation (per CLAUDE.md rule 7)

After implementation, update `docs/WORKFLOW.md` (chat/session interaction notes) and the
MVP release doc as appropriate to reflect concurrent sessions + pagination.
