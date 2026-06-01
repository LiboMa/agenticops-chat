# Concurrent Chat Sessions + Fast Session Open — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the WebUI chat support many concurrently-streaming sessions in one app and open any session instantly, by moving the SSE read-loop into a module-level store keyed by `session_id` and adding cursor-paginated, virtualized message loading.

**Architecture:** Backend gains a cursor-paginated `GET /sessions/{id}/messages` endpoint, a metadata-only detail endpoint, and a `(session_id, id)` index. Frontend lifts the streaming loop out of the `Chat` page into a framework-agnostic `chatStream` singleton (so streams survive navigation), reads it via `useSyncExternalStore`, paginates history with `useInfiniteQuery`, and virtualizes the message list with `@tanstack/react-virtual` (with an immutable-message markdown memo).

**Tech Stack:** FastAPI + SQLAlchemy + SQLite (backend); React 18 + TypeScript + TanStack Query + `@tanstack/react-virtual` + Vite/Vitest (frontend); pytest + Starlette TestClient (backend tests).

**Spec:** `docs/superpowers/specs/2026-06-01-concurrent-chat-sessions-design.md`

---

## Conventions for this plan

- **Backend tests:** `python -m pytest tests/<file> -v`. The DB is the real configured SQLite (`data/agenticops.db`); tests seed + clean their own rows (follow `tests/test_chat_api.py` pattern). No special fixture file needed — `TestClient(app)` + `get_db_session()`.
- **Frontend tests:** from `src/agenticops/web/frontend/`, run `npm run test` (vitest `--run`). Test env is `node` (set in `vite.config.ts`); pure-logic tests only — no DOM rendering tests (keeps with existing `sessionSort.prop.test.ts` style). Alias `@` → `./src`.
- **Type-check / build (frontend):** `cd src/agenticops/web/frontend && npx tsc --noEmit && npm run build`.
- **Compile (backend):** `python3 -m py_compile src/agenticops/web/app.py src/agenticops/web/schemas.py src/agenticops/models.py`.
- **Commits:** frequent, one per task. Push (if asked) uses `git push --no-verify`.
- **Branch:** work proceeds on the current branch `cycle3-skills-autonomy` unless told otherwise.

---

## File Structure

**Backend (modify):**
- `src/agenticops/web/schemas.py` — add `ChatMessagesPage`; mark `ChatSessionDetail.messages` deprecated/optional.
- `src/agenticops/web/app.py` — add `GET /api/chat/sessions/{id}/messages`; make `GET /api/chat/sessions/{id}` metadata-only.
- `src/agenticops/models.py` — add `(session_id, id)` index on `chat_messages` in `init_db`.

**Backend (test):**
- `tests/test_chat_messages_pagination.py` *(new)* — pagination endpoint + metadata-only detail.

**Frontend (create):**
- `src/agenticops/web/frontend/src/lib/chatStream.ts` — the streaming store singleton.
- `src/agenticops/web/frontend/src/lib/markdownCache.ts` — immutable-message markdown memo.
- `src/agenticops/web/frontend/src/hooks/useSessionStream.ts` — `useSyncExternalStore` adapter (replaces `useChat`).
- `src/agenticops/web/frontend/src/hooks/useChatMessages.ts` — `useInfiniteQuery` paginated history.

**Frontend (modify):**
- `src/agenticops/web/frontend/src/api/types.ts` — add `ChatMessagesPage`; deprecate `ChatSessionDetail.messages`.
- `src/agenticops/web/frontend/src/components/chat/MessageList.tsx` — rewrite with virtualization + markdown memo + older-page loading.
- `src/agenticops/web/frontend/src/pages/Chat.tsx` — use store + paginated messages; per-session input disable.
- `src/agenticops/web/frontend/src/components/chat/SessionFlyout.tsx` — live ● streaming indicator.
- `src/agenticops/web/frontend/src/hooks/useLazySessionCreate.ts` — simplify (drop dead `pendingMessage`); call store.
- `src/agenticops/web/frontend/package.json` — add `@tanstack/react-virtual`.

**Frontend (test):**
- `src/agenticops/web/frontend/src/__tests__/chatStream.test.ts` *(new)* — store isolation + lifecycle.

**Frontend (delete):**
- `src/agenticops/web/frontend/src/hooks/useChat.ts` — superseded by `useSessionStream.ts` (deleted in Task 9 after Chat.tsx migrates).

---

## Task 1: Backend — DB index on `chat_messages (session_id, id)`

**Files:**
- Modify: `src/agenticops/models.py` (the `init_db` function, chat-sessions migration area ~line 893)

- [ ] **Step 1: Add idempotent index migration**

In `src/agenticops/models.py`, inside `init_db()`, immediately AFTER the existing
"add pinned/starred/archived columns to chat_sessions" migration block (the block ending
with the `pinned/starred/archived` `conn.commit()` around line 894) and BEFORE the
"add fingerprint dedup columns to health_issues" block, insert:

```python
    # Migration: composite index on chat_messages for cursor pagination.
    # chat_messages had NO indexes; this makes (session_id, id) range scans
    # for the paginated /messages endpoint efficient. Idempotent.
    if insp.has_table("chat_messages"):
        with engine.connect() as conn:
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_chat_message_session_id "
                "ON chat_messages(session_id, id)"
            ))
            conn.commit()
```

- [ ] **Step 2: Apply the migration against the live DB and verify the index exists**

Run:
```bash
cd /Users/malibo/MyDev/AgenticOps
python3 -c "from agenticops.models import init_db; init_db()"
sqlite3 data/agenticops.db "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='chat_messages';"
```
Expected output includes: `idx_chat_message_session_id`

- [ ] **Step 3: Verify idempotency (re-run does not error)**

Run:
```bash
cd /Users/malibo/MyDev/AgenticOps
python3 -c "from agenticops.models import init_db; init_db(); init_db()"
echo "OK exit=$?"
```
Expected: `OK exit=0` (no exception on second call)

- [ ] **Step 4: Compile check**

Run: `python3 -m py_compile src/agenticops/models.py`
Expected: no output (success)

- [ ] **Step 5: Commit**

```bash
cd /Users/malibo/MyDev/AgenticOps
git add src/agenticops/models.py
git commit --no-verify -m "perf(db): add (session_id, id) index on chat_messages for cursor pagination"
```

---

## Task 2: Backend — `ChatMessagesPage` schema + deprecate detail messages

**Files:**
- Modify: `src/agenticops/web/schemas.py:609-610` (`ChatSessionDetail`)

- [ ] **Step 1: Add the page schema and deprecate `ChatSessionDetail.messages`**

In `src/agenticops/web/schemas.py`, replace the `ChatSessionDetail` class (lines 609-610):

```python
class ChatSessionDetail(ChatSessionResponse):
    messages: List[ChatMessageResponse] = []
```

with:

```python
class ChatSessionDetail(ChatSessionResponse):
    # DEPRECATED: history now comes from GET /sessions/{id}/messages (paginated).
    # Kept for type stability; the detail endpoint always returns [].
    messages: List[ChatMessageResponse] = []


class ChatMessagesPage(BaseModel):
    """One page of chat messages, ordered oldest→newest (chronological).

    Cursor is ChatMessage.id (monotonic). `next_cursor` is the id to pass as
    `before` to fetch the immediately-older page; null when no older page exists.
    """
    messages: List[ChatMessageResponse] = []
    has_more: bool = False
    next_cursor: Optional[int] = None
```

- [ ] **Step 2: Compile check**

Run: `python3 -m py_compile src/agenticops/web/schemas.py`
Expected: no output (success)

- [ ] **Step 3: Commit**

```bash
cd /Users/malibo/MyDev/AgenticOps
git add src/agenticops/web/schemas.py
git commit --no-verify -m "feat(api): add ChatMessagesPage schema; deprecate ChatSessionDetail.messages"
```

---

## Task 3: Backend — paginated `/messages` endpoint + metadata-only detail (TDD)

**Files:**
- Create: `tests/test_chat_messages_pagination.py`
- Modify: `src/agenticops/web/app.py:3848-3871` (detail endpoint) + add new endpoint after it

- [ ] **Step 1: Write the failing tests**

Create `tests/test_chat_messages_pagination.py`:

```python
"""Tests for cursor-paginated chat messages endpoint + metadata-only detail.

Validates the concurrent-chat-sessions design:
- GET /sessions/{id}/messages?limit=&before= returns chronological page + cursor
- GET /sessions/{id} returns metadata only (no messages payload)
"""

from datetime import datetime, timezone

import pytest
from starlette.testclient import TestClient

from agenticops.web.app import app
from agenticops.models import ChatSession, ChatMessage, get_db_session


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def _seed_session_with_messages():
    """Create a session with 120 messages (ids ascending)."""
    sid = "page-test-session-001"
    now = datetime.now(timezone.utc)
    with get_db_session() as db:
        s = ChatSession(session_id=sid, name="Page Test",
                        created_at=now, updated_at=now, last_activity_at=now)
        db.add(s)
        db.flush()
        for i in range(120):
            db.add(ChatMessage(
                session_id=s.id,
                role="user" if i % 2 == 0 else "assistant",
                content=f"msg-{i:03d}",
            ))
    yield sid
    with get_db_session() as db:
        row = db.query(ChatSession).filter(ChatSession.session_id == sid).first()
        if row:
            db.query(ChatMessage).filter(ChatMessage.session_id == row.id).delete()
            db.delete(row)


class TestMessagesPagination:
    def test_default_returns_newest_page_chronological(self, client, _seed_session_with_messages):
        sid = _seed_session_with_messages
        resp = client.get(f"/api/chat/sessions/{sid}/messages", params={"limit": 50})
        assert resp.status_code == 200
        body = resp.json()
        # newest 50 messages, returned oldest→newest
        assert len(body["messages"]) == 50
        contents = [m["content"] for m in body["messages"]]
        assert contents == sorted(contents)  # chronological ascending
        assert contents[-1] == "msg-119"     # last is the newest
        assert contents[0] == "msg-070"      # newest 50 = msg-070..msg-119
        assert body["has_more"] is True
        assert body["next_cursor"] is not None

    def test_before_cursor_returns_older_page(self, client, _seed_session_with_messages):
        sid = _seed_session_with_messages
        first = client.get(f"/api/chat/sessions/{sid}/messages", params={"limit": 50}).json()
        cursor = first["next_cursor"]
        older = client.get(
            f"/api/chat/sessions/{sid}/messages",
            params={"limit": 50, "before": cursor},
        ).json()
        assert len(older["messages"]) == 50
        older_contents = [m["content"] for m in older["messages"]]
        # older page is msg-020..msg-069 (the 50 immediately before the newest 50)
        assert older_contents[-1] == "msg-069"
        assert older_contents[0] == "msg-020"
        # no overlap with the first page
        first_contents = {m["content"] for m in first["messages"]}
        assert not (set(older_contents) & first_contents)

    def test_last_page_has_more_false(self, client, _seed_session_with_messages):
        sid = _seed_session_with_messages
        # walk to the oldest page (120 msgs / 50 = pages of 50,50,20)
        p1 = client.get(f"/api/chat/sessions/{sid}/messages", params={"limit": 50}).json()
        p2 = client.get(f"/api/chat/sessions/{sid}/messages",
                        params={"limit": 50, "before": p1["next_cursor"]}).json()
        p3 = client.get(f"/api/chat/sessions/{sid}/messages",
                        params={"limit": 50, "before": p2["next_cursor"]}).json()
        assert len(p3["messages"]) == 20
        assert p3["messages"][0]["content"] == "msg-000"
        assert p3["has_more"] is False
        assert p3["next_cursor"] is None

    def test_empty_session_returns_empty_page(self, client):
        sid = "page-test-empty-002"
        now = datetime.now(timezone.utc)
        with get_db_session() as db:
            db.add(ChatSession(session_id=sid, name="Empty",
                               created_at=now, updated_at=now, last_activity_at=now))
        try:
            resp = client.get(f"/api/chat/sessions/{sid}/messages")
            assert resp.status_code == 200
            body = resp.json()
            assert body["messages"] == []
            assert body["has_more"] is False
            assert body["next_cursor"] is None
        finally:
            with get_db_session() as db:
                row = db.query(ChatSession).filter(ChatSession.session_id == sid).first()
                if row:
                    db.delete(row)

    def test_nonexistent_session_404(self, client):
        resp = client.get("/api/chat/sessions/does-not-exist-xyz/messages")
        assert resp.status_code == 404

    def test_limit_capped_at_100(self, client, _seed_session_with_messages):
        sid = _seed_session_with_messages
        resp = client.get(f"/api/chat/sessions/{sid}/messages", params={"limit": 500})
        assert resp.status_code == 422  # Query(le=100) rejects >100


class TestDetailMetadataOnly:
    def test_detail_returns_no_messages(self, client, _seed_session_with_messages):
        sid = _seed_session_with_messages
        resp = client.get(f"/api/chat/sessions/{sid}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["messages"] == []          # metadata-only now
        assert body["message_count"] == 120     # count still accurate
        assert body["name"] == "Page Test"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_chat_messages_pagination.py -v`
Expected: FAIL — `TestMessagesPagination` 404s (endpoint missing) and `test_detail_returns_no_messages` fails because detail still returns 120 messages.

- [ ] **Step 3: Make the detail endpoint metadata-only**

In `src/agenticops/web/app.py`, replace the `api_get_chat_session` body (lines 3848-3871):

```python
@app.get("/api/chat/sessions/{session_id}", response_model=ChatSessionDetail)
async def api_get_chat_session(session_id: str):
    with get_db_session() as db:
        row = db.query(ChatSession).filter(ChatSession.session_id == session_id).first()
        if not row:
            raise HTTPException(404, "Session not found")
        msgs = (
            db.query(ChatMessage)
            .filter(ChatMessage.session_id == row.id)
            .order_by(ChatMessage.created_at.asc())
            .all()
        )
        return ChatSessionDetail(
            id=row.id, session_id=row.session_id, name=row.name,
            created_at=row.created_at, updated_at=row.updated_at,
            last_activity_at=row.last_activity_at,
            message_count=len(msgs),
            pinned=row.pinned, starred=row.starred, archived=row.archived,
            messages=[ChatMessageResponse(
                id=m.id, role=m.role, content=m.content,
                tool_calls=m.tool_calls, token_usage=m.token_usage,
                created_at=m.created_at,
            ) for m in msgs],
        )
```

with (metadata-only; uses a COUNT instead of loading rows):

```python
@app.get("/api/chat/sessions/{session_id}", response_model=ChatSessionDetail)
async def api_get_chat_session(session_id: str):
    """Session metadata only. History is fetched via the paginated
    /sessions/{id}/messages endpoint. `messages` is always [] (deprecated)."""
    with get_db_session() as db:
        row = db.query(ChatSession).filter(ChatSession.session_id == session_id).first()
        if not row:
            raise HTTPException(404, "Session not found")
        cnt = db.query(func.count(ChatMessage.id)).filter(
            ChatMessage.session_id == row.id
        ).scalar()
        return ChatSessionDetail(
            id=row.id, session_id=row.session_id, name=row.name,
            created_at=row.created_at, updated_at=row.updated_at,
            last_activity_at=row.last_activity_at,
            message_count=cnt,
            pinned=row.pinned, starred=row.starred, archived=row.archived,
            messages=[],
        )
```

- [ ] **Step 4: Add the paginated messages endpoint**

In `src/agenticops/web/app.py`, immediately AFTER the `api_get_chat_session` function
(after the block you just edited, before `api_rename_chat_session` at line 3874), insert:

```python
@app.get("/api/chat/sessions/{session_id}/messages", response_model=ChatMessagesPage)
async def api_get_chat_messages(
    session_id: str,
    limit: int = Query(default=50, ge=1, le=100),
    before: Optional[int] = Query(default=None, description="Return messages with id < before (older page)"),
):
    """Cursor-paginated chat history, newest-first window returned in
    chronological (oldest→newest) order. Cursor = ChatMessage.id."""
    with get_db_session() as db:
        row = db.query(ChatSession).filter(ChatSession.session_id == session_id).first()
        if not row:
            raise HTTPException(404, "Session not found")

        q = db.query(ChatMessage).filter(ChatMessage.session_id == row.id)
        if before is not None:
            q = q.filter(ChatMessage.id < before)
        # Fetch newest `limit + 1` (descending) to detect has_more, then reverse.
        rows_desc = q.order_by(ChatMessage.id.desc()).limit(limit + 1).all()

        has_more = len(rows_desc) > limit
        page = rows_desc[:limit]                 # newest `limit` (still descending)
        page_chrono = list(reversed(page))       # oldest→newest for the client
        next_cursor = page_chrono[0].id if (page_chrono and has_more) else None

        return ChatMessagesPage(
            messages=[ChatMessageResponse(
                id=m.id, role=m.role, content=m.content,
                tool_calls=m.tool_calls, token_usage=m.token_usage,
                attachments=m.attachments, created_at=m.created_at,
            ) for m in page_chrono],
            has_more=has_more,
            next_cursor=next_cursor,
        )
```

- [ ] **Step 5: Add the `ChatMessagesPage` import**

In `src/agenticops/web/app.py`, find the existing import of chat schemas (search for
`ChatSessionDetail` in the import statements near the top of the file) and add
`ChatMessagesPage` to that import list. Verify with:

```bash
cd /Users/malibo/MyDev/AgenticOps
grep -n "ChatSessionDetail" src/agenticops/web/app.py | head -1
```
Add `ChatMessagesPage` alongside `ChatSessionDetail` in that `from agenticops.web.schemas import (...)` block.

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_chat_messages_pagination.py -v`
Expected: PASS (all tests in `TestMessagesPagination` and `TestDetailMetadataOnly`).

- [ ] **Step 7: Run the existing chat API tests to ensure no regression**

Run: `python -m pytest tests/test_chat_api.py -v`
Expected: PASS (all existing tests still green).

- [ ] **Step 8: Commit**

```bash
cd /Users/malibo/MyDev/AgenticOps
git add src/agenticops/web/app.py tests/test_chat_messages_pagination.py
git commit --no-verify -m "feat(api): cursor-paginated /sessions/{id}/messages; metadata-only detail"
```

---

## Task 4: Frontend — add `@tanstack/react-virtual` + `ChatMessagesPage` type

**Files:**
- Modify: `src/agenticops/web/frontend/package.json`
- Modify: `src/agenticops/web/frontend/src/api/types.ts:581-583`

- [ ] **Step 1: Install the dependency**

```bash
cd /Users/malibo/MyDev/AgenticOps/src/agenticops/web/frontend
npm install @tanstack/react-virtual@^3
```
Expected: `package.json` dependencies now include `@tanstack/react-virtual`.

- [ ] **Step 2: Add the page type + deprecate detail messages**

In `src/agenticops/web/frontend/src/api/types.ts`, replace the `ChatSessionDetail`
interface (lines 581-583):

```typescript
export interface ChatSessionDetail extends ChatSession {
  messages: ChatMessage[];
}
```

with:

```typescript
export interface ChatSessionDetail extends ChatSession {
  /** @deprecated History now comes from GET /sessions/{id}/messages. Always []. */
  messages?: ChatMessage[];
}

export interface ChatMessagesPage {
  messages: ChatMessage[];
  has_more: boolean;
  next_cursor: number | null;
}
```

- [ ] **Step 3: Type-check**

Run: `cd /Users/malibo/MyDev/AgenticOps/src/agenticops/web/frontend && npx tsc --noEmit`
Expected: PASS — no errors. (`Chat.tsx` still reads `detail?.messages` which is now
optional; `?? []` already guards it, so it stays valid until Task 9.)

- [ ] **Step 4: Commit**

```bash
cd /Users/malibo/MyDev/AgenticOps
git add src/agenticops/web/frontend/package.json src/agenticops/web/frontend/package-lock.json src/agenticops/web/frontend/src/api/types.ts
git commit --no-verify -m "chore(web): add @tanstack/react-virtual; add ChatMessagesPage type"
```

---

## Task 5: Frontend — `chatStream` store singleton (TDD)

**Files:**
- Create: `src/agenticops/web/frontend/src/lib/chatStream.ts`
- Create: `src/agenticops/web/frontend/src/__tests__/chatStream.test.ts`

The store owns the SSE loop (lifted from `useChat.ts`) outside React, keyed by sessionId.

- [ ] **Step 1: Write the store**

Create `src/agenticops/web/frontend/src/lib/chatStream.ts`:

```typescript
import { getAuthToken } from "@/api/client";

export interface ToolCall {
  name: string;
  status: "running" | "done";
}

export interface StreamState {
  streaming: boolean;
  content: string;
  toolCalls: ToolCall[];
  tokenMetrics: { input: number; output: number } | null;
  error: string | null;
}

/** Callbacks the store fires on lifecycle events (wired to TanStack cache by hooks). */
export interface StreamCallbacks {
  /** Fired once per completed assistant turn with the final text + tools + tokens. */
  onDone?: (
    sessionId: string,
    payload: { content: string; toolCalls: ToolCall[]; tokenMetrics: { input: number; output: number } | null },
  ) => void;
  /** Fired when the backend auto-renames the session. */
  onRenamed?: (sessionId: string, name: string) => void;
}

const EMPTY: StreamState = {
  streaming: false,
  content: "",
  toolCalls: [],
  tokenMetrics: null,
  error: null,
};

const TOKEN_FLUSH_MS = 60;

class ChatStreamStore {
  private states = new Map<string, StreamState>();
  private controllers = new Map<string, AbortController>();
  private subscribers = new Map<string, Set<() => void>>();
  private activeSubscribers = new Set<() => void>();
  private callbacks: StreamCallbacks = {};

  setCallbacks(cb: StreamCallbacks) {
    this.callbacks = cb;
  }

  getSnapshot(sessionId: string | null): StreamState {
    if (!sessionId) return EMPTY;
    return this.states.get(sessionId) ?? EMPTY;
  }

  /** session ids currently streaming (for the flyout indicator). */
  activeSessions(): string[] {
    const out: string[] = [];
    this.states.forEach((s, id) => {
      if (s.streaming) out.push(id);
    });
    return out;
  }

  subscribe(sessionId: string, cb: () => void): () => void {
    let set = this.subscribers.get(sessionId);
    if (!set) {
      set = new Set();
      this.subscribers.set(sessionId, set);
    }
    set.add(cb);
    return () => set!.delete(cb);
  }

  subscribeActive(cb: () => void): () => void {
    this.activeSubscribers.add(cb);
    return () => this.activeSubscribers.delete(cb);
  }

  private set(sessionId: string, patch: Partial<StreamState>) {
    const prev = this.states.get(sessionId) ?? EMPTY;
    this.states.set(sessionId, { ...prev, ...patch });
    this.subscribers.get(sessionId)?.forEach((cb) => cb());
    this.activeSubscribers.forEach((cb) => cb());
  }

  isStreaming(sessionId: string): boolean {
    return this.states.get(sessionId)?.streaming ?? false;
  }

  cancel(sessionId: string) {
    this.controllers.get(sessionId)?.abort();
  }

  async send(sessionId: string, content: string, file?: File, detailLevel?: string) {
    if (this.isStreaming(sessionId)) return;

    this.set(sessionId, { streaming: true, content: "", toolCalls: [], tokenMetrics: null, error: null });

    const controller = new AbortController();
    this.controllers.set(sessionId, controller);

    // Completed-turn payload, handed to the cache layer in `finally` AFTER the
    // live slice is cleared (prevents a flash where both the streaming trailer
    // and the persisted row render at once).
    let donePayload: { content: string; toolCalls: ToolCall[]; tokenMetrics: { input: number; output: number } | null } | null = null;

    // Token coalescing buffer (avoids O(n^2) markdown re-parse downstream).
    let pendingText = "";
    let flushTimer: ReturnType<typeof setTimeout> | null = null;
    const flush = () => {
      if (pendingText) {
        const cur = this.states.get(sessionId) ?? EMPTY;
        this.set(sessionId, { content: cur.content + pendingText });
        pendingText = "";
      }
      flushTimer = null;
    };

    try {
      const authHeaders: Record<string, string> = {};
      const token = getAuthToken();
      if (token) authHeaders["Authorization"] = `Bearer ${token}`;

      let res: Response;
      if (file) {
        const formData = new FormData();
        formData.append("content", content);
        formData.append("file", file);
        if (detailLevel && detailLevel !== "medium") formData.append("detail_level", detailLevel);
        res = await fetch(`/api/chat/sessions/${sessionId}/messages`, {
          method: "POST", headers: authHeaders, body: formData, signal: controller.signal,
        });
      } else {
        const body: Record<string, string> = { content };
        if (detailLevel && detailLevel !== "medium") body.detail_level = detailLevel;
        res = await fetch(`/api/chat/sessions/${sessionId}/messages`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...authHeaders },
          body: JSON.stringify(body),
          signal: controller.signal,
        });
      }

      if (!res.ok) {
        const errBody = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(errBody.detail ?? res.statusText);
      }

      const reader = res.body?.getReader();
      if (!reader) throw new Error("No response body");

      const decoder = new TextDecoder();
      let buffer = "";
      let currentEvent = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (line.startsWith("event:")) {
            currentEvent = line.slice(6).trim();
            continue;
          }
          if (!line.startsWith("data:")) continue;
          const raw = line.slice(5).trim();
          if (!raw) continue;

          try {
            const data = JSON.parse(raw);
            switch (currentEvent) {
              case "text":
                if (data.token) {
                  pendingText += data.token;
                  if (!flushTimer) flushTimer = setTimeout(flush, TOKEN_FLUSH_MS);
                }
                break;
              case "tool_start":
                if (data.name) {
                  const cur = this.states.get(sessionId) ?? EMPTY;
                  this.set(sessionId, { toolCalls: [...cur.toolCalls, { name: data.name, status: "running" }] });
                }
                break;
              case "tool_end":
                if (data.name) {
                  const cur = this.states.get(sessionId) ?? EMPTY;
                  this.set(sessionId, {
                    toolCalls: cur.toolCalls.map((t) =>
                      t.name === data.name ? { ...t, status: "done" as const } : t),
                  });
                }
                break;
              case "session_renamed":
                if (data.name) this.callbacks.onRenamed?.(sessionId, data.name);
                break;
              case "done":
                this.set(sessionId, {
                  tokenMetrics: { input: data.input_tokens ?? 0, output: data.output_tokens ?? 0 },
                });
                break;
              case "error":
                this.set(sessionId, { error: data.message ?? "Unknown error" });
                break;
            }
          } catch {
            // ignore malformed JSON
          }
        }
      }

      if (flushTimer) clearTimeout(flushTimer);
      flush();

      // Capture the completed turn; fired in `finally` after the slice clears.
      const final = this.states.get(sessionId) ?? EMPTY;
      if (!final.error) {
        donePayload = {
          content: final.content,
          toolCalls: final.toolCalls,
          tokenMetrics: final.tokenMetrics,
        };
      }
    } catch (err: unknown) {
      if (err instanceof Error && err.name !== "AbortError") {
        this.set(sessionId, { error: err.message });
      }
    } finally {
      if (flushTimer) clearTimeout(flushTimer);
      this.controllers.delete(sessionId);
      // Clear the live slice FIRST so the streaming trailer disappears, THEN
      // hand the completed turn to the cache layer (no double-render flash).
      this.set(sessionId, { streaming: false, content: "", toolCalls: [], tokenMetrics: null });
      if (donePayload) this.callbacks.onDone?.(sessionId, donePayload);
    }
  }
}

export const chatStream = new ChatStreamStore();
```

- [ ] **Step 2: Write the failing test**

Create `src/agenticops/web/frontend/src/__tests__/chatStream.test.ts`:

```typescript
/**
 * chatStream store: concurrent-session isolation + lifecycle.
 *
 * We stub global.fetch to return a ReadableStream of SSE bytes so the store's
 * parse loop runs without a server.
 */
import { describe, it, expect, beforeEach, vi } from "vitest";
import { chatStream } from "@/lib/chatStream";

// jsdom/node: provide a minimal localStorage so getAuthToken() works.
beforeEach(() => {
  (globalThis as any).localStorage = {
    store: {} as Record<string, string>,
    getItem(k: string) { return this.store[k] ?? null; },
    setItem(k: string, v: string) { this.store[k] = v; },
    removeItem(k: string) { delete this.store[k]; },
  };
});

/** Build a Response whose body streams the given SSE lines. */
function sseResponse(lines: string[]): Response {
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const l of lines) controller.enqueue(encoder.encode(l));
      controller.close();
    },
  });
  return new Response(stream, { status: 200, headers: { "Content-Type": "text/event-stream" } });
}

const SSE_HELLO = [
  'event: text\ndata: {"token":"Hello"}\n\n',
  'event: text\ndata: {"token":" world"}\n\n',
  'event: done\ndata: {"input_tokens":3,"output_tokens":2}\n\n',
];

describe("chatStream", () => {
  it("streams tokens and fires onDone with final content", async () => {
    const done: any[] = [];
    chatStream.setCallbacks({ onDone: (sid, p) => done.push({ sid, ...p }) });
    vi.stubGlobal("fetch", vi.fn(async () => sseResponse(SSE_HELLO)));

    await chatStream.send("sess-A", "hi");

    expect(done).toHaveLength(1);
    expect(done[0].sid).toBe("sess-A");
    expect(done[0].content).toBe("Hello world");
    expect(done[0].tokenMetrics).toEqual({ input: 3, output: 2 });
    // live slice cleared after completion
    expect(chatStream.getSnapshot("sess-A").streaming).toBe(false);
    expect(chatStream.getSnapshot("sess-A").content).toBe("");
  });

  it("keeps two sessions isolated when streamed concurrently", async () => {
    const done: Record<string, string> = {};
    chatStream.setCallbacks({ onDone: (sid, p) => { done[sid] = p.content; } });

    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (String(url).includes("sess-X")) {
        return sseResponse(['event: text\ndata: {"token":"X1"}\n\n',
                            'event: done\ndata: {"input_tokens":0,"output_tokens":0}\n\n']);
      }
      return sseResponse(['event: text\ndata: {"token":"Y1"}\n\n',
                          'event: done\ndata: {"input_tokens":0,"output_tokens":0}\n\n']);
    }));

    await Promise.all([chatStream.send("sess-X", "hi"), chatStream.send("sess-Y", "yo")]);

    expect(done["sess-X"]).toBe("X1");
    expect(done["sess-Y"]).toBe("Y1");
  });

  it("records an error on the session slice and does not fire onDone", async () => {
    const done: any[] = [];
    chatStream.setCallbacks({ onDone: () => done.push(1) });
    vi.stubGlobal("fetch", vi.fn(async () =>
      sseResponse(['event: error\ndata: {"message":"boom"}\n\n'])));

    await chatStream.send("sess-E", "hi");

    expect(chatStream.getSnapshot("sess-E").error).toBe("boom");
    expect(done).toHaveLength(0);
  });

  it("reports active sessions while streaming", async () => {
    let activeDuringStream: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async () => {
      // capture active set synchronously after streaming flips true
      activeDuringStream = chatStream.activeSessions();
      return sseResponse(['event: done\ndata: {"input_tokens":0,"output_tokens":0}\n\n']);
    }));
    await chatStream.send("sess-ACT", "hi");
    expect(activeDuringStream).toContain("sess-ACT");
    expect(chatStream.activeSessions()).not.toContain("sess-ACT"); // cleared after done
  });
});
```

- [ ] **Step 3: Run tests to verify they pass**

Run: `cd /Users/malibo/MyDev/AgenticOps/src/agenticops/web/frontend && npx vitest --run src/__tests__/chatStream.test.ts`
Expected: PASS (4 tests). If `Response`/`ReadableStream`/`TextEncoder` are undefined under
the `node` test env, they are provided by Node ≥18 globals — confirm Node 18+ with
`node --version`. (No config change needed; these are global in modern Node.)

- [ ] **Step 4: Type-check**

Run: `cd /Users/malibo/MyDev/AgenticOps/src/agenticops/web/frontend && npx tsc --noEmit`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/malibo/MyDev/AgenticOps
git add src/agenticops/web/frontend/src/lib/chatStream.ts src/agenticops/web/frontend/src/__tests__/chatStream.test.ts
git commit --no-verify -m "feat(web): chatStream store — out-of-tree SSE loop keyed by session_id"
```

---

## Task 6: Frontend — `markdownCache` memo

**Files:**
- Create: `src/agenticops/web/frontend/src/lib/markdownCache.ts`

- [ ] **Step 1: Write the memo**

Create `src/agenticops/web/frontend/src/lib/markdownCache.ts`:

```typescript
import { renderMarkdown } from "@/lib/renderMarkdown";

/**
 * Persisted chat messages are immutable, so their rendered HTML can be cached
 * by message id forever. This keeps virtualized rows cheap to re-mount on
 * scroll-back (no markdown re-parse). Streaming content is NOT cached here.
 */
const cache = new Map<number, string>();

export function renderMessageMarkdown(id: number, content: string): string {
  const hit = cache.get(id);
  if (hit !== undefined) return hit;
  const html = renderMarkdown(content);
  cache.set(id, html);
  return html;
}
```

- [ ] **Step 2: Type-check**

Run: `cd /Users/malibo/MyDev/AgenticOps/src/agenticops/web/frontend && npx tsc --noEmit`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
cd /Users/malibo/MyDev/AgenticOps
git add src/agenticops/web/frontend/src/lib/markdownCache.ts
git commit --no-verify -m "feat(web): markdownCache memo for immutable chat messages"
```

---

## Task 7: Frontend — `useSessionStream` + `useChatMessages` hooks

**Files:**
- Create: `src/agenticops/web/frontend/src/hooks/useSessionStream.ts`
- Create: `src/agenticops/web/frontend/src/hooks/useChatMessages.ts`

- [ ] **Step 1: Write `useChatMessages` (paginated history)**

Create `src/agenticops/web/frontend/src/hooks/useChatMessages.ts`:

```typescript
import { useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { ChatMessage, ChatMessagesPage } from "@/api/types";

const PAGE_SIZE = 50;

/**
 * Cursor-paginated chat history. Page 0 is the newest PAGE_SIZE messages;
 * fetchNextPage() loads the immediately-older page via the `before` cursor.
 *
 * Pages arrive newest-window-first, each ordered oldest→newest internally.
 * `messages` flattens them into a single chronological array.
 */
export function useChatMessages(sessionId: string | null) {
  const query = useInfiniteQuery({
    queryKey: ["chat-messages", sessionId],
    enabled: !!sessionId,
    initialPageParam: null as number | null,
    queryFn: ({ pageParam }) => {
      const qs = new URLSearchParams({ limit: String(PAGE_SIZE) });
      if (pageParam != null) qs.set("before", String(pageParam));
      return apiFetch<ChatMessagesPage>(`/chat/sessions/${sessionId}/messages?${qs.toString()}`);
    },
    getNextPageParam: (lastPage) => (lastPage.has_more ? lastPage.next_cursor : undefined),
    staleTime: 30_000,
  });

  // pages[0] = newest window, pages[1] = older, ... → reverse page order, keep
  // each page's internal chronological order, to get a single oldest→newest list.
  const messages: ChatMessage[] = (query.data?.pages ?? [])
    .slice()
    .reverse()
    .flatMap((p) => p.messages);

  return {
    messages,
    fetchOlder: query.fetchNextPage,
    hasOlder: query.hasNextPage,
    isFetchingOlder: query.isFetchingNextPage,
    isLoading: query.isLoading,
  };
}

/**
 * Optimistic temp ids for messages not yet persisted server-side. Negative +
 * monotonically decreasing so they (a) never collide with real positive ids
 * and (b) never collide with each other (markdown memo + React keys are id-based).
 */
let _tempId = -1;
export function nextTempId(): number {
  return _tempId--;
}

/**
 * Role-agnostic optimistic append: add a message to the newest page so it shows
 * without a refetch. Used for both the user message (on send) and the finished
 * assistant turn (on done). If the cache has no pages yet (e.g. a freshly
 * created session whose history query hasn't loaded), it seeds an initial page.
 */
export function appendMessageToCache(
  qc: ReturnType<typeof useQueryClient>,
  sessionId: string,
  msg: ChatMessage,
) {
  qc.setQueryData<{ pages: ChatMessagesPage[]; pageParams: unknown[] }>(
    ["chat-messages", sessionId],
    (old) => {
      if (!old || old.pages.length === 0) {
        return {
          pages: [{ messages: [msg], has_more: false, next_cursor: null }],
          pageParams: [null],
        };
      }
      const pages = old.pages.slice();
      // pages[0] is the newest window; append to it (it flattens to the bottom).
      pages[0] = { ...pages[0], messages: [...pages[0].messages, msg] };
      return { ...old, pages };
    },
  );
}
```

- [ ] **Step 2: Write `useSessionStream` (store adapter)**

Create `src/agenticops/web/frontend/src/hooks/useSessionStream.ts`:

```typescript
import { useSyncExternalStore, useCallback, useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { chatStream } from "@/lib/chatStream";
import { appendMessageToCache, nextTempId } from "@/hooks/useChatMessages";
import type { ChatSession, ChatMessage } from "@/api/types";

/**
 * React adapter over the chatStream store for a single session. Returns the
 * same shape the old useChat() exposed, but the underlying SSE loop lives in
 * the store, so it survives navigation and runs concurrently per session.
 */
export function useSessionStream(sessionId: string | null) {
  const qc = useQueryClient();

  // Wire store lifecycle callbacks to the TanStack cache ONCE per mount.
  // (Module-level store keeps the last callbacks; re-registering with a fresh
  // qc each render is fine because qc is stable.)
  useEffect(() => {
    chatStream.setCallbacks({
      onDone: (sid, payload) => {
        const assistantMsg: ChatMessage = {
          id: nextTempId(), // optimistic temp id (negative, unique); reconciled below
          role: "assistant",
          content: payload.content,
          tool_calls: payload.toolCalls,
          token_usage: payload.tokenMetrics ?? undefined,
          created_at: new Date().toISOString(),
        };
        appendMessageToCache(qc, sid, assistantMsg);
        // Refresh the session list (name/last_activity/order may change).
        qc.invalidateQueries({ queryKey: ["chat-sessions"] });
        // Reconcile optimistic temp ids -> real server ids by refetching the
        // newest page in the background (keeps markdown-memo/React keys correct).
        qc.invalidateQueries({ queryKey: ["chat-messages", sid] });
      },
      onRenamed: (sid, name) => {
        qc.setQueryData<ChatSession[]>(["chat-sessions"], (old) =>
          old?.map((s) => (s.session_id === sid ? { ...s, name } : s)));
      },
    });
  }, [qc]);

  const subscribe = useCallback(
    (cb: () => void) => (sessionId ? chatStream.subscribe(sessionId, cb) : () => {}),
    [sessionId],
  );
  const getSnapshot = useCallback(() => chatStream.getSnapshot(sessionId), [sessionId]);
  const state = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);

  const send = useCallback(
    (content: string, file?: File, detailLevel?: string) => {
      if (!sessionId) return;
      // Optimistically append the user's message so it shows immediately.
      const userMsg: ChatMessage = {
        id: nextTempId(),
        role: "user",
        content,
        attachments: file ? [{ filename: file.name, size: file.size }] : undefined,
        created_at: new Date().toISOString(),
      };
      appendMessageToCache(qc, sessionId, userMsg);
      void chatStream.send(sessionId, content, file, detailLevel);
    },
    [sessionId, qc],
  );

  const cancel = useCallback(() => {
    if (sessionId) chatStream.cancel(sessionId);
  }, [sessionId]);

  return {
    streaming: state.streaming,
    streamingContent: state.content,
    toolCalls: state.toolCalls,
    tokenMetrics: state.tokenMetrics,
    error: state.error,
    sendMessage: send,
    cancel,
  };
}

/** Subscribe to the set of session ids currently streaming (for the flyout dot). */
export function useActiveStreamingSessions(): string[] {
  const subscribe = useCallback((cb: () => void) => chatStream.subscribeActive(cb), []);
  // getSnapshot must be referentially stable when nothing changed; the store
  // returns a fresh array each call, so memoize via a cached join key.
  const lastRef = useRef<{ key: string; val: string[] }>({ key: "", val: [] });
  const getSnapshot = useCallback(() => {
    const arr = chatStream.activeSessions();
    const key = arr.slice().sort().join(",");
    if (key !== lastRef.current.key) lastRef.current = { key, val: arr };
    return lastRef.current.val;
  }, []);
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}
```

NOTE: `appendMessageToCache` is role-agnostic — it appends any `ChatMessage` to the newest
page and seeds an initial page if the cache is empty, so it is correct for the user
message, the assistant turn, and the welcome-flow first message alike.

- [ ] **Step 3: Type-check**

Run: `cd /Users/malibo/MyDev/AgenticOps/src/agenticops/web/frontend && npx tsc --noEmit`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
cd /Users/malibo/MyDev/AgenticOps
git add src/agenticops/web/frontend/src/hooks/useChatMessages.ts src/agenticops/web/frontend/src/hooks/useSessionStream.ts
git commit --no-verify -m "feat(web): useSessionStream + useChatMessages hooks (store + paginated history)"
```

---

## Task 8: Frontend — rewrite `MessageList` with virtualization + markdown memo

**Files:**
- Modify (rewrite): `src/agenticops/web/frontend/src/components/chat/MessageList.tsx`

- [ ] **Step 1: Rewrite MessageList**

Replace the ENTIRE contents of `src/agenticops/web/frontend/src/components/chat/MessageList.tsx` with:

```typescript
import { useEffect, useRef, useMemo, useLayoutEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useVirtualizer } from "@tanstack/react-virtual";
import { ToolCallChip } from "./ToolCallChip";
import { TokenMetrics } from "./TokenMetrics";
import type { ChatMessage } from "@/api/types";
import { renderMarkdown } from "@/lib/renderMarkdown";
import { renderMessageMarkdown } from "@/lib/markdownCache";

interface Props {
  messages: ChatMessage[];
  streamingContent?: string;
  streamingToolCalls?: Array<{ name: string; status: string }>;
  streamingTokenMetrics?: { input: number; output: number } | null;
  streaming?: boolean;
  hasOlder?: boolean;
  isFetchingOlder?: boolean;
  onLoadOlder?: () => void;
}

export function MessageList({
  messages,
  streamingContent,
  streamingToolCalls,
  streamingTokenMetrics,
  streaming,
  hasOlder,
  isFetchingOlder,
  onLoadOlder,
}: Props) {
  const navigate = useNavigate();
  const parentRef = useRef<HTMLDivElement>(null);

  const handleRefClick = (e: React.MouseEvent) => {
    const anchor = (e.target as HTMLElement).closest("a.md-ref") as HTMLAnchorElement | null;
    if (anchor) {
      e.preventDefault();
      navigate(new URL(anchor.href).pathname);
    }
  };

  // One virtual row per message; the streaming bubble is rendered as a sticky
  // trailer below the virtualizer (always at the bottom), not virtualized.
  const virtualizer = useVirtualizer({
    count: messages.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 80,
    overscan: 8,
    getItemKey: (i) => messages[i].id,
  });

  // Auto-scroll to bottom on new messages / streaming tokens (sticky-bottom).
  useEffect(() => {
    const el = parentRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [messages.length, streamingContent, streaming]);

  // Reverse-infinite-scroll: when scrolled near the top, load the older page.
  const onScroll = () => {
    const el = parentRef.current;
    if (!el || !hasOlder || isFetchingOlder) return;
    if (el.scrollTop < 120) onLoadOlder?.();
  };

  const streamingHtml = useMemo(
    () => (streamingContent ? renderMarkdown(streamingContent) : ""),
    [streamingContent],
  );

  if (messages.length === 0 && !streamingContent && !streaming) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="text-center text-muted-foreground">
          <p className="text-lg font-medium">Start a conversation</p>
          <p className="text-sm mt-1">
            Ask about your AWS resources, health issues, or request a report.
          </p>
        </div>
      </div>
    );
  }

  const items = virtualizer.getVirtualItems();

  return (
    <div
      ref={parentRef}
      onScroll={onScroll}
      onClick={handleRefClick}
      className="flex-1 overflow-y-auto px-6 py-4"
    >
      {isFetchingOlder && (
        <div className="text-center text-xs text-muted-foreground py-2">Loading older messages…</div>
      )}

      {/* Virtualized message rows */}
      <div style={{ height: `${virtualizer.getTotalSize()}px`, position: "relative", width: "100%" }}>
        {items.map((vi) => {
          const msg = messages[vi.index];
          return (
            <div
              key={vi.key}
              data-index={vi.index}
              ref={virtualizer.measureElement}
              style={{ position: "absolute", top: 0, left: 0, width: "100%", transform: `translateY(${vi.start}px)` }}
              className="pb-5"
            >
              <MessageRow msg={msg} />
            </div>
          );
        })}
      </div>

      {/* Thinking indicator — streaming started but no content yet */}
      {streaming && !streamingContent && (!streamingToolCalls || streamingToolCalls.length === 0) && (
        <div className="flex gap-3 animate-[fadeIn_0.2s_ease-out] pt-2">
          <div className="flex-shrink-0 w-7 h-7 rounded-full bg-primary-600 flex items-center justify-center text-white text-xs font-semibold">AI</div>
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <span className="flex gap-1">
              <span className="w-1.5 h-1.5 bg-primary-400 rounded-full animate-bounce [animation-delay:0ms]" />
              <span className="w-1.5 h-1.5 bg-primary-400 rounded-full animate-bounce [animation-delay:150ms]" />
              <span className="w-1.5 h-1.5 bg-primary-400 rounded-full animate-bounce [animation-delay:300ms]" />
            </span>
            Thinking...
          </div>
        </div>
      )}

      {/* Streaming assistant message (sticky trailer) */}
      {streaming && (streamingContent || (streamingToolCalls && streamingToolCalls.length > 0)) && (
        <div className="flex gap-3 animate-[fadeIn_0.2s_ease-out] pt-2">
          <div className="flex-shrink-0 w-7 h-7 rounded-full bg-primary-600 flex items-center justify-center text-white text-xs font-semibold">AI</div>
          <div className="flex-1 max-w-3xl space-y-2">
            {streamingToolCalls && streamingToolCalls.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mb-1">
                {streamingToolCalls.map((t, i) => (<ToolCallChip key={i} name={t.name} status={t.status} />))}
              </div>
            )}
            {streamingContent && (
              <div className="text-sm text-foreground leading-relaxed report-content max-w-none">
                <span dangerouslySetInnerHTML={{ __html: streamingHtml }} />
                <span className="inline-block w-1.5 h-4 bg-primary-500 animate-pulse ml-0.5 align-text-bottom" />
              </div>
            )}
            {streamingTokenMetrics && (
              <TokenMetrics input={streamingTokenMetrics.input} output={streamingTokenMetrics.output} />
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function MessageRow({ msg }: { msg: ChatMessage }) {
  return (
    <div className={msg.role === "user" ? "flex justify-end" : "flex gap-3"}>
      {msg.role === "assistant" && (
        <div className="flex-shrink-0 w-7 h-7 rounded-full bg-primary-600 flex items-center justify-center text-white text-xs font-semibold">AI</div>
      )}
      <div className={msg.role === "user"
        ? "bg-primary-50 border border-primary-100 rounded-xl px-4 py-2.5 max-w-2xl"
        : "flex-1 max-w-3xl space-y-2"}>
        {msg.role === "user" && msg.attachments && msg.attachments.length > 0 && (
          <div className="flex flex-wrap gap-1 mb-1">
            {msg.attachments.map((att, i) => (
              <span key={i} className="inline-flex items-center gap-1 text-xs bg-primary-100 text-primary-700 px-2 py-0.5 rounded-full">
                <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
                </svg>
                {att.filename}
              </span>
            ))}
          </div>
        )}
        {msg.role === "assistant" && msg.tool_calls && msg.tool_calls.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mb-1">
            {msg.tool_calls.map((t, i) => (<ToolCallChip key={i} name={t.name} status={t.status} />))}
          </div>
        )}
        <div
          className="text-sm text-foreground leading-relaxed report-content max-w-none"
          dangerouslySetInnerHTML={{ __html: renderMessageMarkdown(msg.id, msg.content) }}
        />
        {msg.role === "assistant" && msg.token_usage && (
          <TokenMetrics input={msg.token_usage.input} output={msg.token_usage.output} />
        )}
      </div>
    </div>
  );
}
```

NOTE: `useLayoutEffect` is imported but used only if needed for measurement; if `tsc`
flags it as unused, remove it from the import. (Kept available for the measurement path.)

- [ ] **Step 2: Type-check (will surface the unused import if any)**

Run: `cd /Users/malibo/MyDev/AgenticOps/src/agenticops/web/frontend && npx tsc --noEmit`
Expected: PASS. If it errors `'useLayoutEffect' is declared but its value is never read`,
remove `useLayoutEffect` from the import on line 1, then re-run — expected PASS.

- [ ] **Step 3: Commit**

```bash
cd /Users/malibo/MyDev/AgenticOps
git add src/agenticops/web/frontend/src/components/chat/MessageList.tsx
git commit --no-verify -m "feat(web): virtualize MessageList + markdown memo + older-page loading"
```

---

## Task 9: Frontend — migrate `Chat.tsx` to store + paginated messages; delete `useChat`

**Files:**
- Modify: `src/agenticops/web/frontend/src/pages/Chat.tsx`
- Delete: `src/agenticops/web/frontend/src/hooks/useChat.ts`

- [ ] **Step 1: Update imports in Chat.tsx**

In `src/agenticops/web/frontend/src/pages/Chat.tsx`, replace:

```typescript
import { useChat } from "@/hooks/useChat";
```

with:

```typescript
import { useSessionStream } from "@/hooks/useSessionStream";
import { useChatMessages } from "@/hooks/useChatMessages";
```

- [ ] **Step 2: Swap the hook usage + message source**

In `Chat.tsx`, replace these two lines (currently 87-89):

```typescript
  const { data: detail } = useChatSession(selectedId);
  const { streaming, streamingContent, toolCalls, tokenMetrics, error, sendMessage, cancel } =
    useChat(selectedId);
```

with:

```typescript
  useChatSession(selectedId); // metadata only — primes session existence/validation
  const { messages, fetchOlder, hasOlder, isFetchingOlder } = useChatMessages(selectedId);
  const { streaming, streamingContent, toolCalls, tokenMetrics, error, sendMessage, cancel } =
    useSessionStream(selectedId);
```

- [ ] **Step 3: Update the `<MessageList>` props**

In `Chat.tsx`, replace the `<MessageList>` block (currently lines 271-277):

```typescript
            <MessageList
              messages={detail?.messages ?? []}
              streamingContent={streamingContent}
              streamingToolCalls={toolCalls}
              streamingTokenMetrics={tokenMetrics}
              streaming={streaming}
            />
```

with:

```typescript
            <MessageList
              messages={messages}
              streamingContent={streamingContent}
              streamingToolCalls={toolCalls}
              streamingTokenMetrics={tokenMetrics}
              streaming={streaming}
              hasOlder={hasOlder}
              isFetchingOlder={isFetchingOlder}
              onLoadOlder={fetchOlder}
            />
```

- [ ] **Step 4: Delete the obsolete useChat hook**

```bash
cd /Users/malibo/MyDev/AgenticOps
git rm src/agenticops/web/frontend/src/hooks/useChat.ts
```

- [ ] **Step 5: Verify nothing else imports useChat**

Run:
```bash
cd /Users/malibo/MyDev/AgenticOps
grep -rn "hooks/useChat\"" src/agenticops/web/frontend/src/ || echo "no references — OK"
```
Expected: `no references — OK`.

- [ ] **Step 6: Type-check**

Run: `cd /Users/malibo/MyDev/AgenticOps/src/agenticops/web/frontend && npx tsc --noEmit`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
cd /Users/malibo/MyDev/AgenticOps
git add src/agenticops/web/frontend/src/pages/Chat.tsx
git commit --no-verify -m "feat(web): Chat page uses chatStream + paginated messages; remove useChat"
```

---

## Task 10: Frontend — first-message flow via store + live streaming indicator in flyout

**Files:**
- Modify: `src/agenticops/web/frontend/src/hooks/useLazySessionCreate.ts`
- Modify: `src/agenticops/web/frontend/src/pages/Chat.tsx` (welcome send path)
- Modify: `src/agenticops/web/frontend/src/components/chat/SessionFlyout.tsx`

- [ ] **Step 1: Simplify `useLazySessionCreate` (drop dead pendingMessage; send via store)**

Replace the ENTIRE contents of `src/agenticops/web/frontend/src/hooks/useLazySessionCreate.ts` with:

```typescript
import { useState, useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import { chatStream } from "@/lib/chatStream";
import { appendMessageToCache, nextTempId } from "@/hooks/useChatMessages";
import type { ChatSession, ChatMessage } from "@/api/types";

/**
 * Lazy (deferred) session creation for the welcome flow:
 *   1. Create a ChatSession
 *   2. Seed the user's first message into the messages cache (shows immediately)
 *   3. Start streaming the first message via the chatStream store (survives nav)
 *   4. Navigate to the new session URL
 */
export function useLazySessionCreate() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [creating, setCreating] = useState(false);
  const creatingRef = useRef(false);

  const sendFirstMessage = useCallback(
    async (content: string, file?: File, detailLevel?: string) => {
      if (creatingRef.current) return;
      creatingRef.current = true;
      setCreating(true);
      try {
        const session = await apiFetch<ChatSession>("/chat/sessions", {
          method: "POST",
          body: JSON.stringify({ name: undefined }),
        });
        localStorage.setItem("aiops-last-session-id", session.session_id);
        qc.invalidateQueries({ queryKey: ["chat-sessions"] });
        // Seed the user's message into the cache so it shows the moment the
        // Chat page mounts (the history query starts empty for a new session).
        const userMsg: ChatMessage = {
          id: nextTempId(),
          role: "user",
          content,
          attachments: file ? [{ filename: file.name, size: file.size }] : undefined,
          created_at: new Date().toISOString(),
        };
        appendMessageToCache(qc, session.session_id, userMsg);
        // Kick off the stream in the store, then navigate. The Chat page binds
        // to the in-flight stream for this session id on mount.
        void chatStream.send(session.session_id, content, file, detailLevel);
        navigate(`/app/chat/${session.session_id}`, { replace: true });
      } finally {
        creatingRef.current = false;
        setCreating(false);
      }
    },
    [navigate, qc],
  );

  return { sendFirstMessage, creating };
}
```

- [ ] **Step 2: Update Chat.tsx welcome send to pass detailLevel**

In `src/agenticops/web/frontend/src/pages/Chat.tsx`, the welcome handler currently is:

```typescript
  const handleWelcomeSend = (content: string, file?: File) => {
    sendFirstMessage(content, file);
  };
```

Replace it with (thread the detail level through, matching the normal send path):

```typescript
  const handleWelcomeSend = (content: string, file?: File) => {
    sendFirstMessage(content, file, detailLevel);
  };
```

- [ ] **Step 3: Type-check (welcome flow + flyout still compile)**

Run: `cd /Users/malibo/MyDev/AgenticOps/src/agenticops/web/frontend && npx tsc --noEmit`
Expected: PASS.

- [ ] **Step 4: Add live streaming indicator to SessionFlyout**

In `src/agenticops/web/frontend/src/components/chat/SessionFlyout.tsx`:

(a) Add the import near the top (with the other hook imports):

```typescript
import { useActiveStreamingSessions } from "@/hooks/useSessionStream";
```

(b) Inside the `SessionFlyout` component body, near the other hook calls (e.g. just after
the `filtered` useMemo), add:

```typescript
  const activeStreaming = useActiveStreamingSessions();
```

(c) In the session row, render a pulsing dot when that session is streaming. Find the
relative-time line (around line 228):

```typescript
                  <p className="text-[10px] text-muted-foreground mt-0.5">
                    {relativeTime(s.last_activity_at)}
                  </p>
```

Replace it with:

```typescript
                  <p className="text-[10px] text-muted-foreground mt-0.5 flex items-center gap-1">
                    {activeStreaming.includes(s.session_id) && (
                      <span
                        title="Streaming…"
                        className="inline-block w-1.5 h-1.5 rounded-full bg-primary-500 animate-pulse"
                      />
                    )}
                    {relativeTime(s.last_activity_at)}
                  </p>
```

- [ ] **Step 5: Type-check**

Run: `cd /Users/malibo/MyDev/AgenticOps/src/agenticops/web/frontend && npx tsc --noEmit`
Expected: PASS.

- [ ] **Step 6: Full frontend build + run the store test once more**

Run:
```bash
cd /Users/malibo/MyDev/AgenticOps/src/agenticops/web/frontend
npx tsc --noEmit && npm run build && npm run test
```
Expected: tsc clean, build succeeds, vitest all green (including `chatStream.test.ts` and
the existing `sessionSort.prop.test.ts`).

- [ ] **Step 7: Commit**

```bash
cd /Users/malibo/MyDev/AgenticOps
git add src/agenticops/web/frontend/src/hooks/useLazySessionCreate.ts src/agenticops/web/frontend/src/pages/Chat.tsx src/agenticops/web/frontend/src/components/chat/SessionFlyout.tsx
git commit --no-verify -m "feat(web): first-message via store; live streaming dot in session flyout"
```

---

## Task 11: Full verification + docs update

**Files:**
- Modify: `docs/WORKFLOW.md` (chat/session section)
- Modify: `CLAUDE.md` (web module note, if warranted)

- [ ] **Step 1: Backend full chat test sweep**

Run:
```bash
cd /Users/malibo/MyDev/AgenticOps
python -m pytest tests/test_chat_api.py tests/test_chat_messages_pagination.py tests/test_chat_session_rename.py -v
```
Expected: all PASS.

- [ ] **Step 2: Backend compile sweep**

Run:
```bash
cd /Users/malibo/MyDev/AgenticOps
python3 -m py_compile src/agenticops/web/app.py src/agenticops/web/schemas.py src/agenticops/models.py
echo "compile OK exit=$?"
```
Expected: `compile OK exit=0`.

- [ ] **Step 3: Frontend full check**

Run:
```bash
cd /Users/malibo/MyDev/AgenticOps/src/agenticops/web/frontend
npx tsc --noEmit && npm run build && npm run test
```
Expected: clean tsc, successful build, all vitest green.

- [ ] **Step 4: Manual smoke (record results)**

Start the API + frontend and verify by hand (record pass/fail for each):
```bash
cd /Users/malibo/MyDev/AgenticOps
uvicorn agenticops.web.app:app --reload --port 8000
# (separate terminal) cd src/agenticops/web/frontend && npm run dev
```
Checklist:
- Open a large existing session → paints immediately (no multi-second wait).
- Scroll to top → older page loads ("Loading older messages…" shows, then prepends).
- Send in session A, switch to session B, send there → both show a streaming dot in the
  flyout and both continue generating; switching back to A shows A's live progress.
- Session A's input is enabled while B streams (per-session disable, not global).
- After a turn completes, the assistant message persists and shows without a flash/refetch.

- [ ] **Step 5: Update `docs/WORKFLOW.md`**

Add/refresh a short subsection under the chat/web section documenting:
- Concurrent sessions: streams run in a module-level `chatStream` store keyed by
  `session_id`; navigating away does not stop generation; multiple sessions stream at once.
- Fast open: history is cursor-paginated (`GET /sessions/{id}/messages?limit=&before=`,
  newest page first, `next_cursor` for older) and virtualized; the detail endpoint is
  metadata-only.
- Caching: TanStack page cache + optimistic append on done; Bedrock prompt cache preserved;
  immutable-message markdown memo.
- Reload caveat: an in-flight stream is not resumed after a hard page reload; the persisted
  partial reply appears in history.

- [ ] **Step 6: Update `CLAUDE.md` web module note (one line)**

In the `web/` row of the Key Modules table (or the architecture notes), append a brief note:
`per-session concurrent SSE via frontend chatStream store; cursor-paginated + virtualized history`.

- [ ] **Step 7: Commit docs**

```bash
cd /Users/malibo/MyDev/AgenticOps
git add docs/WORKFLOW.md CLAUDE.md
git commit --no-verify -m "docs: document concurrent chat sessions + paginated/virtualized history"
```

---

## Self-Review Notes (author)

- **Spec coverage:** store-based concurrency (T5,7,9,10), cursor pagination endpoint (T3),
  metadata-only detail (T3), `(session_id,id)` index (T1), virtualization (T8), markdown
  memo (T6,T8), TanStack page cache + optimistic append (T7), per-session input disable
  (T9), live streaming indicator (T10), welcome-flow cleanup / dead `pendingMessage`
  removal (T10), docs (T11). All spec sections map to a task.
- **No server-side cache / ETag:** intentionally absent per spec (YAGNI).
- **Type consistency:** `ChatMessagesPage` (`messages/has_more/next_cursor`) identical in
  `schemas.py` (T2) and `types.ts` (T4); endpoint returns it (T3); `useChatMessages`
  consumes it (T7). `chatStream` exposes `send/cancel/getSnapshot/subscribe/
  subscribeActive/activeSessions/setCallbacks` (T5) — all used by the hooks (T7) and
  flyout (T10) with matching names. `useSessionStream` returns the same surface the old
  `useChat` did (`streaming/streamingContent/toolCalls/tokenMetrics/error/sendMessage/
  cancel`) so `Chat.tsx`/`ChatInput` wiring is unchanged (T9).
- **Reload caveat** is explicit and matches the chosen tradeoff (not a gap).
```
