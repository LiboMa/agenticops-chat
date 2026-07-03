# Chat Composer 2.0 (Per-Session Model Switch + Detail-Level Removal) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Users switch the main-agent model per chat session from the composer (persisted, "Auto" follows global config); the concise/medium/detailed detail-level knob is removed end-to-end (prompts fixed to today's medium template).

**Architecture:** Additive nullable `chat_sessions.model_id` column; reuse `PATCH /api/chat/sessions/{id}` with a `""`-sentinel for Auto; `session_manager` resolves the override at agent build and evicts only the changed session via existing `remove()`; a new in-flight-stream registry backs a 409 guard. Detail-level removal collapses `OUTPUT_RULES` to a single medium constant while keeping `get_output_rules(agent_type)`'s signature so all agent call sites stay untouched.

**Tech Stack:** FastAPI + SQLAlchemy + SQLite ALTER-TABLE migrations (existing `models.py` pattern), Strands BedrockModel, React 18 + TanStack Query + Radix Popover (`@radix-ui/react-popover@^1.1.15` already installed), pytest, typer CLI.

**Spec:** `docs/superpowers/specs/2026-07-03-chat-composer-model-switch-design.md`

## Global Constraints

- Branch: create `MVP-2.0.1` from `MVP-2.0.0-release` before Task 1; all commits on it.
- `model_id: ""` (empty string) in PATCH = Auto (stored NULL). Field omitted = don't change. Never rely on `None` to mean Auto.
- Model validation uses the **cached** presets (`get_model_presets()`) ∪ `MODEL_ALIASES.values()` — must never force a live Bedrock call in the request path beyond what `get_model_presets()` itself does (it has a 24h cache + safe fallback, never raises).
- 409 guard requires the new module-level in-flight registry in app.py (`_streaming_sessions: set[str]`), entry added at `_generate()` start, removed in its `finally`.
- Fixed output rules = today's **medium** template byte-for-byte (including RCA/SRE medium addenda). Prompt-budget goldens should NOT need re-pinning; if a band trips, investigate before touching goldens.
- `ContextPanel.tsx` "Detail chips" are pipeline-event metadata — do NOT touch that file.
- Do not modify unrelated code; each task compiles + tests green before commit.
- Commit with `--no-verify`; **NO `git push`** — owner confirms after final E2E.
- All commits end with: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
- Frontend check after any frontend task: `cd src/agenticops/web/frontend && npx tsc --noEmit`. Full `npm run build` in the final task.
- Python check: `.venv/bin/python -m py_compile <changed files>`; run the named pytest files.

---

### Task 0: Branch setup

- [ ] **Step 1: Create the branch**

```bash
cd /Users/malibo/MyDev/AgenticOps
git checkout MVP-2.0.0-release && git pull --no-verify origin MVP-2.0.0-release 2>/dev/null || true
git checkout -b MVP-2.0.1
```

Expected: `Switched to a new branch 'MVP-2.0.1'`. No commit.

---

### Task 1: Backend — `model_id` column + PATCH validation + 409 stream guard

**Files:**
- Modify: `src/agenticops/models.py` (ChatSession class ~:788; migration function ~:920-930 region)
- Modify: `src/agenticops/web/schemas.py` (`ChatSessionUpdate` :569-573, `ChatSessionResponse` :596-608)
- Modify: `src/agenticops/web/app.py` (PATCH handler :4186-4217; SSE `_generate()` :4411+; session-list builder)
- Test: `tests/test_session_model_switch.py` (new)

**Interfaces:**
- Consumes: existing `ChatSession` model, `get_model_presets()` (`services/model_service.py:134`, returns `[{"label","value","context_window"}]`, cached 24h, never raises), `MODEL_ALIASES` (config.py:801), `_chat_sessions.remove(session_id)` (session_manager.py:474).
- Produces (later tasks rely on): `chat_sessions.model_id` nullable column; `ChatSessionUpdate.model_id: Optional[str]`; `ChatSessionResponse.model_id: Optional[str]`; app.py module-level `_streaming_sessions: set[str]` + helper `_allowed_model_ids() -> set[str]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_session_model_switch.py`:

```python
"""Per-session model switch — column, PATCH validation, 409 stream guard."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

from agenticops.web.app import app, _streaming_sessions


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture()
def session_id(client):
    r = client.post("/api/chat/sessions", json={})
    assert r.status_code in (200, 201)
    return r.json()["session_id"]


PRESETS = [{"label": "Opus 4.8", "value": "global.anthropic.claude-opus-4-8", "context_window": 200000}]


class TestPatchModelId:
    def test_set_valid_model_persists_and_echoes(self, client, session_id):
        with patch("agenticops.web.app.get_model_presets", return_value=PRESETS):
            r = client.patch(f"/api/chat/sessions/{session_id}",
                             json={"model_id": "global.anthropic.claude-opus-4-8"})
        assert r.status_code == 200
        assert r.json()["model_id"] == "global.anthropic.claude-opus-4-8"
        # persisted — list endpoint echoes it too
        rows = client.get("/api/chat/sessions").json()
        mine = [s for s in rows if s["session_id"] == session_id][0]
        assert mine["model_id"] == "global.anthropic.claude-opus-4-8"

    def test_alias_value_accepted(self, client, session_id):
        # values from MODEL_ALIASES are allowed even if presets fetch is empty
        from agenticops.config import MODEL_ALIASES
        if not MODEL_ALIASES:
            pytest.skip("no aliases configured")
        target = next(iter(MODEL_ALIASES.values()))
        with patch("agenticops.web.app.get_model_presets", return_value=[]):
            r = client.patch(f"/api/chat/sessions/{session_id}", json={"model_id": target})
        assert r.status_code == 200

    def test_unknown_model_400(self, client, session_id):
        with patch("agenticops.web.app.get_model_presets", return_value=PRESETS):
            r = client.patch(f"/api/chat/sessions/{session_id}",
                             json={"model_id": "not.a.real.model"})
        assert r.status_code == 400

    def test_empty_string_means_auto_stored_null(self, client, session_id):
        with patch("agenticops.web.app.get_model_presets", return_value=PRESETS):
            client.patch(f"/api/chat/sessions/{session_id}",
                         json={"model_id": "global.anthropic.claude-opus-4-8"})
            r = client.patch(f"/api/chat/sessions/{session_id}", json={"model_id": ""})
        assert r.status_code == 200
        assert r.json()["model_id"] is None

    def test_omitted_field_unchanged(self, client, session_id):
        with patch("agenticops.web.app.get_model_presets", return_value=PRESETS):
            client.patch(f"/api/chat/sessions/{session_id}",
                         json={"model_id": "global.anthropic.claude-opus-4-8"})
            r = client.patch(f"/api/chat/sessions/{session_id}", json={"name": "renamed"})
        assert r.json()["model_id"] == "global.anthropic.claude-opus-4-8"

    def test_streaming_session_409(self, client, session_id):
        _streaming_sessions.add(session_id)
        try:
            with patch("agenticops.web.app.get_model_presets", return_value=PRESETS):
                r = client.patch(f"/api/chat/sessions/{session_id}",
                                 json={"model_id": "global.anthropic.claude-opus-4-8"})
            assert r.status_code == 409
        finally:
            _streaming_sessions.discard(session_id)

    def test_streaming_session_allows_non_model_patch(self, client, session_id):
        _streaming_sessions.add(session_id)
        try:
            r = client.patch(f"/api/chat/sessions/{session_id}", json={"pinned": True})
            assert r.status_code == 200
        finally:
            _streaming_sessions.discard(session_id)

    def test_model_change_evicts_only_this_session(self, client, session_id):
        with patch("agenticops.web.app._chat_sessions") as mock_mgr, \
             patch("agenticops.web.app.get_model_presets", return_value=PRESETS):
            client.patch(f"/api/chat/sessions/{session_id}",
                         json={"model_id": "global.anthropic.claude-opus-4-8"})
            mock_mgr.remove.assert_called_once_with(session_id)
            mock_mgr.clear.assert_not_called()
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_session_model_switch.py -q 2>&1 | tail -3`
Expected: ImportError — `cannot import name '_streaming_sessions'`.

- [ ] **Step 3: models.py — column + migration**

In `src/agenticops/models.py` ChatSession class (~:788), after the `archived` column add:

```python
    # Per-session main-agent model override; NULL = Auto (follow global config)
    model_id: Mapped[Optional[str]] = mapped_column(String(200), default=None)
```

In the migration function, right after the pinned/starred/archived block (~:930), add:

```python
    # Migration: add per-session model override to chat_sessions if missing
    if insp.has_table("chat_sessions"):
        columns = {col["name"] for col in insp.get_columns("chat_sessions")}
        if "model_id" not in columns:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE chat_sessions ADD COLUMN model_id VARCHAR(200)"))
                conn.commit()
```

- [ ] **Step 4: schemas.py**

`ChatSessionUpdate` (:569) — add after `archived`:

```python
    # "" = set Auto (stored NULL); omitted = don't change; non-empty = validated model id
    model_id: Optional[str] = None
```

`ChatSessionResponse` (:596) — add after `archived: bool = False`:

```python
    model_id: Optional[str] = None
```

- [ ] **Step 5: app.py — registry, helper, PATCH handler, list endpoint, SSE hooks**

(a) Near the other module-level chat state (search for `_chat_sessions = ` in app.py), add:

```python
# Sessions with an SSE response currently streaming — used to reject
# mid-stream model switches (409). Entries removed in the generator's finally.
_streaming_sessions: set[str] = set()


def _allowed_model_ids() -> set[str]:
    """Valid per-session model ids: cached presets ∪ alias targets (no live call beyond preset cache)."""
    from agenticops.config import MODEL_ALIASES
    return {p["value"] for p in get_model_presets()} | set(MODEL_ALIASES.values())
```

Ensure `from agenticops.services.model_service import get_model_presets` is imported at module top (it already is — verify; if aliased differently, match the existing import).

(b) PATCH handler (:4186) — inside the function, before `with get_db_session() as db:` add the guard; inside the field-copy section add model handling. Full replacement of the handler body:

```python
@app.patch("/api/chat/sessions/{session_id}", response_model=ChatSessionResponse)
async def api_rename_chat_session(session_id: str, payload: ChatSessionUpdate, background_tasks: BackgroundTasks):
    model_field_set = "model_id" in payload.model_fields_set
    if model_field_set and session_id in _streaming_sessions:
        raise HTTPException(409, "A response is still streaming — stop it before switching models")
    if model_field_set and payload.model_id:
        allowed = _allowed_model_ids()
        if payload.model_id not in allowed:
            raise HTTPException(400, f"Unknown model id. Allowed: {sorted(allowed)[:10]} ...")

    with get_db_session() as db:
        row = db.query(ChatSession).filter(ChatSession.session_id == session_id).first()
        if not row:
            raise HTTPException(404, "Session not found")
        if payload.name is not None:
            row.name = payload.name
        if payload.pinned is not None:
            row.pinned = payload.pinned
        if payload.starred is not None:
            row.starred = payload.starred
        # Track whether this request is archiving the session
        archiving = payload.archived is True and not row.archived
        if payload.archived is not None:
            row.archived = payload.archived
        model_changed = False
        if model_field_set:
            new_model = payload.model_id or None  # "" sentinel → NULL (Auto)
            model_changed = new_model != row.model_id
            row.model_id = new_model
        row.updated_at = datetime.now(timezone.utc)
        db.flush()
        cnt = db.query(func.count(ChatMessage.id)).filter(ChatMessage.session_id == row.id).scalar()
        response = ChatSessionResponse(
            id=row.id, session_id=row.session_id, name=row.name,
            created_at=row.created_at, updated_at=row.updated_at,
            last_activity_at=row.last_activity_at, message_count=cnt,
            pinned=row.pinned, starred=row.starred, archived=row.archived,
            model_id=row.model_id,
        )

    # Rebuild this session's agent with the new model on next message
    if model_changed:
        _chat_sessions.remove(session_id)

    # Trigger memory extraction in the background when archiving
    if archiving:
        from agenticops.web.session_manager import _trigger_memory_extraction
        background_tasks.add_task(_trigger_memory_extraction, session_id)

    return response
```

(c) Session-list endpoint (~:4110-4122) and any other place constructing `ChatSessionResponse` (grep `ChatSessionResponse(` in app.py — session create, get, list): add `model_id=row.model_id` (or the equivalent row variable) to each constructor call.

(d) SSE `_generate()` (:4411): first line inside `try` add `_streaming_sessions.add(session_id)`; in the generator's existing `finally` block add `_streaming_sessions.discard(session_id)`. If `_generate()` has no `finally`, wrap its body: the `try:` exists (:4567 shows `except`); append a `finally: _streaming_sessions.discard(session_id)` after the except block at the same level.

- [ ] **Step 6: Run tests**

Run: `.venv/bin/python -m pytest tests/test_session_model_switch.py -q 2>&1 | tail -3`
Expected: 8 passed.
Also: `.venv/bin/python -m pytest tests/test_chat_sessions.py tests/test_chat_messages_pagination.py -q 2>&1 | tail -2` (existing chat tests still green; file names may differ — run `ls tests/ | grep chat` and run all matches).

- [ ] **Step 7: Commit**

```bash
git add src/agenticops/models.py src/agenticops/web/schemas.py src/agenticops/web/app.py tests/test_session_model_switch.py
git commit --no-verify -m "feat(chat): per-session model_id — column, PATCH validation, 409 stream guard

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Backend — session_manager + main_agent honor the override; cost attribution

**Files:**
- Modify: `src/agenticops/agents/main_agent.py` (:207-239)
- Modify: `src/agenticops/web/session_manager.py` (:438-472)
- Modify: `src/agenticops/web/app.py` (cost blocks :4500-4511, :4538-4556)
- Test: `tests/test_session_model_switch.py` (append)

**Interfaces:**
- Consumes: Task 1's `chat_sessions.model_id` column.
- Produces: `create_main_agent(model_id_override: str = "") -> Agent`; `session_manager.get_or_create(session_id)` reads the session row's `model_id`; app.py helper `_effective_main_model(session_id) -> str` used by both cost blocks.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_session_model_switch.py`:

```python
class TestModelResolution:
    def test_create_main_agent_accepts_override(self):
        import inspect
        from agenticops.agents.main_agent import create_main_agent
        assert "model_id_override" in inspect.signature(create_main_agent).parameters

    def test_get_or_create_passes_session_model(self, client, session_id):
        from agenticops.web import session_manager as sm
        with patch("agenticops.web.app.get_model_presets", return_value=PRESETS):
            client.patch(f"/api/chat/sessions/{session_id}",
                         json={"model_id": "global.anthropic.claude-opus-4-8"})
        with patch.object(sm, "create_main_agent") as mock_create:
            mock_create.return_value.messages = []
            from agenticops.web.app import _chat_sessions
            _chat_sessions.remove(session_id)
            _chat_sessions.get_or_create(session_id)
            mock_create.assert_called_once_with(model_id_override="global.anthropic.claude-opus-4-8")
            _chat_sessions.remove(session_id)

    def test_auto_session_passes_empty_override(self, client, session_id):
        from agenticops.web import session_manager as sm
        with patch.object(sm, "create_main_agent") as mock_create:
            mock_create.return_value.messages = []
            from agenticops.web.app import _chat_sessions
            _chat_sessions.remove(session_id)
            _chat_sessions.get_or_create(session_id)
            mock_create.assert_called_once_with(model_id_override="")
            _chat_sessions.remove(session_id)


class TestEffectiveModelForCost:
    def test_effective_model_uses_override(self, client, session_id):
        from agenticops.web.app import _effective_main_model
        with patch("agenticops.web.app.get_model_presets", return_value=PRESETS):
            client.patch(f"/api/chat/sessions/{session_id}",
                         json={"model_id": "global.anthropic.claude-opus-4-8"})
        assert _effective_main_model(session_id) == "global.anthropic.claude-opus-4-8"

    def test_effective_model_auto_falls_back_to_global(self, client, session_id):
        from agenticops.web.app import _effective_main_model
        from agenticops.config import get_agent_model_config
        assert _effective_main_model(session_id) == get_agent_model_config("main")[0]
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_session_model_switch.py -q 2>&1 | tail -3`
Expected: fails — no `model_id_override` param / no `_effective_main_model`.

- [ ] **Step 3: main_agent.py override param**

Change the signature and model read (:207, :230):

```python
def create_main_agent(model_id_override: str = "") -> Agent:
    """Create and return the Main Agent (Orchestrator).

    Args:
        model_id_override: Per-session model id; empty = use global config.

    Returns:
        Configured Strands Agent with sub-agents and metadata tools.
    """
```

and:

```python
    model_id, max_tokens = get_agent_model_config("main")
    if model_id_override:
        model_id = model_id_override
```

- [ ] **Step 4: session_manager.py — read session model at build**

In `get_or_create` slow path (:456-457), replace `agent = create_main_agent()` with:

```python
            session_model = ""
            try:
                from agenticops.models import ChatSession, get_db_session
                with get_db_session() as db:
                    row = db.query(ChatSession).filter(ChatSession.session_id == session_id).first()
                    if row and row.model_id:
                        session_model = row.model_id
            except Exception:
                logger.warning("Could not read session model for %s; using global", session_id, exc_info=True)
            agent = create_main_agent(model_id_override=session_model)
```

(Match the module's existing import style — if `get_db_session`/`ChatSession` are already imported at module top, use those.)

- [ ] **Step 5: app.py — `_effective_main_model` + wire both cost blocks**

Add next to `_allowed_model_ids()`:

```python
def _effective_main_model(session_id: str) -> str:
    """Session model override if set, else global main model (for cost attribution)."""
    from agenticops.config import get_agent_model_config
    with get_db_session() as db:
        row = db.query(ChatSession).filter(ChatSession.session_id == session_id).first()
        if row and row.model_id:
            return row.model_id
    return get_agent_model_config("main")[0]
```

Assistant-persist block (:4500-4511): replace

```python
                        from agenticops.config import get_agent_model_config
                        _msg_model, _ = get_agent_model_config("main")
```

with

```python
                        _msg_model = _effective_main_model(session_id)
```

log_agent_call block (:4538-4556): replace

```python
                from agenticops.config import get_agent_model_config
                _main_model_id, _ = get_agent_model_config("main")
```

with

```python
                _main_model_id = _effective_main_model(session_id)
```

- [ ] **Step 6: Run tests**

Run: `.venv/bin/python -m pytest tests/test_session_model_switch.py -q 2>&1 | tail -3`
Expected: 13 passed.
Regression: `.venv/bin/python -m pytest tests/test_cost_api.py tests/test_agent_log_cost.py -q 2>&1 | tail -2` — green.

- [ ] **Step 7: Commit**

```bash
git add src/agenticops/agents/main_agent.py src/agenticops/web/session_manager.py src/agenticops/web/app.py tests/test_session_model_switch.py
git commit --no-verify -m "feat(chat): session model override in agent build + cost attribution

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Frontend — composer ModelSelector (replaces detail select)

**Files:**
- Create: `src/agenticops/web/frontend/src/components/chat/ModelSelector.tsx`
- Modify: `src/agenticops/web/frontend/src/components/chat/ChatInput.tsx` (props :9-16, :32; selector block :176-189)
- Modify: `src/agenticops/web/frontend/src/pages/Chat.tsx` (:26, :144, :222, :293, :297)
- Modify: `src/agenticops/web/frontend/src/hooks/useChatSessions.ts` (useUpdateChatSession fields)
- Modify: `src/agenticops/web/frontend/src/api/types.ts` (ChatSession :578-589)
- Modify: `src/agenticops/web/frontend/src/locales/en.json`, `zh.json`
- Modify: `src/agenticops/web/frontend/src/lib/chatStream.ts` (:92,127,133), `src/hooks/useSessionStream.ts` (:50,63), `src/hooks/useLazySessionCreate.ts` (:23,48)

**Interfaces:**
- Consumes: `useSettings()` (`model_presets: {label,value,context_window?}[]`, `agent_models`), `useUpdateChatSession()` (PATCH), `useSessionStream(sessionId).streaming`.
- Produces: `<ModelSelector sessionId={string} disabled={boolean} />` self-contained component (fetches session via `useChatSessions`, patches via `useUpdateChatSession`).

- [ ] **Step 1: types + hook fields**

`api/types.ts` ChatSession — add after `archived: boolean;`:

```typescript
  model_id: string | null;
```

`useChatSessions.ts` `useUpdateChatSession` fields type — add:

```typescript
      model_id?: string;
```

- [ ] **Step 2: i18n keys**

`en.json` (in the chat.* block):

```json
  "chat.model.auto": "Auto",
  "chat.model.followGlobal": "Auto (follow global setting)",
  "chat.model.switchTooltip": "Model for this session",
  "chat.model.streamingLocked": "Wait for the current response to finish",
```

`zh.json`:

```json
  "chat.model.auto": "自动",
  "chat.model.followGlobal": "自动（跟随全局设置）",
  "chat.model.switchTooltip": "本会话使用的模型",
  "chat.model.streamingLocked": "等待当前回复完成后可切换",
```

- [ ] **Step 3: Create ModelSelector.tsx**

```tsx
import { useState } from "react";
import * as Popover from "@radix-ui/react-popover";
import { useSettings } from "@/hooks/useSettings";
import { useChatSessions, useUpdateChatSession } from "@/hooks/useChatSessions";
import { useLocale } from "@/i18n/LocaleContext";

/** Strip provider prefix: "global.anthropic.claude-opus-4-8" → "claude-opus-4-8" */
function shortName(id: string): string {
  const parts = id.split(".");
  return parts.length > 2 ? parts.slice(2).join(".") : id;
}

export function ModelSelector({ sessionId, disabled }: { sessionId: string | null; disabled?: boolean }) {
  const { t } = useLocale();
  const [open, setOpen] = useState(false);
  const settingsQ = useSettings();
  const sessionsQ = useChatSessions();
  const update = useUpdateChatSession();

  if (!sessionId) return null;
  const session = sessionsQ.data?.find((s) => s.session_id === sessionId);
  const presets = settingsQ.data?.model_presets ?? [];
  const globalMain = settingsQ.data?.agent_models?.["main"]?.model_id ?? "";

  const current = session?.model_id ?? null;
  const currentLabel = current
    ? presets.find((p) => p.value === current)?.label ?? shortName(current)
    : `${t("chat.model.auto")} · ${presets.find((p) => p.value === globalMain)?.label ?? shortName(globalMain)}`;

  const select = (value: string) => {
    update.mutate({ sessionId, model_id: value });
    setOpen(false);
  };

  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger asChild>
        <button
          disabled={disabled}
          className="self-center max-w-[180px] truncate text-[11px] rounded-lg px-2 py-1 text-muted-foreground bg-transparent hover:bg-muted focus:outline-none disabled:opacity-50 cursor-pointer"
          title={disabled ? t("chat.model.streamingLocked") : t("chat.model.switchTooltip")}
        >
          {currentLabel}
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content side="top" align="start" sideOffset={6}
          className="z-50 w-72 rounded-xl border border-border bg-background shadow-lg p-1.5">
          <button
            onClick={() => select("")}
            className={`w-full text-left px-2.5 py-1.5 rounded-lg text-xs hover:bg-muted ${!current ? "text-primary font-medium" : "text-foreground"}`}
          >
            {t("chat.model.followGlobal")}
            {!current && <span className="float-right">✓</span>}
          </button>
          <div className="my-1 border-t border-border" />
          {presets.map((p) => (
            <button
              key={p.value}
              onClick={() => select(p.value)}
              className={`w-full text-left px-2.5 py-1.5 rounded-lg text-xs hover:bg-muted ${current === p.value ? "text-primary font-medium" : "text-foreground"}`}
            >
              <span className="block truncate">{p.label}</span>
              <span className="block truncate text-[10px] text-muted-foreground">{p.value}</span>
              {current === p.value && <span className="float-right -mt-6">✓</span>}
            </button>
          ))}
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
```

- [ ] **Step 4: ChatInput.tsx — swap detail select for ModelSelector**

Props (:9-16): remove `detailLevel?: string;` and `onDetailLevelChange?: (level: string) => void;`, add `sessionId?: string | null;`. Destructure (:32) accordingly.

Replace the detail-select block (:176-189) with:

```tsx
          {/* Per-session model selector */}
          <ModelSelector sessionId={sessionId ?? null} disabled={disabled || streaming} />
```

Add the import: `import { ModelSelector } from "./ModelSelector";`

- [ ] **Step 5: Chat.tsx + stream plumbing detail removal**

- `Chat.tsx:26` — delete the `usePersistedState("aiops-detail-level", "medium")` line (and the `usePersistedState` import if now unused; check other usages first — `aiops-chat-split` also uses it, keep the import).
- `:144` `sendFirstMessage(content, files, detailLevel)` → `sendFirstMessage(content, files)`
- `:222,297` remove `detailLevel={detailLevel}` props; pass `sessionId={activeSessionId}` (use the existing session-id variable in scope at those call sites — grep nearby lines for the active session variable name and reuse it)
- `:293` `sendMessage(msg, files, detailLevel)` → `sendMessage(msg, files)`
- `chatStream.ts:92` `async send(sessionId, content, files?, detailLevel?)` → drop the param; delete lines :127 and :133 (`if (detailLevel && ...)`)
- `useSessionStream.ts:50,63` and `useLazySessionCreate.ts:23,48` — drop the `detailLevel` param and pass-through.

- [ ] **Step 6: TypeScript check**

Run: `cd /Users/malibo/MyDev/AgenticOps/src/agenticops/web/frontend && npx tsc --noEmit`
Expected: clean. (Any leftover `detailLevel` reference will surface here.)
Also: `grep -rn "detailLevel\|detail_level\|aiops-detail-level" src/ | grep -v node_modules` → must return ZERO lines.

- [ ] **Step 7: Commit**

```bash
git add src/agenticops/web/frontend/src
git commit --no-verify -m "feat(chat-ui): composer per-session ModelSelector replaces detail select

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Backend + config + prompts — detail-level removal

**Files:**
- Modify: `src/agenticops/web/schemas.py` (:578)
- Modify: `src/agenticops/web/app.py` (:4291-4298 extraction, :4348-4351, :4411-4416)
- Modify: `src/agenticops/config.py` (:490-494, :948-978)
- Modify: `config/settings.yaml` (:73)
- Modify: `src/agenticops/agents/preamble.py` (:82-157)
- Modify: `src/agenticops/skills/loader.py` (:436-443)
- Modify: `tests/test_preamble.py` (:59-85), delete `tests/test_detail_level.py`

**Interfaces:**
- Produces: `preamble.OUTPUT_RULES: str` (single template), `RCA_ADDENDA: str`, `SRE_ADDENDA: str`, `get_output_rules(agent_type: str = "generic") -> str` (same signature, no ContextVar). Task 5 (CLI) relies on `VALID_DETAIL_LEVELS`/`set_detail_level`/`get_detail_level` being GONE from config.

- [ ] **Step 1: Update tests first**

Delete: `rm tests/test_detail_level.py`

In `tests/test_preamble.py` replace the `TestGetOutputRules` class (:59-85) with:

```python
class TestGetOutputRules:
    """Output rules are fixed (single medium template since MVP-2.0.1)."""

    def test_generic_rules(self):
        from agenticops.agents.preamble import get_output_rules
        rules = get_output_rules()
        assert "~1500 tokens" in rules

    def test_rca_addenda_appended(self):
        from agenticops.agents.preamble import get_output_rules
        rules = get_output_rules(agent_type="rca")
        assert "Root Cause" in rules
        assert "Contributing Factors" in rules

    def test_sre_addenda_appended(self):
        from agenticops.agents.preamble import get_output_rules
        rules = get_output_rules(agent_type="sre")
        assert "Mode A" in rules

    def test_detail_level_machinery_gone(self):
        import agenticops.config as cfg
        assert not hasattr(cfg, "set_detail_level")
        assert not hasattr(cfg, "get_detail_level")
        assert not hasattr(cfg, "VALID_DETAIL_LEVELS")
```

(If other tests in the file patch `get_detail_level`, update them the same way — grep the file.)

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_preamble.py -q 2>&1 | tail -3`
Expected: `test_detail_level_machinery_gone` FAILS (attrs still exist).

- [ ] **Step 3: preamble.py collapse**

Replace :82-157 (the three dicts + get_output_rules) with:

```python
# ── Output Format Rules (fixed — detail levels removed in MVP-2.0.1) ─

OUTPUT_RULES: str = """\
OUTPUT FORMAT RULES (target ~1500 tokens):
- Keep responses CONCISE. Aim for 500-1500 tokens of output text.
- Use bullet points and short sentences — not paragraphs.
- Lead with a 2-3 sentence summary, then key findings as bullets.
- Include brief recommendations section when relevant.
- Do NOT echo back full skill content or tool results verbatim. Summarize key findings.
- Do NOT repeat the user's question or restate the protocol steps.
- When citing resource IDs, use inline format (e.g., "i-0abc123 is running") not tables."""

RCA_ADDENDA: str = """\
- Structure: Root Cause → Evidence → Contributing Factors → Recommendations → Fix Plan (if applicable)."""

SRE_ADDENDA: str = """\
- For Mode A (fix plans): use numbered steps, one line per step.
- For Mode B (investigation): lead with a 2-3 sentence summary, then key findings as bullets."""


def get_output_rules(agent_type: str = "generic") -> str:
    """Return the OUTPUT FORMAT RULES block (fixed medium template).

    Args:
        agent_type: One of 'rca', 'sre', or 'generic'.
    """
    if agent_type == "rca":
        return f"{OUTPUT_RULES}\n{RCA_ADDENDA}"
    if agent_type == "sre":
        return f"{OUTPUT_RULES}\n{SRE_ADDENDA}"
    return OUTPUT_RULES
```

Also remove `get_detail_level` from the preamble import at :14: `from agenticops.config import get_detail_level, settings` → `from agenticops.config import settings`.

- [ ] **Step 4: config.py + settings.yaml**

- Delete :490-494 (`agent_output_detail` field + comment).
- Delete :948-976 (the whole `# ── Agent Detail Level` block: `VALID_DETAIL_LEVELS`, `_detail_level_var`, `get_detail_level`, `set_detail_level`). Keep the Scan Focus block that follows.
- If `contextvars` import becomes unused, check first: `grep -n "contextvars" src/agenticops/config.py` — scan_focus/trace_id also use it; keep if used.
- `config/settings.yaml`: delete line 73 `agent_output_detail: medium`.

- [ ] **Step 5: schemas.py + app.py**

- schemas.py:578 — delete the `detail_level` field from `ChatMessageCreate` (keep `scan_focus`).
- app.py: delete `:4291` (`detail_level_req: Optional[str] = None`), `:4297` (form extraction), `:4350` (`detail_level_req = payload.detail_level`), and the `_generate()` block :4412-4416 (`if detail_level_req: ... set_detail_level(...)`). Keep all scan_focus twins.

- [ ] **Step 6: skills/loader.py back-compat block**

Replace :436-443 imports to match the new names (they're re-exports; same symbols still exist so only the comment changes — verify `_OUTPUT_RULES` etc. still import cleanly; they will, since we kept the names with new types). No change needed unless a consumer indexes `_OUTPUT_RULES["medium"]` — check: `grep -rn "_OUTPUT_RULES\|_RCA_ADDENDA\|_SRE_ADDENDA" src/ tests/` and fix any dict-style access found.

- [ ] **Step 7: Run tests**

```bash
.venv/bin/python -m py_compile src/agenticops/config.py src/agenticops/agents/preamble.py src/agenticops/web/app.py src/agenticops/web/schemas.py src/agenticops/skills/loader.py
.venv/bin/python -m pytest tests/test_preamble.py tests/test_prompt_budget.py tests/test_session_model_switch.py -q 2>&1 | tail -3
grep -rn "detail_level\|VALID_DETAIL_LEVELS\|set_detail_level\|get_detail_level\|agent_output_detail" src/agenticops/web/ src/agenticops/config.py src/agenticops/agents/ | grep -v "\.pyc"
```
Expected: compile clean; tests green (prompt goldens must NOT trip — if they do, STOP and investigate); grep returns only CLI hits (removed in Task 5).

- [ ] **Step 8: Commit**

```bash
git add -A src/agenticops config/settings.yaml tests/test_preamble.py
git rm tests/test_detail_level.py 2>/dev/null; git add tests/
git commit --no-verify -m "refactor(prompts): remove detail-level machinery — fixed medium output rules

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: CLI detail removal + docs

**Files:**
- Modify: `src/agenticops/cli/main.py` (:3507-3520, :4065, :4086, :4099-4104, :4173, :4267-4270, :2562, :2633-2657, :2830-2852)
- Modify: `src/agenticops/cli/context.py` (:9, :19, :37-42)
- Modify: `tests/test_cli_session_commands.py` (:290)
- Modify: `docs/WORKFLOW.md` (:634, :813-816, :827, :1016, :1051-1054), `CLAUDE.md` (config table `agent_output_detail` row), `docs/MVP-2.0.0-RELEASE.md` or new `docs/MVP-2.0.1-RELEASE.md` note

**Interfaces:** none new — deletions.

- [ ] **Step 1: CLI edits**

main.py:
- Delete the `/detail` command block (:3507-3520, from `# Detail level command` through its final `return`).
- Delete the typer option (:4065): the `detail: Optional[str] = typer.Option(None, "--detail", "-d", ...)` line.
- :4086: `from agenticops.config import VALID_DETAIL_LEVELS, set_detail_level` — delete the whole line (scan_focus import on :4087 stays).
- Delete the `if detail:` block (:4099-4104).
- :4173: remove `"/detail", ` from the slash-commands list.
- :4267-4270: change to keep only scan focus:

```python
            # Set scan focus from context before each agent call
            from agenticops.config import set_scan_focus as _set_sf
            _set_sf(ctx.scan_focus)
```

- :2562: delete the line `(ctx.detail_level == "detailed") and console.print(...)` (keep the surrounding if-block's other content).
- :2633-2657 `/context`: remove the `Detail Level: {ctx.detail_level}` line from the status text and `ctx.detail_level = "medium"` from reset.
- :2830-2852 `/session save/load`: remove `"detail_level": ctx.detail_level,` from save dict and `ctx.detail_level = data.get("detail_level", "medium")` from load (loading old files with the key still works — key is just ignored).

context.py:
- :9 import — drop `VALID_DETAIL_LEVELS` from the config import.
- :19 delete `self.detail_level = "medium"  # ...`.
- :37-42 delete the whole `set_detail` method.

- [ ] **Step 2: Fix the CLI test**

`tests/test_cli_session_commands.py:290` — delete the `ctx.detail_level = "detailed"` line (the save/load assertions still pass; the saved JSON simply has no detail key).

- [ ] **Step 3: Docs**

- WORKFLOW.md :634 — remove `detail_level` from the contextvars list (keep scan_focus, trace_id).
- :813-816 — delete the three `-d` example lines; :827 — delete the "Detail levels:" paragraph.
- :1016 — delete the `/detail` slash-command table row.
- :1051-1054 — change the curl example body to `-d '{"content": "deep dive on EC2"}'` and retitle the comment `# Send message`.
- CLAUDE.md — delete the `agent_output_detail` row from the Key Configuration table.
- Release note: create `docs/MVP-2.0.1-RELEASE.md` with a short header (version 2.0.1, date, branch `MVP-2.0.1`) and two bullets: per-session model switch; detail-level removal. Keep it brief — it grows with sub-projects B/C/D.

- [ ] **Step 4: Verify**

```bash
.venv/bin/python -m py_compile src/agenticops/cli/main.py src/agenticops/cli/context.py
.venv/bin/python -m pytest tests/test_cli_session_commands.py tests/test_preamble.py -q 2>&1 | tail -2
grep -rn "detail_level\|VALID_DETAIL_LEVELS\|set_detail_level\|get_detail_level\|agent_output_detail" src/ --include="*.py" | grep -v test_
```
Expected: compile clean, tests green, grep → ZERO lines.

- [ ] **Step 5: Commit**

```bash
git add src/agenticops/cli tests/test_cli_session_commands.py docs/WORKFLOW.md CLAUDE.md docs/MVP-2.0.1-RELEASE.md
git commit --no-verify -m "refactor(cli): remove /detail command and --detail flag; docs updated

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Full regression + build + live E2E — then STOP for owner

**Files:** none new.

- [ ] **Step 1: Full backend regression**

Run: `caffeinate -i .venv/bin/python -u -m pytest tests/ -q --tb=line 2>&1 | tail -5`
Expected: same baseline as main (~3400+ passed) + new tests; ZERO new failures. (The 3 config-drift failures were fixed on main by d8a413d — if this branch was cut before syncing main, `git merge origin/main` first.)

- [ ] **Step 2: Frontend build**

Run: `cd src/agenticops/web/frontend && npx tsc --noEmit && npm run build 2>&1 | tail -3`
Expected: clean build.

- [ ] **Step 3: Live E2E (Playwright or manual, server running)**

```bash
pkill -f "uvicorn agenticops" 2>/dev/null; sleep 1
nohup .venv/bin/uvicorn agenticops.web.app:app --host 0.0.0.0 --port 8000 > /tmp/aiops-e2e.log 2>&1 &
sleep 5
```

Verify via browser (Playwright MCP) at `http://localhost:8000/app/chat`:
1. Composer shows the model pill ("Auto · <global model>"); detail select is gone.
2. Open popover → pick a non-default model → pill updates; reload page → pill persists.
3. Send a message → response streams; expand the TokenMetrics footer → trace shows the overridden model; cost present.
4. While streaming, the pill is disabled.
5. Switch back to Auto → next message uses global model.

- [ ] **Step 4: STOP — report to owner**

Report test counts, E2E screenshots, commit list. **Do NOT push, do NOT merge** — owner confirms E2E then decides (project rule: push only after E2E + owner confirmation).
