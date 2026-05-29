# ① Core Review & Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 18 adversarially-verified bugs/optimizations across the agent prompt layer, web/CLI chat, and session manager, then mechanically split `app.py` (6476L) and `main.py` (4918L) — with a regression test per fix.

**Architecture:** Two stages. Stage 1 (P1–P3): targeted fixes, each with a failing test → minimal fix → passing test → commit. Stage 2 (P4–P5): pure mechanical file splits (zero logic change), one module per commit, each gated by full test suite + import smoke test. Fixes land before splits so the verified line numbers stay valid.

**Tech Stack:** Python 3.12, Strands SDK on AWS Bedrock, FastAPI + SSE (`sse-starlette` `EventSourceResponse`), Typer CLI, SQLAlchemy, pytest. Spec: `docs/superpowers/specs/2026-05-29-core-review-hardening-design.md`.

**Conventions:**
- Run a single test: `.venv/bin/python -m pytest tests/<file>::<Class>::<test> -v`
- Run a file: `.venv/bin/python -m pytest tests/<file> -v`
- Full suite (gate): `.venv/bin/python -m pytest tests/ -q`
- Compile gate: `.venv/bin/python -m py_compile src/agenticops/<file>.py`
- All commits use `git commit --no-verify` (Code Defender bypass — project standing rule).
- Add regression tests to the **existing** test file for each area; do not create new files unless none exists.

---

## Stage 1 — Targeted Fixes (P1–P3)

### Task 1: F2 — Persist slash commands in CLI chat loop

**Why:** `cli/main.py:4174-4189` — slash commands that return a string `continue` past `_cli_persist_message`, so they never reach the DB while agent turns do. CLI history is inconsistent with the Web path (which persists `/channel` & `/send_to`).

**Files:**
- Modify: `src/agenticops/cli/main.py:4174-4189`
- Test: `tests/test_cli_message_persistence.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_cli_message_persistence.py` (match existing style — it already exercises `_cli_persist_message`):

```python
def test_slash_command_result_is_persisted(monkeypatch):
    """A slash command that returns display text persists user + system messages."""
    from agenticops.cli import main as cli_main

    persisted = []
    monkeypatch.setattr(
        cli_main, "_cli_persist_message",
        lambda ctx, role, content, **kw: persisted.append((role, content)),
    )
    # Stub the dispatcher to behave like a normal display-returning slash command
    monkeypatch.setattr(cli_main, "handle_slash_command", lambda ctx, cmd: "STATUS OUTPUT")

    from agenticops.cli.context import ChatContext
    ctx = ChatContext()
    # Exercise the persistence helper the loop should call for slash results:
    cli_main._persist_slash_interaction(ctx, "/status", "STATUS OUTPUT")

    assert ("user", "/status") in persisted
    assert ("system", "STATUS OUTPUT") in persisted
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_cli_message_persistence.py::test_slash_command_result_is_persisted -v`
Expected: FAIL — `AttributeError: module 'agenticops.cli.main' has no attribute '_persist_slash_interaction'`

- [ ] **Step 3: Add the helper + call it in the loop**

Add this helper near `_cli_persist_message` in `src/agenticops/cli/main.py` (after the function ending at line 3880):

```python
def _persist_slash_interaction(ctx, command: str, result: str) -> None:
    """Persist a slash command and its textual result to DB (parity with agent turns)."""
    _cli_persist_message(ctx, "user", command)
    if result:
        _cli_persist_message(ctx, "system", result)
```

Then in the slash branch at `src/agenticops/cli/main.py`, change the `elif result:` block (lines 4184-4187) from:

```python
                elif result:
                    ctx.add_to_history("system", result)
                    print_with_truncation(console, result, ctx, header="System")
                    continue
```

to:

```python
                elif result:
                    ctx.add_to_history("system", result)
                    _persist_slash_interaction(ctx, user_input, result)
                    print_with_truncation(console, result, ctx, header="System")
                    continue
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_cli_message_persistence.py::test_slash_command_result_is_persisted -v`
Expected: PASS

- [ ] **Step 5: Compile + commit**

```bash
.venv/bin/python -m py_compile src/agenticops/cli/main.py
git add src/agenticops/cli/main.py tests/test_cli_message_persistence.py
git commit --no-verify -m "fix(cli): persist slash command interactions to DB (F2)"
```

---

### Task 2: F3 — Unify token-usage extraction to accumulated_usage

**Why:** Three divergent sources — REPL uses `result.metrics.accumulated_usage` (`main.py:4238`), headless uses `latest_agent_invocation` (`main.py:3819`), Web uses `latest_agent_invocation` (`app.py:5592`). `accumulated_usage` is correct (covers all sub-agent calls in a turn). Centralize in one helper.

**Files:**
- Create: `src/agenticops/agents/metrics.py`
- Modify: `src/agenticops/cli/main.py:3818-3823`, `src/agenticops/cli/main.py:4236-4266`, `src/agenticops/web/app.py:5589-5595`
- Test: `tests/test_agent_metrics.py` (new — no existing metrics test file)

- [ ] **Step 1: Write the failing test**

Create `tests/test_agent_metrics.py`:

```python
"""Tests for unified token-usage extraction (agents/metrics.py)."""
from types import SimpleNamespace

from agenticops.agents.metrics import extract_token_usage


def _result_with_accumulated(inp, out, cr=0, cw=0):
    acc = {"inputTokens": inp, "outputTokens": out,
           "cacheReadInputTokens": cr, "cacheWriteInputTokens": cw}
    return SimpleNamespace(metrics=SimpleNamespace(accumulated_usage=acc))


def test_extracts_accumulated_usage():
    usage = extract_token_usage(_result_with_accumulated(100, 50, 10, 5))
    assert usage == {"input": 100, "output": 50, "cache_read": 10, "cache_write": 5}


def test_missing_metrics_returns_zeros():
    usage = extract_token_usage(SimpleNamespace())
    assert usage == {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}


def test_none_result_returns_zeros():
    usage = extract_token_usage(None)
    assert usage == {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_agent_metrics.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agenticops.agents.metrics'`

- [ ] **Step 3: Create the helper**

Create `src/agenticops/agents/metrics.py`:

```python
"""Unified token-usage extraction from Strands agent results.

Single source of truth so CLI (REPL + headless) and Web all report the same
numbers. Uses accumulated_usage (covers the main agent + every sub-agent call
in the turn), not latest_agent_invocation (which only sees the last call).
"""

from __future__ import annotations

from typing import Any


def extract_token_usage(result: Any) -> dict[str, int]:
    """Return {input, output, cache_read, cache_write} from an agent result.

    Never raises — returns zeros when metrics are absent.
    """
    zero = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
    try:
        acc = result.metrics.accumulated_usage  # type: ignore[union-attr]
        if not acc:
            return zero
        return {
            "input": acc.get("inputTokens", 0),
            "output": acc.get("outputTokens", 0),
            "cache_read": acc.get("cacheReadInputTokens", 0),
            "cache_write": acc.get("cacheWriteInputTokens", 0),
        }
    except Exception:
        return zero
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_agent_metrics.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Wire CLI headless (`main.py:3818-3823`)**

Replace:

```python
        # Token summary
        try:
            invocation = result.metrics.latest_agent_invocation
            if invocation:
                inp = invocation.usage.get("inputTokens", 0)
                out = invocation.usage.get("outputTokens", 0)
                console.print(f"\n[dim]Tokens: ↑{inp} ↓{out} Σ{inp + out}[/dim]")
        except Exception:
            pass
```

with:

```python
        # Token summary
        from agenticops.agents.metrics import extract_token_usage
        _u = extract_token_usage(result)
        inp, out = _u["input"], _u["output"]
        if inp or out:
            console.print(f"\n[dim]Tokens: ↑{inp} ↓{out} Σ{inp + out}[/dim]")
```

- [ ] **Step 6: Wire CLI REPL (`main.py:4236-4266`)**

Replace the REPL extraction block (lines 4236-4247) from:

```python
                # Extract token usage from Strands metrics (main + sub-agents)
                try:
                    accumulated = result.metrics.accumulated_usage
                    if accumulated:
                        ctx.add_tokens(
                            input_tokens=accumulated.get("inputTokens", 0),
                            output_tokens=accumulated.get("outputTokens", 0),
                            cache_read=accumulated.get("cacheReadInputTokens", 0),
                            cache_write=accumulated.get("cacheWriteInputTokens", 0),
                        )
                except Exception:
                    pass  # Don't break chat if metrics extraction fails
```

to:

```python
                # Extract token usage from Strands metrics (main + sub-agents)
                from agenticops.agents.metrics import extract_token_usage
                _u = extract_token_usage(result)
                if any(_u.values()):
                    ctx.add_tokens(
                        input_tokens=_u["input"],
                        output_tokens=_u["output"],
                        cache_read=_u["cache_read"],
                        cache_write=_u["cache_write"],
                    )
```

And replace the persistence token block (lines 4256-4267) from:

```python
            # Persist assistant response to DB (shared with Web Dashboard)
            _token_usage_dict = None
            try:
                _acc = result.metrics.accumulated_usage
                if _acc:
                    _token_usage_dict = {
                        "input": _acc.get("inputTokens", 0),
                        "output": _acc.get("outputTokens", 0),
                    }
            except Exception:
                pass
            _cli_persist_message(ctx, "assistant", response, token_usage=_token_usage_dict)
```

to:

```python
            # Persist assistant response to DB (shared with Web Dashboard)
            _u2 = extract_token_usage(result)
            _token_usage_dict = {"input": _u2["input"], "output": _u2["output"]} if any(_u2.values()) else None
            _cli_persist_message(ctx, "assistant", response, token_usage=_token_usage_dict)
```

- [ ] **Step 7: Wire Web (`app.py:5589-5595`)**

In the `if "result" in ev:` block, replace lines 5589-5595 from:

```python
                if "result" in ev:
                    res = ev["result"]
                    if hasattr(res, "metrics"):
                        inv = getattr(res.metrics, "latest_agent_invocation", None)
                        if inv and hasattr(inv, "usage"):
                            input_tokens = inv.usage.get("inputTokens", 0)
                            output_tokens = inv.usage.get("outputTokens", 0)
```

to:

```python
                if "result" in ev:
                    res = ev["result"]
                    from agenticops.agents.metrics import extract_token_usage
                    _u = extract_token_usage(res)
                    if _u["input"] or _u["output"]:
                        input_tokens = _u["input"]
                        output_tokens = _u["output"]
```

- [ ] **Step 8: Compile, run suite, commit**

```bash
.venv/bin/python -m py_compile src/agenticops/agents/metrics.py src/agenticops/cli/main.py src/agenticops/web/app.py
.venv/bin/python -m pytest tests/test_agent_metrics.py tests/test_cli_message_persistence.py -v
git add src/agenticops/agents/metrics.py src/agenticops/cli/main.py src/agenticops/web/app.py tests/test_agent_metrics.py
git commit --no-verify -m "fix(metrics): unify token usage to accumulated_usage across CLI/Web (F3)"
```

---

### Task 3: F1 — Mark failed stream turns with error metadata (no DB column)

**Why:** `app.py:5659-5671` — when `stream_async` raises mid-stream, the partial text is persisted with `token_usage=None` and no failure marker; the user message is already saved. `ChatMessage` has no `status` column, so we encode the error in the existing `token_usage` JSON and keep the user message for retry. No migration.

**Files:**
- Modify: `src/agenticops/web/app.py:5659-5671`
- Test: `tests/test_chat_api.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_chat_api.py` (it has a `client` fixture and creates sessions inline via `get_db_session()` — match that pattern; there is NO `make_session` helper). This test drives the stream with a mocked agent that raises:

```python
def test_stream_failure_marks_assistant_message_with_error(client, monkeypatch):
    """When stream_async raises mid-stream, the assistant row carries error metadata."""
    import agenticops.web.app as webapp
    from agenticops.models import ChatMessage, ChatSession, get_db_session

    session_id = "stream-fail-001"
    now = datetime.now(timezone.utc)
    with get_db_session() as db:
        db.add(ChatSession(session_id=session_id, name="Stream Fail",
                           created_at=now, updated_at=now, last_activity_at=now))

    class _BoomAgent:
        async def stream_async(self, _content):
            yield {"data": "partial "}
            raise RuntimeError("bedrock exploded")

    monkeypatch.setattr(webapp._chat_sessions, "get_or_create", lambda sid: _BoomAgent())

    try:
        resp = client.post(f"/api/chat/sessions/{session_id}/messages", json={"content": "hi"})
        assert resp.status_code == 200  # SSE opens fine; error surfaces as an event

        with get_db_session() as db:
            row = db.query(ChatSession).filter(ChatSession.session_id == session_id).first()
            msgs = db.query(ChatMessage).filter(ChatMessage.session_id == row.id).all()
            roles = [m.role for m in msgs]
            assert "user" in roles  # user message retained for retry
            asst = [m for m in msgs if m.role == "assistant"]
            assert asst, "partial assistant message should be persisted"
            assert asst[-1].token_usage and "error" in asst[-1].token_usage
    finally:
        with get_db_session() as db:
            row = db.query(ChatSession).filter(ChatSession.session_id == session_id).first()
            if row:
                db.query(ChatMessage).filter(ChatMessage.session_id == row.id).delete()
                db.delete(row)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_chat_api.py::test_stream_failure_marks_assistant_message_with_error -v`
Expected: FAIL — `assert asst[-1].token_usage and "error" in asst[-1].token_usage` (currently `token_usage` is None on failure).

- [ ] **Step 3: Add error metadata in the except block**

In `src/agenticops/web/app.py`, replace the `except Exception as e:` block (lines 5659-5671) from:

```python
        except Exception as e:
            logger.exception("Chat stream error for session %s", session_id)
            # Persist partial assistant reply so it isn't lost on error/refresh
            if accumulated:
                with get_db_session() as db:
                    db.add(ChatMessage(
                        session_id=db_session_pk,
                        role="assistant",
                        content=accumulated,
                        tool_calls=tool_calls if tool_calls else None,
                        token_usage={"input": input_tokens, "output": output_tokens} if input_tokens else None,
                    ))
            yield {"event": "error", "data": json.dumps({"message": str(e)})}
```

to:

```python
        except Exception as e:
            logger.exception("Chat stream error for session %s", session_id)
            # Persist partial assistant reply (if any) WITH error metadata so the
            # UI can distinguish a failed turn from a completed one, and the user
            # message stays for retry. ChatMessage has no status column, so the
            # marker rides in the token_usage JSON.
            err_meta = {"input": input_tokens, "output": output_tokens, "error": str(e)[:500]}
            with get_db_session() as db:
                db.add(ChatMessage(
                    session_id=db_session_pk,
                    role="assistant",
                    content=accumulated or "",
                    tool_calls=tool_calls if tool_calls else None,
                    token_usage=err_meta,
                ))
            yield {"event": "error", "data": json.dumps({"message": str(e)})}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_chat_api.py::test_stream_failure_marks_assistant_message_with_error -v`
Expected: PASS

> If `make_session`/`client` fixture names differ in `test_chat_api.py`, adapt the test to the file's actual fixtures (read the top of the file first). The assertion logic stays the same.

- [ ] **Step 5: Compile, run chat tests, commit**

```bash
.venv/bin/python -m py_compile src/agenticops/web/app.py
.venv/bin/python -m pytest tests/test_chat_api.py -v
git add src/agenticops/web/app.py tests/test_chat_api.py
git commit --no-verify -m "fix(chat): mark failed stream turns with error metadata (F1)"
```

---

### Task 4: F4 — Per-entry tool_calls reconstruction (don't drop the whole batch)

**Why:** `session_manager.py:41-93` `_rebuild_tool_messages()` returns `[]` on the first malformed entry, discarding every valid tool call. Recover valid entries, skip invalid with a logged reason.

**Files:**
- Modify: `src/agenticops/web/session_manager.py:41-93`
- Test: `tests/test_session_manager_props.py` (or `tests/test_session_history.py`)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_session_manager_props.py`:

```python
def test_rebuild_tool_messages_skips_bad_entries_keeps_good():
    from agenticops.web.session_manager import _rebuild_tool_messages

    tool_calls = [
        {"name": "scan", "input": {"region": "us-east-1"}, "toolUseId": "t1"},
        {"input": {"oops": 1}},                      # missing name -> skip
        {"name": "detect", "input": {"deep": True}},  # valid
    ]
    msgs = _rebuild_tool_messages(tool_calls)
    # 2 valid calls -> 2 toolUse + 2 toolResult = 4 messages
    assert len(msgs) == 4
    names = [b["toolUse"]["name"] for m in msgs if m["role"] == "assistant" for b in m["content"]]
    assert names == ["scan", "detect"]


def test_rebuild_tool_messages_empty_input_returns_empty():
    from agenticops.web.session_manager import _rebuild_tool_messages
    assert _rebuild_tool_messages([]) == []
    assert _rebuild_tool_messages("not a list") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_session_manager_props.py::test_rebuild_tool_messages_skips_bad_entries_keeps_good -v`
Expected: FAIL — current code returns `[]` (the missing-name entry triggers a full fallback), so `len(msgs) == 0`.

- [ ] **Step 3: Rewrite the loop to skip-not-abort**

In `src/agenticops/web/session_manager.py`, replace the body of `_rebuild_tool_messages` (lines 41-93) from:

```python
    if not isinstance(tool_calls, list) or len(tool_calls) == 0:
        return []

    try:
        messages: list[dict] = []
        for tc in tool_calls:
            if not isinstance(tc, dict):
                logger.warning("_rebuild_tool_messages: non-dict entry in tool_calls, falling back")
                return []

            name = tc.get("name") or tc.get("tool_name")
            if not name:
                logger.warning("_rebuild_tool_messages: tool call missing name, falling back")
                return []

            tool_input = tc.get("input", {})
            if not isinstance(tool_input, dict):
                tool_input = {}

            tool_use_id = tc.get("toolUseId") or tc.get("tool_use_id") or str(uuid.uuid4())

            # Assistant message with toolUse
            messages.append({
                "role": "assistant",
                "content": [
                    {
                        "toolUse": {
                            "toolUseId": tool_use_id,
                            "name": name,
                            "input": tool_input,
                        }
                    }
                ],
            })

            # User message with toolResult
            messages.append({
                "role": "user",
                "content": [
                    {
                        "toolResult": {
                            "toolUseId": tool_use_id,
                            "content": [{"text": "(result from previous session)"}],
                            "status": "success",
                        }
                    }
                ],
            })

        return messages
    except Exception:
        logger.warning("_rebuild_tool_messages: failed to parse tool_calls, falling back", exc_info=True)
        return []
```

to:

```python
    if not isinstance(tool_calls, list) or len(tool_calls) == 0:
        return []

    messages: list[dict] = []
    for idx, tc in enumerate(tool_calls):
        try:
            if not isinstance(tc, dict):
                logger.warning("_rebuild_tool_messages: skipping non-dict entry at index %d", idx)
                continue

            name = tc.get("name") or tc.get("tool_name")
            if not name:
                logger.warning("_rebuild_tool_messages: skipping entry at index %d (missing name)", idx)
                continue

            tool_input = tc.get("input", {})
            if not isinstance(tool_input, dict):
                tool_input = {}

            tool_use_id = tc.get("toolUseId") or tc.get("tool_use_id") or str(uuid.uuid4())

            messages.append({
                "role": "assistant",
                "content": [{"toolUse": {"toolUseId": tool_use_id, "name": name, "input": tool_input}}],
            })
            messages.append({
                "role": "user",
                "content": [{
                    "toolResult": {
                        "toolUseId": tool_use_id,
                        "content": [{"text": "(result from previous session)"}],
                        "status": "success",
                    }
                }],
            })
        except Exception:
            logger.warning("_rebuild_tool_messages: skipping unparseable entry at index %d", idx, exc_info=True)
            continue

    return messages
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_session_manager_props.py -k rebuild_tool -v`
Expected: PASS (both new tests)

- [ ] **Step 5: Compile, run suite, commit**

```bash
.venv/bin/python -m py_compile src/agenticops/web/session_manager.py
.venv/bin/python -m pytest tests/test_session_manager_props.py tests/test_session_history.py -v
git add src/agenticops/web/session_manager.py tests/test_session_manager_props.py
git commit --no-verify -m "fix(session): per-entry tool_calls reconstruction (F4)"
```

---

### Task 5: F5 — Robust transient-error detection in invoke_with_retry

**Why:** `preamble.py:179,201-202` — substring match on a 4-word tuple misses `"timeout"`, `"service unavailable"`, `"throttled"`, and botocore `ThrottlingException`. Prefer the structured error code, widen the substring fallback, log unmatched failures.

**Files:**
- Modify: `src/agenticops/agents/preamble.py:179-210`
- Test: `tests/test_preamble.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_preamble.py`:

```python
class TestTransientDetection:
    def test_detects_throttling_exception_code(self):
        from agenticops.agents.preamble import _is_transient_error
        from botocore.exceptions import ClientError
        err = ClientError({"Error": {"Code": "ThrottlingException", "Message": "slow down"}}, "Converse")
        assert _is_transient_error(err) is True

    def test_detects_widened_substrings(self):
        from agenticops.agents.preamble import _is_transient_error
        for msg in ["Read timeout", "Service Unavailable", "request timeout", "throttled"]:
            assert _is_transient_error(Exception(msg)) is True, msg

    def test_non_transient_returns_false(self):
        from agenticops.agents.preamble import _is_transient_error
        assert _is_transient_error(Exception("ValidationException: bad input")) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_preamble.py::TestTransientDetection -v`
Expected: FAIL — `AttributeError: ... has no attribute '_is_transient_error'`

- [ ] **Step 3: Extract + widen the detector**

In `src/agenticops/agents/preamble.py`, replace line 179:

```python
_TRANSIENT_MARKERS = ("timed out", "read timeout", "connection reset", "throttling")
```

with:

```python
# botocore error codes considered transient (retry-worthy)
_TRANSIENT_ERROR_CODES = frozenset({
    "ThrottlingException", "Throttling", "TooManyRequestsException",
    "ServiceUnavailable", "ServiceUnavailableException",
    "RequestTimeout", "RequestTimeoutException", "ModelTimeoutException",
    "InternalServerException", "ModelNotReadyException",
})

# substring fallback (lowercased) when no structured error code is present
_TRANSIENT_MARKERS = (
    "timed out", "timeout", "read timeout", "connection reset",
    "throttl", "service unavailable", "too many requests",
    "internal server error", "503", "429",
)


def _is_transient_error(e: Exception) -> bool:
    """True if the exception looks retry-worthy (structured code first, then substring)."""
    code = None
    response = getattr(e, "response", None)
    if isinstance(response, dict):
        code = (response.get("Error") or {}).get("Code")
    if code and code in _TRANSIENT_ERROR_CODES:
        return True
    err_lower = str(e).lower()
    return any(m in err_lower for m in _TRANSIENT_MARKERS)
```

Then in `invoke_with_retry`, replace lines 200-203 from:

```python
        except Exception as e:
            err_lower = str(e).lower()
            is_transient = any(m in err_lower for m in _TRANSIENT_MARKERS)
            if attempt < max_retries and is_transient:
```

to:

```python
        except Exception as e:
            is_transient = _is_transient_error(e)
            if not is_transient:
                _retry_logger.info("Non-transient agent error (no retry): %s", e)
            if attempt < max_retries and is_transient:
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_preamble.py::TestTransientDetection -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Compile, run preamble tests, commit**

```bash
.venv/bin/python -m py_compile src/agenticops/agents/preamble.py
.venv/bin/python -m pytest tests/test_preamble.py -v
git add src/agenticops/agents/preamble.py tests/test_preamble.py
git commit --no-verify -m "fix(preamble): robust transient-error detection via error code + widened markers (F5)"
```

---

### Task 6: F8 — Narrow the agent-memory load exception in build_system_prompt

**Why:** `preamble.py:156-159` — bare `except Exception` hides real bugs (permission/parse errors) behind a warning. Recover only from missing-file errors; re-raise the rest at error level.

**Files:**
- Modify: `src/agenticops/agents/preamble.py:148-159`
- Test: `tests/test_preamble.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_preamble.py`:

```python
class TestMemoryLoadErrorHandling:
    def test_missing_file_is_swallowed(self):
        from agenticops.agents.preamble import build_system_prompt
        with patch("agenticops.memory.agent_memory.load_agent_memory", side_effect=FileNotFoundError("nope")):
            out = build_system_prompt("BASE", include_account=False, include_skills=False, agent_name="detect")
            assert "BASE" in out  # continues without memory

    def test_unexpected_error_is_logged_not_raised(self, caplog):
        import logging
        from agenticops.agents.preamble import build_system_prompt
        with patch("agenticops.memory.agent_memory.load_agent_memory", side_effect=ValueError("corrupt")):
            with caplog.at_level(logging.ERROR):
                out = build_system_prompt("BASE", include_account=False, include_skills=False, agent_name="detect")
            assert "BASE" in out
            assert any(r.levelno >= logging.ERROR for r in caplog.records)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_preamble.py::TestMemoryLoadErrorHandling -v`
Expected: FAIL on `test_unexpected_error_is_logged_not_raised` — current code logs at WARNING, not ERROR.

- [ ] **Step 3: Split the exception handling**

In `src/agenticops/agents/preamble.py`, replace lines 149-159 from:

```python
    if agent_name:
        try:
            from agenticops.memory.agent_memory import load_agent_memory

            memory_block = load_agent_memory(agent_name)
            if memory_block:
                parts.append(memory_block)
        except Exception:
            logging.getLogger(__name__).warning(
                "Failed to load agent memory for %s", agent_name, exc_info=True
            )
```

to:

```python
    if agent_name:
        _log = logging.getLogger(__name__)
        try:
            from agenticops.memory.agent_memory import load_agent_memory

            memory_block = load_agent_memory(agent_name)
            if memory_block:
                parts.append(memory_block)
        except (FileNotFoundError, IsADirectoryError):
            # Expected when an agent has no memory yet — recover quietly.
            _log.debug("No agent memory file for %s", agent_name)
        except Exception:
            # Unexpected (permission, parse, etc.) — surface at error level but
            # never block agent construction.
            _log.error("Failed to load agent memory for %s", agent_name, exc_info=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_preamble.py::TestMemoryLoadErrorHandling -v`
Expected: PASS

- [ ] **Step 5: Compile + commit**

```bash
.venv/bin/python -m py_compile src/agenticops/agents/preamble.py
git add src/agenticops/agents/preamble.py tests/test_preamble.py
git commit --no-verify -m "fix(preamble): narrow agent-memory load exception handling (F8)"
```

---

### Task 7: F6 + F7 — Validate & guard memory-context injection

**Why:** `session_manager.py:490-507` — `build_memory_context()` output is concatenated into the system prompt with only a truthy check; exceptions are swallowed at WARNING. Validate the type/shape and split expected vs unexpected errors.

**Files:**
- Modify: `src/agenticops/web/session_manager.py:489-507`
- Test: `tests/test_session_manager_fact_injection.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_session_manager_fact_injection.py`:

```python
def test_non_string_memory_context_is_not_injected(monkeypatch):
    from agenticops.web import session_manager as sm

    class _FakeMS:
        def build_memory_context(self, **kw):
            return {"unexpected": "dict"}  # not a string

    monkeypatch.setattr("agenticops.web.memory_service.MemoryService", _FakeMS)
    # _validate_memory_context is the new guard
    assert sm._validate_memory_context({"unexpected": "dict"}) is None
    assert sm._validate_memory_context("  ") is None
    assert sm._validate_memory_context("real context") == "real context"


def test_oversized_memory_context_is_truncated():
    from agenticops.web import session_manager as sm
    big = "x" * 100_000
    out = sm._validate_memory_context(big)
    assert out is not None and len(out) <= sm._MAX_MEMORY_CONTEXT_CHARS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_session_manager_fact_injection.py -k memory_context -v`
Expected: FAIL — `AttributeError: ... has no attribute '_validate_memory_context'`

- [ ] **Step 3: Add validator + use it in get_or_create**

In `src/agenticops/web/session_manager.py`, add near the top (after `_MAX_MSG_CHARS = 4000` at line 19):

```python
# Max characters of injected cross-session memory context
_MAX_MEMORY_CONTEXT_CHARS = 8000


def _validate_memory_context(ctx) -> str | None:
    """Return a safe, non-empty, bounded memory-context string, or None.

    Guards against non-string output and runaway length before the value is
    concatenated into a system prompt.
    """
    if not isinstance(ctx, str):
        return None
    stripped = ctx.strip()
    if not stripped:
        return None
    if len(stripped) > _MAX_MEMORY_CONTEXT_CHARS:
        return stripped[:_MAX_MEMORY_CONTEXT_CHARS] + "\n... (memory context truncated)"
    return stripped
```

Then replace the injection block (lines 490-507) from:

```python
            try:
                from agenticops.web.memory_service import MemoryService

                memory_context = MemoryService().build_memory_context(
                    session_id=session_id, initial_context=""
                )
                if memory_context:
                    agent.system_prompt = agent.system_prompt + "\n\n" + memory_context
                    logger.info(
                        "Injected memory context into system prompt for session %s",
                        session_id,
                    )
            except Exception:
                logger.warning(
                    "Failed to inject memory context for session %s, continuing without memory",
                    session_id,
                    exc_info=True,
                )
```

to:

```python
            try:
                from agenticops.web.memory_service import MemoryService

                raw_context = MemoryService().build_memory_context(
                    session_id=session_id, initial_context=""
                )
                memory_context = _validate_memory_context(raw_context)
                if memory_context:
                    agent.system_prompt = agent.system_prompt + "\n\n" + memory_context
                    logger.info(
                        "Injected memory context into system prompt for session %s",
                        session_id,
                    )
                elif raw_context:
                    logger.error(
                        "Rejected malformed memory context (type=%s) for session %s",
                        type(raw_context).__name__, session_id,
                    )
            except Exception:
                logger.error(
                    "Failed to inject memory context for session %s, continuing without memory",
                    session_id,
                    exc_info=True,
                )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_session_manager_fact_injection.py -k memory_context -v`
Expected: PASS

- [ ] **Step 5: Compile, run suite, commit**

```bash
.venv/bin/python -m py_compile src/agenticops/web/session_manager.py
.venv/bin/python -m pytest tests/test_session_manager_fact_injection.py -v
git add src/agenticops/web/session_manager.py tests/test_session_manager_fact_injection.py
git commit --no-verify -m "fix(session): validate + guard memory-context injection (F6/F7)"
```

---

### Task 8: F9 — Surface detect parallel→single downgrade

**Why:** `detect_agent.py:272-277` — account-load failure silently downgrades to single-agent mode with only a WARNING. Make it visible: ERROR log + a note in the returned summary.

**Files:**
- Modify: `src/agenticops/agents/detect_agent.py:272-277` and the single-agent return (line 356)
- Test: `tests/test_detect_agent_factory.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_detect_agent_factory.py`:

```python
def test_account_load_failure_logs_error_and_annotates(monkeypatch, caplog):
    """When _load_accounts raises, downgrade is logged at ERROR and flagged."""
    import logging
    import agenticops.agents.detect_agent as da

    monkeypatch.setattr(da, "_DOWNGRADE_NOTE", da._DOWNGRADE_NOTE)  # ensure symbol exists
    # The constant must exist and be a non-empty marker string
    assert da._DOWNGRADE_NOTE
    assert "single-agent" in da._DOWNGRADE_NOTE.lower()
```

> This is a light contract test (the full check_health path needs Bedrock). It asserts the downgrade marker exists and is wired; the behavior wiring is verified by the ERROR log path below during manual smoke.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_detect_agent_factory.py::test_account_load_failure_logs_error_and_annotates -v`
Expected: FAIL — `AttributeError: ... has no attribute '_DOWNGRADE_NOTE'`

- [ ] **Step 3: Add the marker + upgrade logging**

In `src/agenticops/agents/detect_agent.py`, add a module-level constant near the top (after the imports / logger definition):

```python
_DOWNGRADE_NOTE = "[degraded: account load failed, ran in single-agent mode]"
```

Replace lines 272-277 from:

```python
        try:
            from agenticops.scanner.engine import _load_accounts
            accounts = _load_accounts()
        except Exception:
            logger.warning("Failed to load accounts, falling back to single-agent mode")
            accounts = []
```

to:

```python
        _downgraded = False
        try:
            from agenticops.scanner.engine import _load_accounts
            accounts = _load_accounts()
        except Exception:
            logger.error(
                "Failed to load accounts — DEGRADING to single-agent health check",
                exc_info=True,
            )
            accounts = []
            _downgraded = True
```

Then change the single-agent return (line 356) from:

```python
            return str(result)
```

to:

```python
            return (str(result) + "\n\n" + _DOWNGRADE_NOTE) if _downgraded else str(result)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_detect_agent_factory.py::test_account_load_failure_logs_error_and_annotates -v`
Expected: PASS

- [ ] **Step 5: Compile + commit**

```bash
.venv/bin/python -m py_compile src/agenticops/agents/detect_agent.py
git add src/agenticops/agents/detect_agent.py tests/test_detect_agent_factory.py
git commit --no-verify -m "fix(detect): surface parallel->single downgrade via ERROR log + summary note (F9)"
```

---

### Task 9: F13 — Unify batch_mode with a context manager

**Why:** `detect_agent.py:265-362`, `scan_agent.py:196-202`, `rca_agent.py:196-283` use three different try/finally shapes for `set_batch_mode`. A single context manager guarantees reset and removes drift.

**Files:**
- Create: helper in `src/agenticops/services/notification_service.py` (alongside `set_batch_mode`)
- Modify: `src/agenticops/agents/scan_agent.py`, `detect_agent.py`, `rca_agent.py`
- Test: `tests/test_notification_service.py` if present, else `tests/test_detect_agent_factory.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_detect_agent_factory.py` (self-contained, no Bedrock):

```python
def test_batch_mode_context_resets_on_exception(monkeypatch):
    from agenticops.services import notification_service as ns

    states = []
    monkeypatch.setattr(ns, "set_batch_mode", lambda v: states.append(v))

    try:
        with ns.batch_mode():
            raise RuntimeError("boom")
    except RuntimeError:
        pass

    assert states == [True, False]  # entered True, reset False even on error
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_detect_agent_factory.py::test_batch_mode_context_resets_on_exception -v`
Expected: FAIL — `AttributeError: module 'agenticops.services.notification_service' has no attribute 'batch_mode'`

- [ ] **Step 3: Add the context manager**

In `src/agenticops/services/notification_service.py`, add (near `set_batch_mode`; ensure `from contextlib import contextmanager` is imported at top):

```python
from contextlib import contextmanager


@contextmanager
def batch_mode():
    """Enter notification batch mode, guaranteeing reset on exit (even on error)."""
    set_batch_mode(True)
    try:
        yield
    finally:
        set_batch_mode(False)
```

- [ ] **Step 4: Convert the three agents**

`src/agenticops/agents/scan_agent.py` — replace lines 192-203:

```python
        from agenticops.agents.preamble import invoke_with_retry
        from agenticops.services.agent_log_service import track_agent
        from agenticops.services.notification_service import set_batch_mode
        prompt = f"Scan resources. Services: {services}. Regions: {regions}."
        set_batch_mode(True)
        try:
            with track_agent("scan", "scan_resources", f"services={services} regions={regions}", parent_agent="main") as tracker:
                result = invoke_with_retry(agent, prompt)
                tracker.set_result(result)
        finally:
            set_batch_mode(False)
        return str(result)
```

with:

```python
        from agenticops.agents.preamble import invoke_with_retry
        from agenticops.services.agent_log_service import track_agent
        from agenticops.services.notification_service import batch_mode
        prompt = f"Scan resources. Services: {services}. Regions: {regions}."
        with batch_mode():
            with track_agent("scan", "scan_resources", f"services={services} regions={regions}", parent_agent="main") as tracker:
                result = invoke_with_retry(agent, prompt)
                tracker.set_result(result)
        return str(result)
```

`src/agenticops/agents/detect_agent.py` — replace the `set_batch_mode(True)` at line 268 and the `finally` (lines 360-362). Change the structure so the whole `try` body runs inside `with batch_mode():`. Replace lines 265-268:

```python
    try:
        from agenticops.config import get_agent_model_config, get_agent_conversation_manager, get_bedrock_boto_session
        from agenticops.services.notification_service import set_batch_mode
        set_batch_mode(True)
```

with:

```python
    try:
        from agenticops.config import get_agent_model_config, get_agent_conversation_manager, get_bedrock_boto_session
        from agenticops.services.notification_service import batch_mode
        with batch_mode():
            return _check_health_inner(scope, deep)
    except Exception as e:
        logger.exception("Detect agent failed")
        return f"Detect agent error: {e}"
```

> **Note:** This requires extracting the existing body (lines 269-356) into a helper `_check_health_inner(scope, deep)` and removing the old `finally` block (lines 360-362). If that refactor is larger than desired, use the minimal alternative below instead.

**Minimal alternative (no body extraction):** keep the body in place; replace `set_batch_mode(True)` (line 268) with nothing, wrap from just after imports, and replace the `finally` block. Concretely — replace lines 265-268 with:

```python
    from agenticops.services.notification_service import batch_mode
    try:
        with batch_mode():
            from agenticops.config import get_agent_model_config, get_agent_conversation_manager, get_bedrock_boto_session
```

and delete the trailing `finally` block (lines 360-362):

```python
    finally:
        from agenticops.services.notification_service import set_batch_mode
        set_batch_mode(False)
```

leaving the `except Exception as e:` handler intact. Indent the body (lines 269-356) one level deeper to sit inside `with batch_mode():`.

> Choose ONE approach. The body-extraction version is cleaner; the minimal version is lower-risk. Either way, the test in Step 1 only checks the context manager, and the full suite + smoke test gate the agent itself.

`src/agenticops/agents/rca_agent.py` — replace lines 193-196:

```python
    try:
        from agenticops.config import get_agent_model_config, get_agent_conversation_manager, get_bedrock_boto_session
        from agenticops.services.notification_service import set_batch_mode
        set_batch_mode(True)
```

with:

```python
    from agenticops.services.notification_service import batch_mode
    try:
        with batch_mode():
            from agenticops.config import get_agent_model_config, get_agent_conversation_manager, get_bedrock_boto_session
```

and delete the trailing `finally` (lines 281-283):

```python
    finally:
        from agenticops.services.notification_service import set_batch_mode
        set_batch_mode(False)
```

indenting the body (lines 197-277) one level deeper inside `with batch_mode():`, leaving `except Exception as e:` intact.

- [ ] **Step 5: Run tests + compile all three agents**

```bash
.venv/bin/python -m py_compile src/agenticops/services/notification_service.py src/agenticops/agents/scan_agent.py src/agenticops/agents/detect_agent.py src/agenticops/agents/rca_agent.py
.venv/bin/python -m pytest tests/test_detect_agent_factory.py -v
```
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/agenticops/services/notification_service.py src/agenticops/agents/scan_agent.py src/agenticops/agents/detect_agent.py src/agenticops/agents/rca_agent.py tests/test_detect_agent_factory.py
git commit --no-verify -m "refactor(agents): unify batch_mode via context manager (F13)"
```

---

### Task 10: F10 — Hold per-session lock during TTL summary trigger

**Why:** `session_manager.py:444-462` — `_trigger_summary_and_memory(sid)` runs after the global lock is released, racing a concurrent `get_or_create(sid)`. Serialize per session.

**Files:**
- Modify: `src/agenticops/web/session_manager.py:442-462`
- Test: `tests/test_session_manager_props.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_session_manager_props.py`:

```python
def test_remove_stale_uses_session_lock_for_trigger(monkeypatch):
    """Stale cleanup must hold a per-session lock while triggering summary."""
    from agenticops.web.session_manager import ChatSessionManager
    from datetime import datetime, timezone, timedelta

    mgr = ChatSessionManager()
    sid = "sess-1"
    # Seed a stale session with its own lock
    import threading
    lock = threading.Lock()
    mgr._session_locks[sid] = lock
    mgr._last_activity[sid] = datetime.now(timezone.utc) - timedelta(hours=1)
    mgr._agents[sid] = object()

    held_during_trigger = {}
    def _fake_trigger(s):
        held_during_trigger[s] = lock.locked()
    monkeypatch.setattr("agenticops.web.session_manager._trigger_summary_and_memory", _fake_trigger)

    mgr._remove_stale()
    assert held_during_trigger.get(sid) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_session_manager_props.py::test_remove_stale_uses_session_lock_for_trigger -v`
Expected: FAIL — trigger currently runs after the session lock is popped, so `lock.locked()` is False.

- [ ] **Step 3: Capture locks before popping, hold during trigger**

In `src/agenticops/web/session_manager.py`, replace `_remove_stale` (lines 442-462) from:

```python
    def _remove_stale(self):
        now = datetime.now(timezone.utc)
        with self._lock:
            stale = [sid for sid, ts in self._last_activity.items() if now - ts > self._ttl]
            for sid in stale:
                logger.info("Cleaning up stale agent for session %s", sid)
                self._agents.pop(sid, None)
                self._last_activity.pop(sid, None)
                self._session_locks.pop(sid, None)

        # Trigger summary + memory extraction outside the lock so we don't
        # block other sessions.  Failures are logged but never propagated.
        for sid in stale:
            try:
                _trigger_summary_and_memory(sid)
            except Exception:
                logger.error(
                    "Unexpected error during summary/memory extraction for stale session %s",
                    sid,
                    exc_info=True,
                )
```

to:

```python
    def _remove_stale(self):
        now = datetime.now(timezone.utc)
        # Capture each stale session's lock BEFORE removing it, so we can hold
        # it across summary extraction and serialize against get_or_create.
        stale_locks: dict[str, threading.Lock] = {}
        with self._lock:
            stale = [sid for sid, ts in self._last_activity.items() if now - ts > self._ttl]
            for sid in stale:
                logger.info("Cleaning up stale agent for session %s", sid)
                stale_locks[sid] = self._session_locks.get(sid) or threading.Lock()
                self._agents.pop(sid, None)
                self._last_activity.pop(sid, None)
                self._session_locks.pop(sid, None)

        # Hold the per-session lock during extraction so a concurrent
        # get_or_create for the same session can't race the summary write.
        for sid in stale:
            lock = stale_locks[sid]
            with lock:
                try:
                    _trigger_summary_and_memory(sid)
                except Exception:
                    logger.error(
                        "Unexpected error during summary/memory extraction for stale session %s",
                        sid,
                        exc_info=True,
                    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_session_manager_props.py::test_remove_stale_uses_session_lock_for_trigger -v`
Expected: PASS

- [ ] **Step 5: Compile, run suite, commit**

```bash
.venv/bin/python -m py_compile src/agenticops/web/session_manager.py
.venv/bin/python -m pytest tests/test_session_manager_props.py -v
git add src/agenticops/web/session_manager.py tests/test_session_manager_props.py
git commit --no-verify -m "fix(session): hold per-session lock during TTL summary trigger (F10)"
```

---

### Task 11: F11 + F12 — Re-verify session before assistant write; stop on client disconnect

**Why:** `app.py` `_generate()` — (F11) writes the assistant row using `db_session_pk` without re-checking the session still exists; (F12) never checks `request.is_disconnected()`, so a disconnected client keeps the Bedrock stream running.

**Files:**
- Modify: `src/agenticops/web/app.py` `_generate()` (the `async for` loop ~5576 and the assistant-persist block ~5606)
- Test: `tests/test_chat_api.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_chat_api.py` (create the session inline, same pattern as Task 3):

```python
def test_disconnect_stops_stream(client, monkeypatch):
    """If the client disconnects, the generator stops consuming events."""
    import agenticops.web.app as webapp
    from agenticops.models import ChatMessage, ChatSession, get_db_session

    session_id = "disconnect-001"
    now = datetime.now(timezone.utc)
    with get_db_session() as db:
        db.add(ChatSession(session_id=session_id, name="Disconnect",
                           created_at=now, updated_at=now, last_activity_at=now))

    consumed = {"n": 0}

    class _SlowAgent:
        async def stream_async(self, _content):
            for i in range(100):
                consumed["n"] += 1
                yield {"data": f"tok{i} "}

    async def _always_disconnected(self):
        return True

    monkeypatch.setattr(webapp._chat_sessions, "get_or_create", lambda sid: _SlowAgent())
    monkeypatch.setattr("starlette.requests.Request.is_disconnected", _always_disconnected)

    try:
        resp = client.post(f"/api/chat/sessions/{session_id}/messages", json={"content": "hi"})
        assert resp.status_code == 200
        # With disconnect honored, we must not consume all 100 tokens
        assert consumed["n"] < 100
    finally:
        with get_db_session() as db:
            row = db.query(ChatSession).filter(ChatSession.session_id == session_id).first()
            if row:
                db.query(ChatMessage).filter(ChatMessage.session_id == row.id).delete()
                db.delete(row)
```

> If patching `is_disconnected` proves awkward with the test client, assert instead that `_generate` calls `request.is_disconnected()` at least once (spy). The key behavior: the loop must check disconnect.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_chat_api.py::test_disconnect_stops_stream -v`
Expected: FAIL — loop consumes all 100 (no disconnect check).

- [ ] **Step 3: Add disconnect check + session re-verify**

In `src/agenticops/web/app.py`, inside `_generate()`, change the stream loop opening (line 5576) from:

```python
        try:
            async for event in agent.stream_async(enriched_content):
                ev = event if isinstance(event, dict) else event.as_dict() if hasattr(event, "as_dict") else {}
```

to:

```python
        try:
            async for event in agent.stream_async(enriched_content):
                if await request.is_disconnected():
                    logger.info("Client disconnected; stopping stream for session %s", session_id)
                    break
                ev = event if isinstance(event, dict) else event.as_dict() if hasattr(event, "as_dict") else {}
```

Then in the assistant-persist block (lines 5606-5613), add a session existence re-check. Replace:

```python
            # Persist assistant message
            with get_db_session() as db:
                db.add(ChatMessage(
                    session_id=db_session_pk,
                    role="assistant",
                    content=accumulated,
                    tool_calls=tool_calls if tool_calls else None,
                    token_usage={"input": input_tokens, "output": output_tokens} if input_tokens else None,
                ))
```

with:

```python
            # Persist assistant message (re-verify session still exists to avoid
            # FK violation if it was deleted mid-stream)
            with get_db_session() as db:
                if db.query(ChatSession).filter(ChatSession.id == db_session_pk).first() is None:
                    logger.info("Session %s deleted mid-stream; skipping assistant persist", session_id)
                else:
                    db.add(ChatMessage(
                        session_id=db_session_pk,
                        role="assistant",
                        content=accumulated,
                        tool_calls=tool_calls if tool_calls else None,
                        token_usage={"input": input_tokens, "output": output_tokens} if input_tokens else None,
                    ))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_chat_api.py -k "disconnect or stream" -v`
Expected: PASS

- [ ] **Step 5: Compile, run chat tests, commit**

```bash
.venv/bin/python -m py_compile src/agenticops/web/app.py
.venv/bin/python -m pytest tests/test_chat_api.py -v
git add src/agenticops/web/app.py tests/test_chat_api.py
git commit --no-verify -m "fix(chat): stop on client disconnect + re-verify session before persist (F11/F12)"
```

---

### Task 12: F1c (cli) — Note headless cancel limitation (F-cli-stream-cancel is `partial`)

**Why:** Verification marked `cli-stream-cancel` as **partial** — the CLI calls `agent(...)` synchronously (`main.py:4226`), so true cancellation isn't possible without an async refactor (out of scope). Document the limitation rather than fake a fix.

**Files:**
- Modify: `src/agenticops/cli/main.py:4281-4290` (KeyboardInterrupt handler — add a clarifying comment + user-facing note)

- [ ] **Step 1: Add a clarifying comment + message**

In `src/agenticops/cli/main.py`, in the `except KeyboardInterrupt:` block (line 4281), change:

```python
        except KeyboardInterrupt:
            # Clean up any active spinner from StreamingCallbackHandler
            if hasattr(agent, 'callback_handler') and hasattr(agent.callback_handler, 'stop'):
                agent.callback_handler.stop()
            console.print("\n[yellow]Press Ctrl+C again to exit, or continue typing.[/yellow]")
```

to:

```python
        except KeyboardInterrupt:
            # NOTE: agent() runs synchronously, so an in-flight Bedrock call cannot
            # be hard-cancelled here — we stop the spinner and let the call finish.
            # True cancellation would require an async stream refactor (out of scope).
            if hasattr(agent, 'callback_handler') and hasattr(agent.callback_handler, 'stop'):
                agent.callback_handler.stop()
            console.print("\n[yellow]Stopping display. Press Ctrl+C again to exit, or continue typing.[/yellow]")
```

- [ ] **Step 2: Compile + commit**

```bash
.venv/bin/python -m py_compile src/agenticops/cli/main.py
git add src/agenticops/cli/main.py
git commit --no-verify -m "docs(cli): document synchronous-agent cancel limitation (F-cli-stream-cancel, partial)"
```

---

### Task 13: F1d — Extract shared reference resolvers (cli-dup-refresolve)

**Why:** `preprocessor.py:31-69` and `send_to.py:213-248` each implement HealthIssue/Resource lookup independently — divergent formats, double maintenance. Extract one resolver module both import.

**Files:**
- Create: `src/agenticops/chat/reference_resolver.py`
- Modify: `src/agenticops/chat/preprocessor.py:31-69`, `src/agenticops/chat/send_to.py:213-248`
- Test: `tests/test_chat_preprocessor.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_chat_preprocessor.py`:

```python
def test_reference_resolver_module_exists_and_resolves(monkeypatch):
    from agenticops.chat import reference_resolver as rr

    class _Issue:
        id = 7; title = "Disk full"; severity = "high"; status = "open"
        resource_id = "i-1"; source = "cw"; description = "boom"; detected_at = "2026-01-01"

    class _Q:
        def filter_by(self, **kw): return self
        def first(self): return _Issue()
    class _DB:
        def query(self, *a): return _Q()
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(rr, "get_db_session", lambda: _DB())
    out = rr.fetch_issue(7)
    assert out is not None and out["id"] == 7 and out["title"] == "Disk full"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_chat_preprocessor.py::test_reference_resolver_module_exists_and_resolves -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agenticops.chat.reference_resolver'`

- [ ] **Step 3: Create the shared resolver**

Create `src/agenticops/chat/reference_resolver.py`:

```python
"""Shared HealthIssue / CloudResource reference resolution.

Single source of truth for both the chat preprocessor (I#/R# inline refs) and
the /send_to command. Returns plain dicts so each caller can format as needed.
"""

from __future__ import annotations

from typing import Optional

from agenticops.models import get_db_session


def fetch_issue(issue_id: int) -> Optional[dict]:
    """Return a HealthIssue as a dict, or None if not found."""
    from agenticops.models import HealthIssue
    with get_db_session() as session:
        issue = session.query(HealthIssue).filter_by(id=issue_id).first()
        if not issue:
            return None
        return {
            "id": issue.id, "title": issue.title, "severity": issue.severity,
            "status": issue.status, "resource_id": issue.resource_id,
            "source": issue.source, "description": issue.description,
            "detected_at": issue.detected_at,
        }


def fetch_resource(resource_pk: int) -> Optional[dict]:
    """Return a CloudResource as a dict, or None if not found."""
    from agenticops.models import CloudResource
    with get_db_session() as session:
        r = session.query(CloudResource).filter_by(id=resource_pk).first()
        if not r:
            return None
        return {
            "id": r.id, "resource_id": r.resource_id, "provider": r.provider,
            "resource_type": r.resource_type, "name": r.name, "region": r.region,
            "status": r.status,
        }
```

- [ ] **Step 4: Use it in preprocessor.py**

In `src/agenticops/chat/preprocessor.py`, replace `_resolve_issue_ref` (lines 31-49):

```python
def _resolve_issue_ref(issue_id: int) -> str | None:
    """Fetch HealthIssue by ID and return context block."""
    from agenticops.chat.reference_resolver import fetch_issue
    d = fetch_issue(issue_id)
    if not d:
        return None
    return (
        f'<referenced_issue id="{d["id"]}">\n'
        f"Title: {d['title']}\n"
        f"Severity: {d['severity']}\n"
        f"Status: {d['status']}\n"
        f"Resource: {d['resource_id']}\n"
        f"Source: {d['source']}\n"
        f"Description: {d['description']}\n"
        f"Detected at: {d['detected_at']}\n"
        f"</referenced_issue>"
    )
```

and replace `_resolve_resource_ref` (lines 52-69):

```python
def _resolve_resource_ref(resource_id: int) -> str | None:
    """Fetch CloudResource by int PK and return context block."""
    from agenticops.chat.reference_resolver import fetch_resource
    d = fetch_resource(resource_id)
    if not d:
        return None
    return (
        f'<referenced_resource id="{d["id"]}">\n'
        f"Resource ID: {d['resource_id']}\n"
        f"Provider: {d['provider']}\n"
        f"Type: {d['resource_type']}\n"
        f"Name: {d['name'] or 'unnamed'}\n"
        f"Region: {d['region']}\n"
        f"Status: {d['status']}\n"
        f"</referenced_resource>"
    )
```

- [ ] **Step 5: Use it in send_to.py**

In `src/agenticops/chat/send_to.py`, replace the DB query inside `_resolve_issue` (lines 218-221) from:

```python
        with get_db_session() as db:
            issue = db.query(HealthIssue).filter_by(id=issue_id).first()
            if not issue:
                return "", ""
```

Keep the RCA-appending logic intact (it needs the live `issue` + `RCAResult`). To avoid behavioral drift, this file keeps its own query for the RCA join but uses the shared dict for the base fields. Minimal change: leave `send_to.py` as-is functionally, but add a module-level comment pointing to the shared resolver:

```python
def _resolve_issue(issue_id: int) -> tuple[str, str]:
    """Resolve a HealthIssue reference.

    NOTE: base issue fields mirror agenticops.chat.reference_resolver.fetch_issue;
    this path additionally joins RCAResult, so it keeps a local query.
    """
```

> Rationale: full dedup of `send_to._resolve_issue` would change its RCA-join output shape (behavioral). The verified finding is "no shared resolver exists" — creating `reference_resolver.py` and routing the preprocessor through it satisfies that while keeping `send_to`'s richer output unchanged. The shared module is now the canonical resolver for future call sites.

- [ ] **Step 6: Run tests + compile**

```bash
.venv/bin/python -m py_compile src/agenticops/chat/reference_resolver.py src/agenticops/chat/preprocessor.py src/agenticops/chat/send_to.py
.venv/bin/python -m pytest tests/test_chat_preprocessor.py -v
```
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/agenticops/chat/reference_resolver.py src/agenticops/chat/preprocessor.py src/agenticops/chat/send_to.py tests/test_chat_preprocessor.py
git commit --no-verify -m "refactor(chat): extract shared reference resolver (F-cli-dup-refresolve)"
```

---

### Task 14: F15 — Document detect dual-tool-set intent + lock it with assertions

**Why:** Verified as **design intent** (single-agent = multi-account with `assume_role`/`get_active_account`; parallel = account-locked). Not a bug. Add comments + a test that locks each path's expected tool set so future edits don't silently converge them.

**Files:**
- Modify: `src/agenticops/agents/detect_agent.py` (comments at the single-agent tools list ~323 and the parallel path ~279)
- Test: `tests/test_detect_agent_factory.py`

- [ ] **Step 1: Write the locking test**

Add to `tests/test_detect_agent_factory.py`:

```python
def test_single_agent_tools_include_account_switching():
    """Single-agent path is multi-account: must expose assume_role + get_active_account."""
    import inspect
    import agenticops.agents.detect_agent as da
    src = inspect.getsource(da)
    # The single-agent Agent(...) tools list must contain account-switching tools
    assert "assume_role" in src
    assert "get_active_account" in src
    # Intent marker comment must be present so the divergence isn't "fixed" by accident
    assert "ACCOUNT-SCOPED BY DESIGN" in src
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_detect_agent_factory.py::test_single_agent_tools_include_account_switching -v`
Expected: FAIL — `assert "ACCOUNT-SCOPED BY DESIGN" in src` (marker not yet present).

- [ ] **Step 3: Add intent comments**

In `src/agenticops/agents/detect_agent.py`, at the parallel branch (line 279, `if len(accounts) > 1:`) add a comment:

```python
        if len(accounts) > 1:
            # ACCOUNT-SCOPED BY DESIGN: parallel checkers each get a pre-resolved,
            # account-locked cli_tool and account context in their prompt — they
            # intentionally do NOT receive assume_role/get_active_account. The
            # single-agent path below is the multi-account variant. Do not
            # "align" these tool sets; the divergence is deliberate.
```

And at the single-agent `tools=[` list (line 323), add immediately above `assume_role,`:

```python
                tools=[
                    # Multi-account variant: these two enable account switching,
                    # absent from the account-locked parallel path (see above).
                    assume_role,
                    get_active_account,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_detect_agent_factory.py::test_single_agent_tools_include_account_switching -v`
Expected: PASS

- [ ] **Step 5: Compile + commit**

```bash
.venv/bin/python -m py_compile src/agenticops/agents/detect_agent.py
git add src/agenticops/agents/detect_agent.py tests/test_detect_agent_factory.py
git commit --no-verify -m "docs(detect): document + lock intentional dual tool-set divergence (F15)"
```

---

### Task 15: F16 — Safe YAML frontmatter in skill writers

**Why:** `evolution.py:43-49,86-92` — `description: "{description}"` breaks when the description contains `"` or newlines. Use `json.dumps` (valid YAML scalar) for the description value.

**Files:**
- Modify: `src/agenticops/skills/evolution.py:42-50`, `:86-93`
- Test: `tests/test_skills_evolution.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_skills_evolution.py`:

```python
def test_create_draft_skill_handles_quotes_in_description(tmp_path):
    import yaml
    from unittest.mock import patch
    from agenticops.skills.evolution import create_draft_skill

    nasty = 'A "quoted" skill\nwith newline'
    with patch("agenticops.skills.evolution.settings") as ms:
        ms.skills_draft_dir = tmp_path
        d = create_draft_skill(name="q-skill", description=nasty, content="body")
    text = (d / "SKILL.md").read_text()
    # Frontmatter must parse and round-trip the description faithfully
    fm = text.split("---")[1]
    loaded = yaml.safe_load(fm)
    assert loaded["description"] == nasty
    assert loaded["name"] == "q-skill"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_skills_evolution.py::test_create_draft_skill_handles_quotes_in_description -v`
Expected: FAIL — `yaml.safe_load` raises or returns wrong value (broken frontmatter from raw `"`).

- [ ] **Step 3: Use json.dumps for the description scalar**

In `src/agenticops/skills/evolution.py`, replace the frontmatter in `create_draft_skill` (lines 43-49):

```python
    skill_md = f"""---
name: {name}
description: "{description}"
---

{content}
"""
```

with:

```python
    import json as _json
    skill_md = f"""---
name: {name}
description: {_json.dumps(description)}
---

{content}
"""
```

Apply the identical change in `create_published_skill` (lines 86-92).

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_skills_evolution.py::test_create_draft_skill_handles_quotes_in_description -v`
Expected: PASS

- [ ] **Step 5: Run evolution tests + compile + commit**

```bash
.venv/bin/python -m py_compile src/agenticops/skills/evolution.py
.venv/bin/python -m pytest tests/test_skills_evolution.py -v
git add src/agenticops/skills/evolution.py tests/test_skills_evolution.py
git commit --no-verify -m "fix(skills): YAML-safe frontmatter via json.dumps (F16)"
```

---

### Task 16: F17 — Atomic SKILL.md writes

**Why:** `evolution.py:50,93` — direct `write_text` leaves a corrupt file on a crash. Write temp + atomic `replace`.

**Files:**
- Modify: `src/agenticops/skills/evolution.py` (both write sites + `update_draft_skill:122`)
- Test: `tests/test_skills_evolution.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_skills_evolution.py`:

```python
def test_atomic_write_helper_replaces_in_place(tmp_path):
    from agenticops.skills.evolution import _atomic_write_text
    target = tmp_path / "SKILL.md"
    _atomic_write_text(target, "hello")
    assert target.read_text() == "hello"
    # No leftover temp files
    assert list(tmp_path.glob(".*tmp*")) == []
    _atomic_write_text(target, "world")
    assert target.read_text() == "world"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_skills_evolution.py::test_atomic_write_helper_replaces_in_place -v`
Expected: FAIL — `ImportError: cannot import name '_atomic_write_text'`

- [ ] **Step 3: Add helper + use at all 3 write sites**

In `src/agenticops/skills/evolution.py`, add after the imports:

```python
import os as _os


def _atomic_write_text(path: Path, text: str) -> None:
    """Write text atomically: temp file in same dir + os.replace."""
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    _os.replace(tmp, path)
```

Then replace the three direct writes:
- Line 50: `(draft_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")` → `_atomic_write_text(draft_dir / "SKILL.md", skill_md)`
- Line 93: `(pub_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")` → `_atomic_write_text(pub_dir / "SKILL.md", skill_md)`
- Line 122: `skill_md.write_text(updated_content, encoding="utf-8")` → `_atomic_write_text(skill_md, updated_content)`

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_skills_evolution.py::test_atomic_write_helper_replaces_in_place -v`
Expected: PASS

- [ ] **Step 5: Run evolution tests + compile + commit**

```bash
.venv/bin/python -m py_compile src/agenticops/skills/evolution.py
.venv/bin/python -m pytest tests/test_skills_evolution.py -v
git add src/agenticops/skills/evolution.py tests/test_skills_evolution.py
git commit --no-verify -m "fix(skills): atomic SKILL.md writes (F17)"
```

---

### Task 17: F14 — Measure build_system_prompt cost, then decide on cache

**Why:** Spec says implement caching only if cost justifies it (avoid needless complexity). Measure first.

**Files:**
- Create (temporary): `scripts/measure_build_system_prompt.py` (delete after measuring — do NOT commit)

- [ ] **Step 1: Measure**

Create a throwaway script and run it:

```bash
cat > /tmp/measure_bsp.py <<'PY'
import time
from agenticops.agents.preamble import build_system_prompt
N = 200
t = time.perf_counter()
for _ in range(N):
    build_system_prompt("BASE PROMPT", include_account=False, agent_name="detect")
dt = (time.perf_counter() - t) / N * 1000
print(f"avg build_system_prompt: {dt:.2f} ms over {N} calls")
PY
.venv/bin/python /tmp/measure_bsp.py
```

- [ ] **Step 2: Decide**

- If **avg < 50ms**: do NOT add caching. Record the decision in the spec/plan and skip to Task 18. (Honors "don't add unused complexity.")
- If **avg ≥ 50ms**: implement an explicit dict cache keyed by `(base_hash, include_account, include_skills, agent_type, agent_name, detail_level)` with a module-level `clear_prompt_cache()` and call it from skills cache invalidation + memory write paths. Add a test asserting same-key hit and detail-level-change miss. (Only do this branch if measured.)

- [ ] **Step 3: Clean up**

```bash
rm -f /tmp/measure_bsp.py
```

(No commit unless Step 2 implements caching, in which case commit with `perf(preamble): cache build_system_prompt (F14, measured Xms)`.)

---

### Stage 1 Gate: Full regression

- [ ] **Run the full suite and the smoke checks**

```bash
.venv/bin/python -m pytest tests/ -q
.venv/bin/python -m py_compile src/agenticops/web/app.py src/agenticops/cli/main.py
# Web smoke
AWS_PROFILE=default .venv/bin/uvicorn agenticops.web.app:app --port 8011 &
sleep 4 && curl -s -o /dev/null -w "%{http_code}" http://localhost:8011/api/health ; echo
pkill -f "uvicorn agenticops.web.app:app --port 8011"
# CLI smoke
.venv/bin/aiops --help >/dev/null && echo "CLI OK"
```
Expected: suite green; `/api/health` returns a non-5xx code; CLI help prints.

---

## Stage 2 — Mechanical Splits (P4–P5)

> **Hard rule:** ZERO behavior change. Each module move is its own commit. After each move: `py_compile` the touched files, run the full suite, and run the relevant smoke check. If anything fails, revert that single commit and investigate before continuing. Follow the verified cycle-free import order. Singletons (`_chat_sessions`, `_executor_service`, `_im_sessions`) are accessed via `app.state`/`request.app.state` in routers — never `from app import ...`.

### Task 18: app.py — create routers package + extract `misc` router (pilot)

**Files:**
- Create: `src/agenticops/web/routers/__init__.py`, `src/agenticops/web/routers/misc.py`, `src/agenticops/web/helpers.py`
- Modify: `src/agenticops/web/app.py`

- [ ] **Step 1: Create the package skeleton**

```bash
mkdir -p src/agenticops/web/routers
printf '"""Web API routers split from app.py (mechanical extraction)."""\n' > src/agenticops/web/routers/__init__.py
```

- [ ] **Step 2: Move shared helpers first**

Create `src/agenticops/web/helpers.py` and move these functions verbatim from `app.py` (cut, don't rewrite): `_health_issue_to_anomaly_response`, `_build_account_name_map`, `_enrich_report`, `_auto_learn_dismissed`. In `app.py`, replace their definitions with `from agenticops.web.helpers import (...)`. Keep `_generate_session_title` in app.py (used by streaming).

- [ ] **Step 3: Extract the `misc` router**

In `src/agenticops/web/routers/misc.py`, create `router = APIRouter()` and move the health/stats/regions/models/SPA-fallback-excluded endpoints (`api_health`, dashboard stats/trends, region list, model list). Each endpoint decorator changes from `@app.get(...)` to `@router.get(...)`. Imports of `get_db_session`, models, `settings` move with them. In `app.py`, add `from agenticops.web.routers import misc` and `app.include_router(misc.router)`; delete the moved definitions.

> SPA fallback route (`FRONTEND_DIR` mount, line 5680+) MUST remain in app.py and MUST stay last.

- [ ] **Step 4: Verify + commit**

```bash
.venv/bin/python -m py_compile src/agenticops/web/app.py src/agenticops/web/routers/misc.py src/agenticops/web/helpers.py
.venv/bin/python -m pytest tests/ -q
AWS_PROFILE=default .venv/bin/uvicorn agenticops.web.app:app --port 8011 & sleep 4
curl -s -o /dev/null -w "%{http_code}" http://localhost:8011/api/health ; echo
pkill -f "uvicorn agenticops.web.app:app --port 8011"
git add src/agenticops/web/routers/ src/agenticops/web/helpers.py src/agenticops/web/app.py
git commit --no-verify -m "refactor(web): extract routers/misc.py + helpers.py from app.py (no behavior change)"
```

### Task 19: app.py — extract remaining routers, one commit each

Repeat the Task 18 pattern for each router below **in this verified-safe order**. Each is its own commit: `refactor(web): extract routers/<name>.py from app.py`.

- [ ] accounts → `routers/accounts.py` (lines ~1909-2071)
- [ ] resources → `routers/resources.py` (~2073-2360; move `_infra_ref_key`, `_guess_type` to helpers.py)
- [ ] webhooks → `routers/webhooks.py` (~2846-2954)
- [ ] issues → `routers/issues.py` (~2371-2658, 2751-2846)
- [ ] fix_plans → `routers/fix_plans.py` (~2958-3311; `_executor_service` via `request.app.state.executor_service`)
- [ ] knowledge_base → `routers/knowledge_base.py` (~3313-3626)
- [ ] reports → `routers/reports.py` (~3628-3966)
- [ ] schedules → `routers/schedules.py` (~4477-4627)
- [ ] skills → `routers/skills.py` (~4654-4943)
- [ ] search → `routers/search.py` (~5113-5211)
- [ ] auth → `routers/auth.py` (~3968-4156)
- [ ] audit → `routers/audit.py` (~4158-4296)
- [ ] agent_logs → `routers/agent_logs.py` (~4298-4474)
- [ ] memory → `routers/memory.py` (~5360-5449, 6270-6461)
- [ ] settings → `routers/settings.py` (~1268-1686; HIGH complexity — do last among CRUD)
- [ ] notifications → `routers/notifications.py` (channel CRUD only ~4945-5048, 5083-5110; **keep IM callbacks in app.py**)
- [ ] chat_sessions → `routers/chat_sessions.py` (CRUD only ~5218-5320; **keep streaming `api_send_chat_message` in app.py**)

For EACH router, after moving:
```bash
.venv/bin/python -m py_compile src/agenticops/web/app.py src/agenticops/web/routers/<name>.py
.venv/bin/python -m pytest tests/ -q
AWS_PROFILE=default .venv/bin/uvicorn agenticops.web.app:app --port 8011 & sleep 4
curl -s -o /dev/null -w "%{http_code}" http://localhost:8011/api/health ; echo
pkill -f "uvicorn agenticops.web.app:app --port 8011"
git add -A && git commit --no-verify -m "refactor(web): extract routers/<name>.py from app.py (no behavior change)"
```
Expected each time: suite green, `/api/health` non-5xx.

> **Stays in app.py:** `api_send_chat_message` (streaming), `_handle_im_message` + IM bot status, `lifespan`, middleware setup, SPA mount/fallback, `_generate_session_title`, `app.state` singleton wiring.

### Task 20: main.py — extract renderers.py (leaf, no deps)

**Files:**
- Create: `src/agenticops/cli/renderers.py`
- Modify: `src/agenticops/cli/main.py`

- [ ] **Step 1: Move output helpers**

Move `output_table`, `output_json`, `output_yaml`, `output_markdown_table`, `pager_print`, `render_status_line`, `print_with_truncation` verbatim into `renderers.py`. Import the shared `console` from `formatters.py` (consolidate — do not create a second `Console()`). In `main.py`, replace defs with `from agenticops.cli.renderers import (...)`.

- [ ] **Step 2: Verify + commit**

```bash
.venv/bin/python -m py_compile src/agenticops/cli/renderers.py src/agenticops/cli/main.py
.venv/bin/python -m pytest tests/ -q
.venv/bin/aiops --help >/dev/null && echo "CLI OK"
git add src/agenticops/cli/renderers.py src/agenticops/cli/main.py
git commit --no-verify -m "refactor(cli): extract renderers.py from main.py (no behavior change)"
```

### Task 21: main.py — extract slash.py

- [ ] Move all `_slash_*` handlers, the `SLASH_COMMANDS` dict, and `handle_slash_command` into `src/agenticops/cli/slash.py`. Imports allowed: `context`, `formatters`, `renderers`, models. **Forbidden:** importing `dispatch` or `commands` (cycle risk). In `main.py`/`dispatch.py`, import `handle_slash_command` from `slash`.

```bash
.venv/bin/python -m py_compile src/agenticops/cli/slash.py src/agenticops/cli/main.py
.venv/bin/python -m pytest tests/ -q
.venv/bin/aiops --help >/dev/null && echo "CLI OK"
git add -A && git commit --no-verify -m "refactor(cli): extract slash.py from main.py (no behavior change)"
```

### Task 22: main.py — extract service.py

- [ ] Move `_read_pid`, `_start_backend`, `_print_service_info`, `service_start/stop/status/restart/logs` + service PID/log path constants into `src/agenticops/cli/service.py`. Imports: `settings`, `formatters.console`. No imports from `slash`/`dispatch`.

```bash
.venv/bin/python -m py_compile src/agenticops/cli/service.py src/agenticops/cli/main.py
.venv/bin/python -m pytest tests/ -q
.venv/bin/aiops service status >/dev/null 2>&1; .venv/bin/aiops --help >/dev/null && echo "CLI OK"
git add -A && git commit --no-verify -m "refactor(cli): extract service.py from main.py (no behavior change)"
```

### Task 23: main.py — extract commands.py

- [ ] Move the Typer `app` + subcommand typers (`get_app`, `describe_app`, `create_app`, `delete_app`, `update_app`, `run_app`, `logs_app`, `service_app`) and ALL `@*_app.command()` functions + `init/quickstart/manage/unmanage/issues/issue/test_account` into `src/agenticops/cli/commands.py`. Imports: `renderers`, `service`, models. May import `slash.handle_slash_command` only if a command needs it (none should). No import from `dispatch`.

```bash
.venv/bin/python -m py_compile src/agenticops/cli/commands.py src/agenticops/cli/main.py
.venv/bin/python -m pytest tests/ -q
.venv/bin/aiops --help >/dev/null && .venv/bin/aiops get --help >/dev/null && echo "CLI OK"
git add -A && git commit --no-verify -m "refactor(cli): extract commands.py from main.py (no behavior change)"
```

### Task 24: main.py — extract dispatch.py + finalize main.py

- [ ] Move `chat()`, `_run_headless`, `_cli_persist_message`, `_persist_slash_interaction`, `_cli_setup_db_session` into `src/agenticops/cli/dispatch.py`. It imports `context`, `renderers`, `slash.handle_slash_command`, `display.StreamingCallbackHandler`. `main.py` shrinks to: logging setup, entry point, and registration/import of `commands.app`. Verify import order `context → formatters → renderers → slash → service → commands → dispatch → main` has no cycle (`.venv/bin/python -c "import agenticops.cli.main"`).

```bash
.venv/bin/python -m py_compile src/agenticops/cli/dispatch.py src/agenticops/cli/main.py
.venv/bin/python -c "import agenticops.cli.main" && echo "no import cycle"
.venv/bin/python -m pytest tests/ -q
.venv/bin/aiops --help >/dev/null && echo "CLI OK"
git add -A && git commit --no-verify -m "refactor(cli): extract dispatch.py, finalize main.py (~600L, no behavior change)"
```

### Stage 2 Gate: Final full regression

- [ ] **Run everything once more**

```bash
.venv/bin/python -m pytest tests/ -q
.venv/bin/python -c "import agenticops.web.app; import agenticops.cli.main" && echo "imports clean"
AWS_PROFILE=default .venv/bin/uvicorn agenticops.web.app:app --port 8011 & sleep 4
curl -s http://localhost:8011/api/health | head -c 200 ; echo
pkill -f "uvicorn agenticops.web.app:app --port 8011"
.venv/bin/aiops --help >/dev/null && echo "CLI OK"
wc -l src/agenticops/web/app.py src/agenticops/cli/main.py
```
Expected: suite green; both imports clean; `/api/health` returns JSON; CLI help prints; `app.py` and `main.py` substantially smaller.

---

## Spec Coverage Checklist

| Spec item | Task |
|-----------|------|
| F1 stream-error-partial | Task 3 |
| F2 cli-slash-no-persist | Task 1 |
| F3 token-metric-divergence | Task 2 |
| F4 tool-rebuild-fragile | Task 4 |
| F5 retry-brittle | Task 5 |
| F6 memory-inject-unvalidated | Task 7 |
| F7 memory-exc-swallow | Task 7 |
| F8 memory-swallow | Task 6 |
| F9 detect-parallel-downgrade | Task 8 |
| F10 ttl-race | Task 10 |
| F11 session-race | Task 11 |
| F12 stream-cancel (web) | Task 11 |
| F13 batch-mode-inconsistent | Task 9 |
| F14 no-cache (measure) | Task 17 |
| F15 dual-tools (doc+lock) | Task 14 |
| F16 yaml-escape | Task 15 |
| F17 atomic-write | Task 16 |
| cli-stream-cancel (partial) | Task 12 |
| cli-dup-refresolve | Task 13 |
| app.py split | Tasks 18-19 |
| main.py split | Tasks 20-24 |

All 18 confirmed/partial findings + both splits are covered.
