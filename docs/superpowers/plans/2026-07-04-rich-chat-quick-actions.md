# Rich Chat 切片 1(问题原地定位 + 建议 Chips)Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 聊天里点 I#N 在右侧面板原地定位检查(不跳页);每条 assistant 回复末尾模型生成 2-3 条建议动作,前端渲染为可点击 chips,点击即作为下一条用户消息发送。

**Architecture:** B2 用提示词标记块 `<<SUGGEST>>["...",...]`(仅 main agent),后端流结束时 `extract_suggestions` 剥离落库(`chat_messages.suggestions` JSON 列)并随 `done` 事件下发;前端渲染层过滤标记、`SuggestionChips` 只挂最后一条 assistant 消息。B1 把 `MessageList.handleRefClick` 的 I# 分支改为回调打开现有 `ContextPanel`(零新页面),面板头部加"让 agent 检查"按钮。

**Tech Stack:** FastAPI + SQLAlchemy(ALTER TABLE 迁移模式)、Strands、React 18 + TanStack Query + @tanstack/react-virtual、pytest、vitest。

**Spec:** `docs/superpowers/specs/2026-07-04-rich-chat-quick-actions-design.md`

## Global Constraints

- Branch:`MVP-2.0.1`(已存在,直接在其上提交)。
- 标记常量:`<<SUGGEST>>`,唯一定义于 `src/agenticops/chat/suggestions.py:SUGGEST_MARKER`;前端字面量出现两处(chatStream/MessageList),不建共享常量文件(YAGNI)。
- 每条建议 strip 后 ≤60 字符(超长截断),最多 3 条,空串丢弃;只认**最后一次**出现的标记。
- 任何解析失败 → 正文剥标记行、suggestions 为空;error 流不解析。
- 提示词只动 main agent;`tests/test_prompt_budget.py` 带宽(±25%)不得触发,触发则 STOP 调查。
- 提交用 `--no-verify`;**不 push** —— owner E2E 确认后才推(与 composer 2.0 一起)。
- 提交结尾:`Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
- 前端任务后:`cd src/agenticops/web/frontend && npx tsc --noEmit`;最终任务跑 `npm run build`。
- Python:`.venv/bin/python -m py_compile <files>` + 指名 pytest 文件。

---

### Task 1: 后端 — `extract_suggestions` 纯函数

**Files:**
- Create: `src/agenticops/chat/suggestions.py`
- Test: `tests/test_chat_suggestions.py`(新)

**Interfaces:**
- Produces: `SUGGEST_MARKER: str = "<<SUGGEST>>"`;`extract_suggestions(text: str) -> tuple[str, list[str]]`(Task 2/4 依赖)。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_chat_suggestions.py`:

```python
"""建议 chips — 标记块解析纯函数。"""

from agenticops.chat.suggestions import SUGGEST_MARKER, extract_suggestions


class TestExtractSuggestions:
    def test_normal_block(self):
        text = '结论如上。\n<<SUGGEST>>["深入分析 I#42", "扫描同区域 LB", "生成修复计划"]'
        clean, sugs = extract_suggestions(text)
        assert clean == "结论如上。"
        assert sugs == ["深入分析 I#42", "扫描同区域 LB", "生成修复计划"]

    def test_no_marker_returns_original(self):
        clean, sugs = extract_suggestions("plain reply")
        assert clean == "plain reply"
        assert sugs == []

    def test_malformed_json_strips_line_empty_suggestions(self):
        text = "body\n<<SUGGEST>>[broken json"
        clean, sugs = extract_suggestions(text)
        assert clean == "body"
        assert sugs == []

    def test_caps_at_three_and_60_chars(self):
        long = "x" * 100
        text = f'b\n<<SUGGEST>>["{long}", "a", "b", "c", "d"]'
        clean, sugs = extract_suggestions(text)
        assert len(sugs) == 3
        assert len(sugs[0]) == 60

    def test_last_marker_wins(self):
        text = '<<SUGGEST>>["old"]\nbody\n<<SUGGEST>>["new"]'
        clean, sugs = extract_suggestions(text)
        assert sugs == ["new"]
        assert "old" not in "".join(sugs)

    def test_empty_items_dropped_and_trailing_text_tolerated(self):
        text = 'b\n<<SUGGEST>>["", "  ok  "] trailing'
        clean, sugs = extract_suggestions(text)
        assert sugs == ["ok"]

    def test_empty_text(self):
        assert extract_suggestions("") == ("", [])
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_chat_suggestions.py -q 2>&1 | tail -3`
Expected: ImportError — no module `agenticops.chat.suggestions`。

- [ ] **Step 3: 实现**

创建 `src/agenticops/chat/suggestions.py`:

```python
"""Suggestion-chips marker parsing (MVP-2.0.1 sub-project B slice 1).

Main agent 被提示在每条回复末尾输出一行:
    <<SUGGEST>>["action 1", "action 2", "action 3"]
本模块从回复文本剥离该块。所有出口(Web 持久化、CLI、IM)共用。
"""

import json
import re

SUGGEST_MARKER = "<<SUGGEST>>"

# 剥离时整行移除(标记行内的任何残余不落库)
_MARKER_LINE_RE = re.compile(r"^[ \t]*" + re.escape(SUGGEST_MARKER) + r".*$", re.MULTILINE)

_MAX_ITEMS = 3
_MAX_LEN = 60


def extract_suggestions(text: str) -> tuple[str, list[str]]:
    """从回复文本剥离 <<SUGGEST>>[...] 块。

    Returns:
        (clean_text, suggestions)。无标记 → (原文, [])。解析失败 →
        (标记行整行移除后的文本, [])。只认最后一次出现的标记;每条
        strip 后 ≤60 字符截断;最多 3 条;空串丢弃。
    """
    if not text or SUGGEST_MARKER not in text:
        return text, []

    idx = text.rfind(SUGGEST_MARKER)
    payload = text[idx + len(SUGGEST_MARKER):].strip()

    suggestions: list[str] = []
    try:
        # raw_decode 容忍数组后的尾随杂质
        arr, _ = json.JSONDecoder().raw_decode(payload)
        if isinstance(arr, list):
            for item in arr:
                if isinstance(item, str):
                    s = item.strip()
                    if s:
                        suggestions.append(s[:_MAX_LEN])
                if len(suggestions) >= _MAX_ITEMS:
                    break
    except (ValueError, TypeError):
        suggestions = []

    clean = _MARKER_LINE_RE.sub("", text).rstrip()
    return clean, suggestions
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_chat_suggestions.py -q 2>&1 | tail -2`
Expected: 7 passed。

- [ ] **Step 5: Commit**

```bash
git add src/agenticops/chat/suggestions.py tests/test_chat_suggestions.py
git commit --no-verify -m "feat(chat): extract_suggestions marker parser for suggestion chips

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: 后端 — suggestions 列 + 持久化 + done 事件 + messages API

**Files:**
- Modify: `src/agenticops/models.py`(ChatMessage 类 ~:807-819;迁移函数,加在 chat_sessions model_id 迁移块之后)
- Modify: `src/agenticops/web/schemas.py`(`ChatMessageResponse` :582-593)
- Modify: `src/agenticops/web/app.py`(持久化块 :4545-4556;done 事件 :4590-4599;messages 端点 :4197-4204)
- Test: `tests/test_chat_suggestions.py`(追加)

**Interfaces:**
- Consumes: Task 1 的 `extract_suggestions`。
- Produces: `chat_messages.suggestions` JSON 可空列;`ChatMessageResponse.suggestions: Optional[list]`;done SSE payload 的 `suggestions` 字段(Task 5 依赖)。

- [ ] **Step 1: 写失败测试(追加到 tests/test_chat_suggestions.py)**

```python
import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    from agenticops.web.app import app
    return TestClient(app)


class TestPersistenceLayer:
    def test_chat_message_has_suggestions_column(self):
        from agenticops.models import ChatMessage
        assert hasattr(ChatMessage, "suggestions")

    def test_messages_api_echoes_suggestions(self, client):
        from agenticops.models import ChatMessage, ChatSession, get_db_session
        r = client.post("/api/chat/sessions", json={})
        sid = r.json()["session_id"]
        with get_db_session() as db:
            row = db.query(ChatSession).filter(ChatSession.session_id == sid).first()
            db.add(ChatMessage(session_id=row.id, role="assistant",
                               content="hi", suggestions=["next step"]))
        msgs = client.get(f"/api/chat/sessions/{sid}/messages").json()["messages"]
        assert msgs[-1]["suggestions"] == ["next step"]
        client.delete(f"/api/chat/sessions/{sid}")

    def test_response_schema_has_field(self):
        from agenticops.web.schemas import ChatMessageResponse
        assert "suggestions" in ChatMessageResponse.model_fields
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_chat_suggestions.py -q 2>&1 | tail -3`
Expected: 新 3 个失败(no column / no field)。

- [ ] **Step 3: models.py — 列 + 迁移**

ChatMessage 类(`attachments` 行后)加:

```python
    # Suggestion chips extracted from the reply tail (MVP-2.0.1); NULL = none
    suggestions: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
```

迁移函数里,紧跟 chat_sessions model_id 迁移块之后加:

```python
    # Migration: add suggestion-chips column to chat_messages if missing
    if insp.has_table("chat_messages"):
        cols = {c["name"] for c in insp.get_columns("chat_messages")}
        if "suggestions" not in cols:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE chat_messages ADD COLUMN suggestions JSON"))
                conn.commit()
```

然后对 dev DB 应用一次:`.venv/bin/python -c "from agenticops.models import init_db; init_db()"`

- [ ] **Step 4: schemas.py**

`ChatMessageResponse`(`attachments` 字段后)加:

```python
    suggestions: Optional[list] = None
```

- [ ] **Step 5: app.py — 持久化 + done + messages 端点**

(a) 持久化段:在 `# Persist assistant message` 注释之后、`with get_db_session() as db:` 之**前**加解析(保证"会话已删跳过持久化"路径下变量也有定义):

```python
            # Persist assistant message (re-verify session still exists to avoid
            # FK violation / orphan if it was deleted mid-stream)
            from agenticops.chat.suggestions import extract_suggestions
            _clean_text, _suggestions = extract_suggestions(accumulated)
            with get_db_session() as db:
```

块内的 `db.add(ChatMessage(...))` 改为存净文本 + 建议列(`_tu` 计算不动):

```python
                    db.add(ChatMessage(
                        session_id=db_session_pk,
                        role="assistant",
                        content=_clean_text,
                        suggestions=_suggestions or None,
                        tool_calls=tool_calls if tool_calls else None,
                        token_usage=_tu,
                        trace_id=_chat_trace_id,
                    ))
```

(注意:auto-name 块用 `accumulated[:500]` 生成标题,不改——标记在末尾,前 500 字符几乎不含;YAGNI。)

(b) done 事件(:4590 附近)改为:

```python
            yield {
                "event": "done",
                "data": json.dumps({
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "suggestions": _suggestions,
                }),
            }
```

(c) messages 端点(:4198)构造器加 `suggestions=m.suggestions,`。error 路径(:4605-4613)不动。

- [ ] **Step 6: 跑测试**

Run: `.venv/bin/python -m py_compile src/agenticops/models.py src/agenticops/web/schemas.py src/agenticops/web/app.py && .venv/bin/python -m pytest tests/test_chat_suggestions.py tests/test_chat_api.py tests/test_chat_messages_pagination.py -q 2>&1 | tail -2`
Expected: 全 passed。

- [ ] **Step 7: Commit**

```bash
git add src/agenticops/models.py src/agenticops/web/schemas.py src/agenticops/web/app.py tests/test_chat_suggestions.py
git commit --no-verify -m "feat(chat): persist suggestion chips + carry in done SSE event

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: 后端 — main agent 提示词块 + 预算验证

**Files:**
- Modify: `src/agenticops/agents/main_agent.py`(OUTPUT FORMATTING 段 :201-204)

**Interfaces:**
- Consumes: 无。
- Produces: main agent 每条回复末尾的 `<<SUGGEST>>` 行(运行时行为,Task 1 的解析器消费)。

- [ ] **Step 1: 提示词追加**

`MAIN_SYSTEM_PROMPT` 的 OUTPUT FORMATTING 段(:201-204)改为:

```python
OUTPUT FORMATTING:
- When referencing issues, use I#N notation (e.g., I#170). When referencing resources, use R#N notation (e.g., R#42).
  These references are auto-linked in the web UI and CLI.
- End EVERY reply with exactly one line (no text after it):
  <<SUGGEST>>["<action 1>", "<action 2>", "<action 3>"]
  containing 2-3 short follow-up actions the user would likely take next, in the
  conversation's language. If you asked the user a question, make each suggestion
  a direct answer option to that question. This line is machine-parsed and
  hidden from the user - do not reference it in your prose.
```

- [ ] **Step 2: 预算 + 回归验证**

Run: `.venv/bin/python -m py_compile src/agenticops/agents/main_agent.py && .venv/bin/python -m pytest tests/test_prompt_budget.py tests/test_preamble.py -q 2>&1 | tail -2`
Expected: 全 passed(带宽 ±25% 不触发;触发则 STOP 调查,勿直接重 pin)。

- [ ] **Step 3: Commit**

```bash
git add src/agenticops/agents/main_agent.py
git commit --no-verify -m "feat(agents): main agent emits <<SUGGEST>> follow-up block

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: CLI + IM 出口剥标记

**Files:**
- Modify: `src/agenticops/cli/display.py`(`StreamingCallbackHandler` :144-246)
- Modify: `src/agenticops/cli/main.py`(REPL :4262+:4280-4285;headless :3842-3847)
- Modify: `src/agenticops/im/feishu_ws.py`(:296-305)
- Test: `tests/test_chat_suggestions.py`(追加)

**Interfaces:**
- Consumes: Task 1 `extract_suggestions` / `SUGGEST_MARKER`。
- Produces: 无(出口净化)。

- [ ] **Step 1: 写失败测试(追加)**

```python
class TestCliStreamingSuppression:
    def _drive(self, chunks):
        from unittest.mock import MagicMock, patch
        from agenticops.cli.display import StreamingCallbackHandler
        h = StreamingCallbackHandler(MagicMock())
        printed = []
        with patch.object(h, "_flush_buf", side_effect=lambda: (printed.extend(h._buf), h._buf.clear())):
            for c in chunks:
                h(data=c)
            h(complete=True)
        return "".join(printed)

    def test_marker_split_across_chunks_suppressed(self):
        out = self._drive(["answer done\n<<SUG", 'GEST>>["a","b"]'])
        assert "SUGGEST" not in out
        assert "answer done" in out

    def test_partial_lookalike_flushed_at_end(self):
        out = self._drive(["price is 1<<2 ok"])
        assert out.endswith("ok")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_chat_suggestions.py::TestCliStreamingSuppression -q 2>&1 | tail -3`
Expected: FAIL(marker 被打印出来)。

- [ ] **Step 3: display.py — 跨 chunk 尾部滞留过滤**

`StreamingCallbackHandler.__init__` 追加:

```python
        self._suppress = False    # marker 已现,吞掉后续所有 data
        self._tail = ""           # 滞留的可能-是-marker-前缀 的尾巴
```

`__call__` 的 `if data:` 分支,把 `self._buf.append(data)` 前的逻辑改为:

```python
        # Text data -> stream to stdout with buffering
        if data:
            if self._phase != "streaming":
                self._flush_buf()
                if self._current_step:
                    self._complete_step()
                self._phase = "streaming"
                print()  # blank line before response
            from agenticops.chat.suggestions import SUGGEST_MARKER
            if self._suppress:
                return
            combined = self._tail + data
            midx = combined.find(SUGGEST_MARKER)
            if midx != -1:
                printable = combined[:midx].rstrip("\n")
                self._suppress = True
                self._tail = ""
            else:
                # 滞留可能是 marker 前缀的最长后缀,等下一 chunk 拼合判断
                hold = 0
                for k in range(min(len(SUGGEST_MARKER) - 1, len(combined)), 0, -1):
                    if SUGGEST_MARKER.startswith(combined[-k:]):
                        hold = k
                        break
                printable = combined[:-hold] if hold else combined
                self._tail = combined[-hold:] if hold else ""
            if printable:
                self._buf.append(printable)
            now = time.time()
            if now - self._last_flush > 0.05 or "\n" in (printable or ""):
                self._flush_buf()
```

`if complete:` 分支开头加(未压制时把滞留尾巴吐回):

```python
        if complete:
            if self._tail and not self._suppress:
                self._buf.append(self._tail)
                self._tail = ""
```

- [ ] **Step 4: cli/main.py + feishu_ws.py 剥标记**

main.py REPL(:4262)`response = str(result)` 后加:

```python
                from agenticops.chat.suggestions import extract_suggestions
                response, _ = extract_suggestions(response)
```

(此后 add_to_history/_cli_persist_message/format_reference_links 全用净文本,无需再改。)

headless(:3842)`response = str(result)` 后加同样两行(缩进 4 空格)。

feishu_ws.py(:296)`response_text = str(result)` 后加:

```python
                from agenticops.chat.suggestions import extract_suggestions
                response_text, _ = extract_suggestions(response_text)
```

- [ ] **Step 5: 跑测试**

Run: `.venv/bin/python -m py_compile src/agenticops/cli/display.py src/agenticops/cli/main.py src/agenticops/im/feishu_ws.py && .venv/bin/python -m pytest tests/test_chat_suggestions.py -q 2>&1 | tail -2`
Expected: 全 passed。

- [ ] **Step 6: Commit**

```bash
git add src/agenticops/cli/display.py src/agenticops/cli/main.py src/agenticops/im/feishu_ws.py tests/test_chat_suggestions.py
git commit --no-verify -m "feat(cli,im): strip <<SUGGEST>> marker at CLI streaming + IM outlets

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: 前端 — chips 渲染 + 流层过滤

**Files:**
- Create: `src/agenticops/web/frontend/src/components/chat/SuggestionChips.tsx`
- Modify: `src/agenticops/web/frontend/src/api/types.ts`(ChatMessage :593-608)
- Modify: `src/agenticops/web/frontend/src/lib/chatStream.ts`(StreamCallbacks :19-24;done case :196-200;donePayload :103,:215-222)
- Modify: `src/agenticops/web/frontend/src/hooks/useSessionStream.ts`(onDone :19-28)
- Modify: `src/agenticops/web/frontend/src/components/chat/MessageList.tsx`(Props、MessageRow :185+、streamingHtml memo :93-96)
- Modify: `src/agenticops/web/frontend/src/pages/Chat.tsx`(session 模式 MessageList :273-282)

**Interfaces:**
- Consumes: Task 2 的 done payload `suggestions` 字段 + messages API `suggestions`。
- Produces: `<SuggestionChips suggestions onPick disabled?>`;`MessageList` Props += `onSuggestionPick?: (text: string) => void`。

- [ ] **Step 1: types.ts**

`ChatMessage`(`attachments` 字段后)加:

```typescript
  /** Follow-up suggestion chips from the reply tail; only rendered on the last assistant message */
  suggestions?: string[];
```

- [ ] **Step 2: chatStream.ts**

(a) `StreamCallbacks.onDone` payload 类型加 `suggestions?: string[]`:

```typescript
  onDone?: (
    sessionId: string,
    payload: { content: string; toolCalls: ToolCall[]; tokenMetrics: { input: number; output: number } | null; suggestions?: string[] },
  ) => void;
```

(b) `send()` 里 donePayload 声明(:103)同步加 `suggestions?: string[]`;`case "done":` 改为:

```typescript
              case "done":
                this.set(sessionId, {
                  tokenMetrics: { input: data.input_tokens ?? 0, output: data.output_tokens ?? 0 },
                });
                doneSuggestions = Array.isArray(data.suggestions) ? data.suggestions : [];
                break;
```

(循环外、`let pendingText` 旁声明 `let doneSuggestions: string[] = [];`)

(c) donePayload 捕获(:215-222)改为(content 剥标记):

```typescript
      const final = this.states.get(sessionId) ?? EMPTY;
      if (!final.error) {
        donePayload = {
          content: final.content.split("<<SUGGEST>>")[0].trimEnd(),
          toolCalls: final.toolCalls,
          tokenMetrics: final.tokenMetrics,
          suggestions: doneSuggestions,
        };
      }
```

- [ ] **Step 3: useSessionStream.ts onDone 写缓存**

`assistantMsg` 构造(:20-27)加一行:

```typescript
          suggestions: payload.suggestions?.length ? payload.suggestions : undefined,
```

- [ ] **Step 4: SuggestionChips 组件**

创建 `src/agenticops/web/frontend/src/components/chat/SuggestionChips.tsx`:

```tsx
interface Props {
  suggestions: string[];
  onPick: (text: string) => void;
  disabled?: boolean;
}

/** Follow-up action chips under the last assistant message (click = send). */
export function SuggestionChips({ suggestions, onPick, disabled }: Props) {
  if (suggestions.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-1.5 mt-2">
      {suggestions.map((s, i) => (
        <button
          key={i}
          onClick={() => onPick(s)}
          disabled={disabled}
          className="px-3 py-1 rounded-full border border-border text-xs text-muted-foreground
                     hover:bg-muted hover:border-primary-400 hover:text-foreground
                     disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {s}
        </button>
      ))}
    </div>
  );
}
```

- [ ] **Step 5: MessageList 挂载 + 流层显示过滤**

(a) Props 接口加:

```typescript
  onSuggestionPick?: (text: string) => void;
```

(解构同步加 `onSuggestionPick`。)

(b) streamingHtml memo(:93-96)把入参剥标记:

```typescript
  const streamingHtml = useMemo(
    () => renderMarkdown(streamingContent.split("<<SUGGEST>>")[0]),
    [streamingContent],
  );
```

(c) 虚拟行渲染(:136)`<MessageRow msg={msg} />` 改为:

```tsx
              <MessageRow
                msg={msg}
                isLast={vi.index === messages.length - 1}
                streaming={streaming}
                onSuggestionPick={onSuggestionPick}
              />
```

(d) `MessageRow`(:185)签名与尾部改为:

```tsx
function MessageRow({ msg, isLast, streaming, onSuggestionPick }: {
  msg: ChatMessage;
  isLast?: boolean;
  streaming?: boolean;
  onSuggestionPick?: (text: string) => void;
}) {
```

在 assistant 气泡内容器末尾(TokenMetrics 渲染之后)加:

```tsx
        {msg.role === "assistant" && isLast && !streaming && onSuggestionPick &&
          Array.isArray(msg.suggestions) && msg.suggestions.length > 0 && (
          <SuggestionChips suggestions={msg.suggestions} onPick={onSuggestionPick} />
        )}
```

import:`import { SuggestionChips } from "./SuggestionChips";`

- [ ] **Step 6: Chat.tsx 接线**

session 模式 `<MessageList>`(:273)加 prop:

```tsx
              onSuggestionPick={(text) => sendMessage(text)}
```

- [ ] **Step 7: 验证**

Run: `cd src/agenticops/web/frontend && npx tsc --noEmit && npx vitest run 2>&1 | tail -3`
Expected: tsc 干净,vitest 全 passed。

- [ ] **Step 8: Commit**

```bash
git add src/agenticops/web/frontend/src
git commit --no-verify -m "feat(chat-ui): suggestion chips under last assistant message

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: B1 — I# 原地定位 + "让 agent 检查"

**Files:**
- Modify: `src/agenticops/web/frontend/src/components/chat/MessageList.tsx`(handleRefClick :34-40 + Props)
- Modify: `src/agenticops/web/frontend/src/components/chat/ContextPanel.tsx`(Props :19-22 + header :48-60)
- Modify: `src/agenticops/web/frontend/src/pages/Chat.tsx`(:273+ MessageList、:309-312 ContextPanel)
- Modify: `src/agenticops/web/frontend/src/locales/en.json`、`zh.json`

**Interfaces:**
- Consumes: 现有 `setContextIssueId` / `sendMessage` / `streaming`。
- Produces: `MessageList` Props += `onIssueRefClick?: (issueId: number) => void`;`ContextPanel` Props += `onAgentCheck?: () => void; agentCheckDisabled?: boolean`。

- [ ] **Step 1: MessageList — I# 点击改回调**

Props 加 `onIssueRefClick?: (issueId: number) => void;`(解构同步)。`handleRefClick` 改为:

```typescript
  const handleRefClick = (e: React.MouseEvent) => {
    const anchor = (e.target as HTMLElement).closest("a.md-ref") as HTMLAnchorElement | null;
    if (!anchor) return;
    e.preventDefault();
    const pathname = new URL(anchor.href).pathname;
    const issueMatch = pathname.match(/^\/app\/issues\/(\d+)$/);
    if (issueMatch && onIssueRefClick) {
      onIssueRefClick(Number(issueMatch[1]));
      return;
    }
    navigate(pathname);
  };
```

- [ ] **Step 2: ContextPanel — "让 agent 检查"按钮**

Props 改为:

```typescript
interface Props {
  issueId: number | null;
  onClose: () => void;
  onAgentCheck?: () => void;
  agentCheckDisabled?: boolean;
}
```

(解构同步。)header 里 `I#{issueId}` span 之后、close 按钮之前加:

```tsx
        <div className="flex items-center gap-1">
          {onAgentCheck && (
            <button
              onClick={onAgentCheck}
              disabled={agentCheckDisabled}
              className="flex items-center gap-1 px-2 py-1 text-[11px] rounded-md text-muted-foreground hover:text-foreground hover:bg-accent disabled:opacity-50 transition-colors"
              title={t("chat.contextPanel.agentCheck")}
            >
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
              </svg>
              {t("chat.contextPanel.agentCheck")}
            </button>
          )}
          <button
            onClick={onClose}
```

(原 close 按钮整体挪进这个 flex 容器;原外层 justify-between 结构不变。)

- [ ] **Step 3: Chat.tsx 接线**

MessageList(:273)加 `onIssueRefClick={setContextIssueId}`。ContextPanel(:309)改为:

```tsx
            <ContextPanel
              issueId={contextIssueId}
              onClose={() => setContextIssueId(null)}
              onAgentCheck={() => {
                if (contextIssueId == null) return;
                sendMessage(t("chat.contextPanel.checkPrompt").replace("{id}", String(contextIssueId)));
              }}
              agentCheckDisabled={streaming}
            />
```

(`useLocale` 的 `t` 在 Chat.tsx 已有。)

- [ ] **Step 4: i18n(两文件,chat.model.* 块后)**

en.json:

```json
  "chat.contextPanel.agentCheck": "Ask agent to check",
  "chat.contextPanel.checkPrompt": "Check the current status of I#{id}: verify whether the issue still exists, and suggest next steps",
```

zh.json:

```json
  "chat.contextPanel.agentCheck": "让 agent 检查",
  "chat.contextPanel.checkPrompt": "检查 I#{id} 的当前状态,确认问题是否仍存在,并给出下一步建议",
```

- [ ] **Step 5: 验证 + Commit**

Run: `cd src/agenticops/web/frontend && npx tsc --noEmit 2>&1 | tail -2`
Expected: 干净。

```bash
git add src/agenticops/web/frontend/src
git commit --no-verify -m "feat(chat-ui): I# refs open ContextPanel in place + ask-agent-to-check

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: 全量回归 + build + live E2E → STOP 等 owner

**Files:** 无新增。

- [ ] **Step 1: 后端全量回归**

Run: `caffeinate -i .venv/bin/python -u -m pytest tests/ -q --tb=line > /tmp/aiops-b1-regression.log 2>&1; tail -4 /tmp/aiops-b1-regression.log`
Expected: 基线(~3520 passed)+ 新增;仅允许两个已知环境失败(skills 脏文件的 registry_search、代理劫持的 web_tools invalid_headers)。

- [ ] **Step 2: 前端 build**

Run: `cd src/agenticops/web/frontend && npx tsc --noEmit && npm run build 2>&1 | tail -3`
Expected: 干净。

- [ ] **Step 3: live E2E(Playwright,server 重启加载新代码)**

```bash
pkill -f "uvicorn agenticops" 2>/dev/null; sleep 1
nohup .venv/bin/uvicorn agenticops.web.app:app --host 0.0.0.0 --port 8000 > /tmp/aiops-e2e.log 2>&1 &
sleep 6
```

浏览器验证 `http://localhost:8000/app/chat`:
1. 发一条消息 → 回复流式完成后,正文里**看不到** `<<SUGGEST>>` 字样,消息下方出现 2-3 个 chips。
2. 点击一个 chip → 其文本作为新用户消息发出并开始流式;流式期间 chips 消失。
3. 回复含 I#N 时点击 → 右侧 ContextPanel 滑出(URL 不变),四 tab 正常;点"让 agent 检查" → 检查消息发出。
4. 刷新页面 → 最后一条 assistant 消息的 chips 恢复(来自 DB)。
5. CLI 抽查:`aiops chat "列出未解决的 issues"` → 输出末尾无 `<<SUGGEST>>` 残留。

- [ ] **Step 4: STOP — 汇报 owner**

汇报测试计数、E2E 截图、提交清单。**不 push、不 merge** —— owner 确认 E2E 后连同 composer 2.0 一起决定推送。
