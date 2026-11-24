# ChatGPT-style Web Chat Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Web chat looks and works like ChatGPT with a Codex-style work log:
- a left chat list and a centered column;
- a collapsible «work steps» block above each answer, with live steps, durations, results and the model's narration;
- answers that render charts (bar / line / area / pie) and flowcharts instead of ASCII;
- a copy / regenerate / ⋯ action row and «下一步» chips;
- a rounded composer that holds its attachments inside the box, with the whole chat column as the drop target;
- a real mobile layout.

**Architecture:**
- **Backend.**
  - The SSE loop in `web/app.py` records, for each tool call:
    - where in the reply text it started (`text_offset`) and ended (`text_end`);
    - a redacted one-line input summary (new `tool_input` frame);
    - its duration;
    - a redacted result preview.
  - All of this is persisted in `ChatMessage.tool_calls`.
  - Web-built main agents get a prompt rule to emit ```` ```chart ```` JSON and ```` ```mermaid ```` blocks.
- **Frontend.**
  - Pure libs split the reply into a work timeline plus the answer (`lib/workSteps`), and the answer into markdown / chart / mermaid segments (`lib/richBlocks`).
  - Components render those segments: recharts (already a dependency), and mermaid lazy-loaded (new dependency).
  - The composer, the shell rail and the mobile drawer are layout work on the existing components.

**Tech Stack:** FastAPI + sse-starlette, Strands 1.64 stream events, SQLAlchemy JSON column; React 18 + TanStack Query/Virtual, recharts 3, mermaid 11 (new, dynamic import), Tailwind; vitest (node env, no DOM); Playwright MCP for browser E2E.

**Spec:** `docs/superpowers/specs/2026-11-07-chatgpt-style-chat-design.md` (owner-approved 2026-11-07, Chinese). Read it with this plan. Where this plan names a value, it is the spec's value or a ruling recorded below.

## Global Constraints

- **Branch.**
  - Work in the main checkout `/Users/malibo/MyDev/AgenticOps` on branch `MVP-2.7.1` (owner's decision). Base `cd4f0d2`.
  - Never push. The owner confirms after full evidence; then `git push --no-verify`.
  - The working tree carries the owner's local, uncommitted state. Never commit, revert or `git checkout --` any of it:
    - `config/settings.yaml`;
    - `src/agenticops/agents/reporter_agent.py`;
    - `agent-memory/`;
    - `skills/`;
    - `src/agenticops/web/frontend/dist/`;
    - `tsconfig.tsbuildinfo`;
    - the RAW idea files.
- **Tests.**
  - Backend: `.superpowers/aiops-pytest.sh <logfile> <pytest args>`. It uses a throwaway DB and backs up and restores `agent-memory/` and `skills/`. Never pipe pytest into `tail`.
  - Frontend, from `src/agenticops/web/frontend`:
    - `npx vitest --run <file>`;
    - `npx tsc --noEmit`;
    - `npm run build`.
- **Commits.** Explicit paths only, never `git add -A` / `git add .`. Messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Local service.**
  - `aiops service stop|start|restart|status`. Never nohup, never a hand-started uvicorn.
  - Rebuild the frontend (`npm run build`) before restarting.
- **Scope of the prompt rule.**
  - Only Web chat agents get it, both the full one and the read-only (viewer) one.
  - CLI, IM bots, the scheduler and the reporter are unchanged.
  - The rule is English and cloud-neutral (concept categories; vendor names only as examples).
- **Redaction.**
  - Summaries and previews pass `security.redaction.redact_secrets` first, then the new display-only filter.
  - The shared `redact_secrets` is NOT changed: it guards every DB column, and the owner mandates precision there.
- **UI rules.**
  - Every overlay animates in with `animate-[slideInRight_0.2s_ease-out]` and closes on ESC.
  - No OpenAI brand assets.
  - Inline SVG icons; no new icon library (`lucide-react` is already a dependency and may be used).
  - Every new string goes in both `src/locales/en.json` and `zh.json`, because `locales.test.ts` checks parity.
- **No new dependencies except `mermaid`.** No syntax highlighter, no chart library beyond recharts.
- **Skills to load while building.**
  - `frontend-design` before Tasks 7–9.
  - `dataviz` before writing `ChartBlock` (Task 6).

## Rulings made while planning (the spec's builder questions and what the code showed)

1. **The summary is a separate frame.**
   - Strands streams a tool's input as a growing string. `current_tool_use.input` is incomplete when `tool_start` fires.
   - So the summary arrives in a new SSE frame `tool_input {call_id, summary}`. It is sent when the assistant `message` event carries the parsed `toolUse.input`.
   - The spec said «`tool_start` 增加 summary»; this is the same fact, one frame later.
2. **Offsets have to be clamped.**
   - The DB write boundary redacts `content`, which can shift character offsets by a few characters in a reply that quotes a secret.
   - The frontend clamps every offset to `[0, content.length]`. A shifted boundary misplaces at most a few characters between narration and answer, and never loses text.
3. **`enhanced_task` is one step.**
   - Its inner `tool_start` / `tool_end` sub-events are no longer emitted or recorded. Its text still streams.
   - That text lands between the step's `text_offset` and `text_end`, so it shows under that step in the timeline.
4. **Step time is measured from first sight.**
   - A step's duration runs from the moment its `current_tool_use` is first seen to its result. That includes the model writing the call.
   - The collapsed header's total is the sum of the step durations.
5. **No second agent cache.**
   - `web/session_manager.ChatSessionManager` only ever builds Web chat agents, so it always passes `rich_output=True`.
6. **Markdown images.** `![x](url)` already renders as `!` plus a link (`renderMarkdown` has no image syntax). That is the spec's «显示为链接»; nothing to build.
7. **Mermaid init directives.** `%%{ ... }%%` directives are stripped before rendering, on top of `securityLevel: "strict"`.
8. **Enter on touch devices.** On a coarse pointer (touch), Enter inserts a newline and sending is by the button, as in mobile ChatGPT. On desktop, Enter sends.
9. **Chat list.**
   - The existing resizable `SessionFlyout` is kept as the desktop chat list (≥ 768 px), now open by default (`aiops-chat-list-open`, persisted).
   - Below 768 px it opens as a drawer.

## Review Focus

1. **Half-written chart fence while streaming.**
   - A ```` ```chart ```` block whose closing fence has not arrived yet shows as a plain code block.
   - It never shows «图表数据无法解析» for a moment.
   - Pinned in Task 5: `splitRichBlocks` streaming test.
2. **Hostile mermaid source.**
   - The input is a `%%{init: {"securityLevel":"loose"}}%%` directive, a `click A "javascript:…"` line, or a `<script>` label.
   - Expected: the directive is stripped, mermaid runs strict, and nothing executes.
   - Pinned in Task 5: `mermaidSource` test.
3. **A huge tool result.**
   - A 5 MB result makes `result_preview` cut its input before any regex runs, and return ≤ 200 characters quickly.
   - Pinned in Task 1: `test_preview_of_a_huge_result_is_bounded`.
4. **Redaction shifted the offsets.**
   - Offsets beyond the content length are clamped, and no text is lost.
   - Pinned in Task 4: `splitWork` clamp test.
5. **Virtualized rows remounting.**
   - Scrolling a long chat away from a mermaid block and back reuses its cached SVG. There is no second `mermaid.render` and no height jump.
   - Pinned in Task 6: `mermaidCache` test plus the E2E scroll check in Task 10.

---

### Task 0: Commit the pending 2.7.1 doc edits

The working tree holds the 2.7.1 doc updates written earlier today (not yet committed). They go in first, so Task 11's doc commit only carries this feature.

**Files:** `CLAUDE.md`, `README.md`, `README_CN.md`, `docs/DESIGN.md`, `docs/MVP-2.7.0-RELEASE.md`, `docs/MVP-2.7.1-RELEASE.md`, `docs/README.md`, `docs/superpowers/specs/2026-11-07-chatgpt-style-chat-design.md`, `docs/superpowers/plans/2026-11-07-chatgpt-style-chat.md`

- [ ] **Step 1: Check that the diff is only docs**

  Run `git diff --stat -- <the files above>`. Expected: only those files, with no code.

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md README.md README_CN.md docs/DESIGN.md docs/MVP-2.7.0-RELEASE.md docs/MVP-2.7.1-RELEASE.md docs/README.md \
  docs/superpowers/specs/2026-11-07-chatgpt-style-chat-design.md docs/superpowers/plans/2026-11-07-chatgpt-style-chat.md
git commit -m "docs(2.7.1): record the rebase onto main bb01e5f; design + plan for the ChatGPT-style chat"
```

---

### Task 1: Tool-step facts (summary, preview, display redaction)

**Files:**
- Create: `src/agenticops/chat/tool_steps.py`
- Test: `tests/test_chat_tool_steps.py`

**Interfaces:**
- Produces:
  - `summarize_input(tool_input) -> str`
  - `result_preview(text: str | None) -> str`
  - `redact_for_display(text: str) -> str`
  - constants `SUMMARY_MAX = 160`, `PREVIEW_MAX = 200`, `PREVIEW_SCAN_MAX = 4000`

- [ ] **Step 1: Write the failing tests**

```python
from agenticops.chat.tool_steps import summarize_input, result_preview, redact_for_display, SUMMARY_MAX, PREVIEW_MAX
M = "[REDACTED-SECRET]"

def test_command_field_wins():
    assert summarize_input({"command": "kubectl get pods -A", "account": "prod"}) == "kubectl get pods -A"

def test_single_string_field_is_the_summary():
    assert summarize_input({"query": "list RDS instances\nin prod"}) == "list RDS instances in prod"

def test_scalars_join_as_key_value():
    assert summarize_input({"issue_id": 12, "rerun": True, "nested": {"a": 1}}) == "issue_id=12 rerun=True"

def test_string_input_and_empty():
    assert summarize_input("raw text") == "raw text" and summarize_input(None) == "" and summarize_input({}) == ""

def test_summary_is_one_line_and_bounded():
    s = summarize_input({"command": "x" * 500})
    assert "\n" not in s and len(s) == SUMMARY_MAX and s.endswith("…")

@pytest.mark.parametrize("raw,leak", [
    ("aws configure set aws_secret_access_key wJalrXUtnFEMI/K7MDENG", "wJalrXUtnFEMI"),
    ("mysql --password hunter2secret -h db", "hunter2secret"),
    ("mysql --password=hunter2secret", "hunter2secret"),
    ("curl -H 'Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.abc.def' https://x", "eyJhbGciOiJIUzI1NiJ9"),
    ("psql postgresql://admin:S3cretPass@db:5432/app", "S3cretPass"),
    ("kubectl get ns --token=abcdef123456", "abcdef123456"),
    ("export AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG", "wJalrXUtnFEMI"),
])
def test_display_redaction_masks_the_common_shapes(raw, leak):
    out = redact_for_display(raw)
    assert leak not in out and M in out
    assert leak not in summarize_input({"command": raw}) and leak not in result_preview(raw)

def test_display_redaction_keeps_ordinary_text():
    assert redact_for_display("kubectl get pods -n orders") == "kubectl get pods -n orders"
    assert redact_for_display("postgresql://db:5432/app") == "postgresql://db:5432/app"

def test_preview_collapses_whitespace_and_truncates():
    p = result_preview("line1\n\n  line2\t" + "y" * 400)
    assert p.startswith("line1 line2 ") and len(p) == PREVIEW_MAX and p.endswith("…")
    assert result_preview(None) == "" and result_preview("") == ""

def test_preview_of_a_huge_result_is_bounded():
    import time
    t = time.monotonic(); p = result_preview("A" * 5_000_000)
    assert len(p) <= PREVIEW_MAX and time.monotonic() - t < 0.5
```

- [ ] **Step 2: Run the tests and watch them fail**

  Run `.superpowers/aiops-pytest.sh /tmp/t1.log tests/test_chat_tool_steps.py`.

  Expected: `ModuleNotFoundError: agenticops.chat.tool_steps`.

- [ ] **Step 3: Implement `chat/tool_steps.py`**

  - **`redact_for_display(text)`.** Apply `redact_secrets(text)` first. Then the display patterns, each keeping the label and replacing the value with `PLACEHOLDER` (imported from `security.redaction`):
    - a CLI flag `--(password|passwd|pwd|secret|token|api-key|apikey|access-key|secret-access-key|private-key|client-secret|credentials?)` followed by `=` or whitespace, then the value (quoted or `\S+`);
    - a key whose name contains `secret|password|passwd|token|api_key|apikey|private_key` (case-insensitive, `[A-Za-z0-9_.-]*` around it), followed by `=`, `:` or whitespace, then the value;
    - `Authorization:\s*(Bearer|Basic|Token)?\s*<value>` and a bare `Bearer <8+ token chars>`;
    - URL userinfo `scheme://user:<pw>@` → `scheme://user:[REDACTED-SECRET]@`.
  - **`summarize_input(tool_input)`.** Pick the first that applies:
    1. a dict with a non-empty str `command` → that string;
    2. a dict with exactly one non-empty str value → that value;
    3. otherwise the scalar entries (str / int / float / bool) as `k=v`, joined by a space, in input order;
    4. a str input → itself;
    5. anything else → `""`.

    Then collapse whitespace to single spaces, apply `redact_for_display`, and cut to `SUMMARY_MAX` with a trailing `…`.
  - **`result_preview(text)`.** Cut to `PREVIEW_SCAN_MAX` before anything else, collapse whitespace, apply `redact_for_display`, then cut to `PREVIEW_MAX` with `…`.
  - **Truncation.** When the text is longer than the limit, keep `limit - 1` characters and add `…`, so the length is exactly the limit.

- [ ] **Step 4: Run the tests and watch them pass**

  Run the Step 2 command. Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add src/agenticops/chat/tool_steps.py tests/test_chat_tool_steps.py
git commit -m "feat(chat): tool-step summary, result preview and a display-only redaction for the work log"
```

---

### Task 2: SSE frames and persistence for the work steps

**Files:**
- Modify: `src/agenticops/web/app.py` (the `_generate()` loop, ~lines 4620–4730, and the post-loop sweep)
- Test: `tests/test_chat_work_steps_stream.py`. Copy the `env` fixture, `frames` and `_session` helpers from `tests/test_chat_dispatch_api.py`; the fake agent returns `stream_async` events.

**Interfaces:**
- Consumes: Task 1 `summarize_input`, `result_preview`.
- Produces (SSE frames; each field also persisted on the matching `tool_calls[i]` dict):
  - `tool_start {name, call_id, text_offset: int}`
  - `tool_input {call_id, summary: str}` (new frame)
  - `tool_end {name, call_id, outcome, duration_ms: int, result_preview: str, text_end: int}`
  - The post-loop sweep's `tool_end` (no result seen): `outcome: "unknown"`, `text_end = text_offset`, `duration_ms` measured up to the sweep, `result_preview: ""`.

- [ ] **Step 1: Write the failing tests**

```python
def test_offsets_summary_duration_and_preview_are_streamed_and_stored(env, monkeypatch):
    client, _, webapp = env
    sid, pk = _session()
    class _A:
        async def stream_async(self, _c):
            yield {"data": "Let me check. "}                                   # 14 chars
            yield {"current_tool_use": {"toolUseId": "t1", "name": "run_kubectl", "input": ""}}
            yield {"current_tool_use": {"toolUseId": "t1", "name": "run_kubectl", "input": "{\"comm"}}
            yield {"message": {"role": "assistant", "content": [
                {"text": "Let me check. "},
                {"toolUse": {"toolUseId": "t1", "name": "run_kubectl",
                             "input": {"command": "kubectl get ns --token=abcdef123456"}}}]}}
            yield {"message": {"role": "user", "content": [{"toolResult": {"toolUseId": "t1", "status": "success",
                                                                          "content": [{"text": "default\nkube-system"}]}}]}}
            yield {"data": "Two namespaces."}
    monkeypatch.setattr(webapp._chat_sessions, "get_or_create", lambda s: _A())
    fs = frames(_send(client, sid).text)
    start = next(d for e, d in fs if e == "tool_start")
    inp = next(d for e, d in fs if e == "tool_input")
    end = next(d for e, d in fs if e == "tool_end")
    assert start["text_offset"] == 14
    assert inp == {"call_id": "t1", "summary": "kubectl get ns --token=[REDACTED-SECRET]"}
    assert end["text_end"] == 14 and end["result_preview"] == "default kube-system" and end["duration_ms"] >= 0
    s = get_session(); reply = s.query(ChatMessage).filter_by(session_id=pk, role="assistant").one(); s.close()
    tc = reply.tool_calls[0]
    assert (tc["text_offset"], tc["text_end"], tc["summary"], tc["result_preview"]) == (
        14, 14, "kubectl get ns --token=[REDACTED-SECRET]", "default kube-system")
    assert "abcdef123456" not in json.dumps(reply.tool_calls)
    assert reply.content == "Let me check. Two namespaces."

def test_a_tool_with_no_result_ends_unknown_at_its_start(env, monkeypatch):
    # current_tool_use t9 at offset 3, no result → tool_end outcome unknown, text_end == text_offset == 3, result_preview ""

def test_enhanced_inner_tools_are_not_steps(env, monkeypatch):
    # yield enhanced_task current_tool_use (t5); then tool_stream events of kinds tool_start "Read", text "inner", tool_end "Read";
    # then the toolResult for t5; then data "Final".
    # Asserts:
    #   - no tool_start / tool_end frame named "Read";
    #   - reply.tool_calls names == ["enhanced_task"];
    #   - its text_offset == 0 and text_end == len("inner");
    #   - reply.content == "innerFinal".
```

  Write the bodies of the second and third tests as their comments say. Build the `tool_stream` events in the shape `tests/test_acp_sse_bridge.py` uses (`{"type": "tool_stream", "tool_stream_event": {"data": {...}}}`).

- [ ] **Step 2: Run the tests and watch them fail**

  Run `.superpowers/aiops-pytest.sh /tmp/t2.log tests/test_chat_work_steps_stream.py`.

  Expected: a `KeyError` on `text_offset`, or `StopIteration` on `tool_input`.

- [ ] **Step 3: Implement it in `web/app.py` `_generate()`**

  - **Timing.** Keep `_tool_t0: dict[str, float]`, keyed by call_id, set at first sight (`time.monotonic()`).
  - **Start.** On first sight, the dict appended to `tool_calls` gets `text_offset = len(accumulated)`, and the `tool_start` frame carries it.
  - **Summary.** In the `_msg` loop, for a `toolUse` block whose `toolUseId` matches a call with no `summary` yet:
    - set `t["summary"] = summarize_input(block["toolUse"].get("input"))`;
    - yield `tool_input`.
  - **Result.** On the `toolResult`:
    - `t["duration_ms"] = int((now - t0) * 1000)`;
    - `t["result_preview"] = result_preview(_txt)`;
    - `t["text_end"] = len(accumulated)`;
    - add all three to the `tool_end` frame.
  - **Sweep.** Unfinished calls get `outcome = "unknown"`, `text_end = t.get("text_offset", len(accumulated))`, `duration_ms` up to now and `result_preview = ""`.
  - **`tool_stream` branch.** Keep the `text` handling (`accumulated +=` and yield). Drop the `tool_start` / `tool_end` handling of enhanced sub-events: no append and no yield. Leave `acp/mapping.py` and its tests unchanged.

- [ ] **Step 4: Run the new tests, then the chat suites**

  Run `.superpowers/aiops-pytest.sh /tmp/t2.log tests/test_chat_work_steps_stream.py tests/test_chat_dispatch_api.py tests/test_chat_api.py tests/test_acp_sse_bridge.py tests/test_chat_send_attachments.py`.

  Expected: all passed. `test_tool_frames_carry_call_id_and_outcome` still passes.

- [ ] **Step 5: Commit**

```bash
git add src/agenticops/web/app.py tests/test_chat_work_steps_stream.py
git commit -m "feat(chat): stream and store each tool step's text offsets, summary, duration and result preview"
```

---

### Task 3: The rich-output prompt rule for Web chat agents

**Files:**
- Modify: `src/agenticops/agents/main_agent.py` (new constant, a new `create_main_agent` parameter, both prompt branches)
- Modify: `src/agenticops/web/session_manager.py:505` (pass `rich_output=True`)
- Test: `tests/test_main_agent_rich_output.py`

**Interfaces:**
- Produces:
  - `RICH_OUTPUT_PROMPT: str`
  - `create_main_agent(model_id_override="", effort_override="", read_only=False, rich_output=False) -> Agent`

- [ ] **Step 1: Write the failing tests**

  Stub `BedrockModel`, `_safe_mcp_clients` and the curators the way `tests/test_viewer_role.py` builds a read-only agent, and read `agent.system_prompt`.

```python
def test_rule_is_only_in_rich_builds(build):            # build(read_only=..., rich_output=...) → system prompt text
    assert "```chart" in build(rich_output=True) and "```mermaid" in build(rich_output=True)
    assert "```chart" not in build() and "```mermaid" not in build()

def test_viewer_web_build_gets_the_rule(build):
    assert "```chart" in build(read_only=True, rich_output=True)

def test_rule_is_english_and_bounded():
    from agenticops.agents.main_agent import RICH_OUTPUT_PROMPT
    assert not any("一" <= c <= "鿿" for c in RICH_OUTPUT_PROMPT) and len(RICH_OUTPUT_PROMPT) < 1500
    assert "ASCII" in RICH_OUTPUT_PROMPT

def test_web_session_manager_builds_rich(monkeypatch):
    # monkeypatch web.session_manager.create_main_agent with a recorder; get_or_create("s1") → kwargs["rich_output"] is True;
    # get_or_create("s2", True) → read_only=True and rich_output=True

def test_other_builders_stay_plain():
    # grep-style: scheduler/scheduler.py, im/session_manager.py and cli/main.py call create_main_agent() without rich_output
    import pathlib, re
    for p in ["scheduler/scheduler.py", "im/session_manager.py", "cli/main.py"]:
        src = (pathlib.Path("src/agenticops") / p).read_text()
        assert "rich_output" not in src
```

- [ ] **Step 2: Run the tests and watch them fail**

  Run `.superpowers/aiops-pytest.sh /tmp/t3.log tests/test_main_agent_rich_output.py`.

  Expected: `ImportError: RICH_OUTPUT_PROMPT`, or `TypeError: unexpected keyword 'rich_output'`.

- [ ] **Step 3: Implement the rule**

  Add `RICH_OUTPUT_PROMPT` with this exact text:

```
RICH OUTPUT (this chat renders these blocks; never draw charts, diagrams or flows with ASCII characters):
- Numbers that compare categories, show shares, or change over time -> one ```chart block holding only JSON:
  {"type":"bar|line|area|pie","title":"...","x":["label", ...],"series":[{"name":"...","data":[1, 2, ...]}],"unit":"..."}
  x and every series' data have the same length; a pie has exactly one series; at most 8 series and 50 points.
  Chart only real figures you obtained from tools or context - never invent data - and state the key numbers in prose too.
- A flow, a call chain, a dependency path, or a sequence of steps -> one ```mermaid block (flowchart LR/TD or
  sequenceDiagram). Quote node labels; no click handlers, links, HTML, or %%{init}%% directives.
- Tabular detail stays a markdown table.
```

  - **Full agent.** Append it after `focus_section` when `rich_output`.
  - **Read-only agent.** Append it to `READ_ONLY_SYSTEM_PROMPT` before `build_system_prompt` when `rich_output`.
  - **Docstring.** Add: `rich_output: a Web chat build — the chart / mermaid output rule (CLI, IM, scheduler stay plain).`
  - **Session manager.** `session_manager.get_or_create` calls `create_main_agent(..., rich_output=True, **viewer)`.

- [ ] **Step 4: Run the new tests and the prompt / viewer suites**

  Run `.superpowers/aiops-pytest.sh /tmp/t3.log tests/test_main_agent_rich_output.py tests/test_prompt_budget.py tests/test_viewer_role.py tests/test_chat_api.py`.

  Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add src/agenticops/agents/main_agent.py src/agenticops/web/session_manager.py tests/test_main_agent_rich_output.py
git commit -m "feat(chat): Web chat agents answer statistics with chart blocks and flows with mermaid, never ASCII"
```

---

### Task 4: Work timeline logic and the stream store

**Files:**
- Create: `src/agenticops/web/frontend/src/lib/workSteps.ts`
- Modify:
  - `src/agenticops/web/frontend/src/lib/chatStream.ts` (`ToolCall` fields, the `tool_input` frame, `tool_start` / `tool_end` fields)
  - `src/agenticops/web/frontend/src/api/types.ts` (`ChatMessage.tool_calls` item type)
- Test:
  - `src/agenticops/web/frontend/src/__tests__/workSteps.test.ts`
  - additions to `__tests__/chatStream.test.ts`

**Interfaces:**
- Consumes: Task 2's frames.
- Produces:
  - `ToolCall`, with `summary?: string; duration_ms?: number; result_preview?: string; text_offset?: number; text_end?: number`. `ChatMessage.tool_calls` uses the same type.
  - `type TimelineItem = { kind: "text"; text: string } | { kind: "tool"; tool: ToolCall }`
  - `splitWork(content: string, tools: ToolCall[], opts?: { live?: boolean }): { timeline: TimelineItem[]; answer: string }`
  - `workTotals(tools: ToolCall[]): { count: number; ms: number | null }`. `ms` is the sum of `duration_ms`; `null` when no tool has one.

- [ ] **Step 1: Write the failing tests**

```ts
const T = (o: Partial<ToolCall>): ToolCall => ({ name: "x", status: "done", ...o });

it("no tools: everything is the answer", () =>
  expect(splitWork("Hi", [])).toEqual({ timeline: [], answer: "Hi" }));
it("legacy tools without offsets: tools in the block, content is the answer", () =>
  expect(splitWork("Hi", [T({ call_id: "a" })])).toEqual({ timeline: [{ kind: "tool", tool: T({ call_id: "a" }) }], answer: "Hi" }));
it("narration before the tool goes in the block", () => {
  const r = splitWork("Let me check. Result", [T({ text_offset: 14, text_end: 14 })]);
  expect(r.timeline.map((i) => i.kind)).toEqual(["text", "tool"]);
  expect((r.timeline[0] as any).text).toBe("Let me check.");
  expect(r.answer).toBe("Result");
});
it("text written while a step runs stays with the step", () => {
  const r = splitWork("Ainner Final", [T({ text_offset: 1, text_end: 6 })]);
  expect(r.timeline.map((i) => (i.kind === "text" ? i.text : "TOOL"))).toEqual(["A", "TOOL", "inner"]);
  expect(r.answer).toBe("Final");
});
it("an answer written before a trailing tool is still the answer", () => {
  const r = splitWork("The answer.", [T({ text_offset: 11, text_end: 11 })]);
  expect(r.answer).toBe("The answer.");
  expect(r.timeline.map((i) => i.kind)).toEqual(["tool"]);
});
it("offsets past the end are clamped (redaction shortened the text) and no text is lost", () => {
  const r = splitWork("Short", [T({ text_offset: 999, text_end: 999 })]);
  expect(r.answer).toBe("Short");
});
it("live with a running tool: no fallback, the text stays in the block", () => {
  const r = splitWork("Checking", [T({ status: "running", text_offset: 8 })], { live: true });
  expect(r.answer).toBe("");
  expect((r.timeline[0] as any).text).toBe("Checking");
});
it("two tools with narration between", () => {
  const r = splitWork("a b c", [T({ text_offset: 2, text_end: 2 }), T({ text_offset: 4, text_end: 4 })]);
  expect(r.timeline.map((i) => (i.kind === "text" ? i.text : "TOOL"))).toEqual(["a", "TOOL", "b", "TOOL"]);
  expect(r.answer).toBe("c");
});
it("totals", () => {
  expect(workTotals([T({ duration_ms: 1200 }), T({ duration_ms: 800 })])).toEqual({ count: 2, ms: 2000 });
  expect(workTotals([T({})])).toEqual({ count: 1, ms: null });
});
```

  Add to `chatStream.test.ts`: a stream of `tool_start {text_offset:3}` → `tool_input {call_id, summary}` → `tool_end {duration_ms, result_preview, text_end}` → `done`. The `onDone` payload's `toolCalls[0]` carries all five new fields.

- [ ] **Step 2: Run the tests and watch them fail**

  Run `npx vitest --run src/__tests__/workSteps.test.ts src/__tests__/chatStream.test.ts`.

  Expected: cannot resolve `@/lib/workSteps`, and the new chatStream assertion fails.

- [ ] **Step 3: Implement `splitWork` and the store changes**

  **`splitWork` algorithm:**
  - Clamp each offset to `[0, len]`.
  - If any tool lacks `text_offset`, use the legacy shape.
  - Sort the tools by `text_offset` (stable).
  - **Cut points.** Let `o_i` be each tool's offset and `E = max(o_n, max(text_end ?? o_i))`. In live mode, a running tool makes `E = len`.
  - **Segments.** `seg_0 = [0, o_1)`, `seg_i = [o_i, o_{i+1})`, `seg_n = [o_n, E)`.
  - **Timeline.** `seg_0, tool_1, seg_1, …, tool_n, seg_n`, trimmed, with blank segments dropped.
  - **Answer.** `content.slice(E).trim()`.
  - **Fallback.** If the answer is empty, not live, and some text segment is non-blank: the last non-blank segment becomes the answer and leaves the timeline.

  **Store (`chatStream.ts`):**
  - `tool_start` stores `text_offset`.
  - The new `case "tool_input"` patches `summary` by `call_id`.
  - `tool_end` also stores `duration_ms`, `result_preview` and `text_end`.

- [ ] **Step 4: Run the tests and watch them pass, then run tsc**

  Run the Step 2 command, then `npx tsc --noEmit`. Expected: all passed, exit 0.

- [ ] **Step 5: Commit**

```bash
git add src/agenticops/web/frontend/src/lib/workSteps.ts src/agenticops/web/frontend/src/lib/chatStream.ts \
  src/agenticops/web/frontend/src/api/types.ts src/agenticops/web/frontend/src/__tests__/workSteps.test.ts \
  src/agenticops/web/frontend/src/__tests__/chatStream.test.ts
git commit -m "feat(chat/web): split a reply into the work timeline and the answer; the stream keeps each step's facts"
```

---

### Task 5: Rich block parsing, chart spec validation, mermaid source guard, code-copy markup

**Files:**
- Create: `src/agenticops/web/frontend/src/lib/richBlocks.ts`
- Modify: `src/agenticops/web/frontend/src/lib/renderMarkdown.ts` (option `{ copyButtons?: boolean }`; default off, so ReportDetail is unchanged)
- Test:
  - `src/agenticops/web/frontend/src/__tests__/richBlocks.test.ts`
  - additions to `__tests__/renderMarkdown.test.ts`

**Interfaces:**
- Produces:
  - `interface ChartSpec { type: "bar" | "line" | "area" | "pie"; title?: string; unit?: string; x: (string | number)[]; series: { name: string; data: (number | null)[] }[] }`
  - `type RichSegment = { kind: "md"; text: string } | { kind: "chart"; spec: ChartSpec | null; source: string } | { kind: "mermaid"; source: string }`
  - `splitRichBlocks(md: string): RichSegment[]`
  - `parseChartSpec(json: string): ChartSpec | null`
  - `mermaidSource(src: string): string`
  - `CHART_LIMITS = { maxSeries: 12, maxPoints: 500 }`
  - `renderMarkdown(md: string, opts?: { copyButtons?: boolean }): string`

- [ ] **Step 1: Write the failing tests**

```ts
const CH = '{"type":"bar","x":["a","b"],"series":[{"name":"n","data":[1,2]}]}';
it("plain markdown is one segment", () => expect(splitRichBlocks("# Hi\ntext")).toEqual([{ kind: "md", text: "# Hi\ntext" }]));
it("md, chart, md", () => {
  const s = splitRichBlocks(`before\n\`\`\`chart\n${CH}\n\`\`\`\nafter`);
  expect(s.map((x) => x.kind)).toEqual(["md", "chart", "md"]);
  expect((s[1] as any).spec.series[0].data).toEqual([1, 2]);
});
it("bad chart JSON keeps its source with spec null", () => {
  const s = splitRichBlocks("```chart\n{nope\n```");
  expect(s).toEqual([{ kind: "chart", spec: null, source: "{nope" }]);
});
it("mermaid block", () => expect(splitRichBlocks("```mermaid\nflowchart LR\nA-->B\n```"))
  .toEqual([{ kind: "mermaid", source: "flowchart LR\nA-->B" }]));
it("an unclosed chart fence (still streaming) stays markdown, never a parse error", () => {
  const s = splitRichBlocks('x\n```chart\n{"type":"ba');
  expect(s).toEqual([{ kind: "md", text: 'x\n```chart\n{"type":"ba' }]);
});
it("fence language is case-insensitive", () => expect(splitRichBlocks(`\`\`\`CHART\n${CH}\n\`\`\``)[0].kind).toBe("chart"));
it("other fences pass through as markdown", () =>
  expect(splitRichBlocks("```bash\nls\n```")).toEqual([{ kind: "md", text: "```bash\nls\n```" }]));

it("chart validation", () => {
  expect(parseChartSpec(CH)?.type).toBe("bar");
  expect(parseChartSpec('{"type":"radar","x":[1],"series":[{"name":"a","data":[1]}]}')).toBeNull();   // unknown type
  expect(parseChartSpec('{"type":"line","x":[1,2],"series":[{"name":"a","data":[1]}]}')).toBeNull();  // length mismatch
  expect(parseChartSpec('{"type":"pie","x":["a"],"series":[{"name":"a","data":[1]},{"name":"b","data":[2]}]}')).toBeNull(); // pie: one series
  expect(parseChartSpec('{"type":"pie","x":["a"],"series":[{"name":"a","data":[-1]}]}')).toBeNull();  // pie: no negatives
  expect(parseChartSpec('{"type":"bar","x":[],"series":[]}')).toBeNull();
  expect(parseChartSpec('{"type":"line","x":[1,2],"series":[{"name":"a","data":[1,null]}]}')?.series[0].data).toEqual([1, null]);
});
it("mermaid source guard strips init directives", () => {
  expect(mermaidSource('%%{init: {"securityLevel":"loose"}}%%\nflowchart LR\nA-->B')).toBe("flowchart LR\nA-->B");
});
```

  Add to `renderMarkdown.test.ts`:
  - with `{ copyButtons: true }`, the output for a fenced block contains exactly one `data-md-copy` button;
  - without the option, the output is identical to today's.

- [ ] **Step 2: Run the tests and watch them fail**

  Run `npx vitest --run src/__tests__/richBlocks.test.ts src/__tests__/renderMarkdown.test.ts`. Expected: cannot resolve `@/lib/richBlocks`.

- [ ] **Step 3: Implement it**

  - **Segmenting.** `splitRichBlocks` walks lines with the same fence rule as `renderMarkdown`: a line whose `trimStart()` begins with ```` ``` ```` toggles.
    - A `chart` or `mermaid` fence that closes becomes its own segment.
    - An unclosed one, and every other fence, stays in the surrounding `md` text.
    - Adjacent `md` text is merged.
  - **Chart validation.** `parseChartSpec` returns `null` on any rule above, on more than `CHART_LIMITS`, or on non-finite numbers.
  - **Mermaid guard.** `mermaidSource` removes every `%%{ … }%%` directive, multi-line ones included, and trims.
  - **Copy markup.** `renderMarkdown`'s `{ copyButtons }` wraps each `<pre class="md-pre">` in `<div class="md-pre-wrap">` with a `<button type="button" class="md-copy" data-md-copy aria-label="Copy">`.

- [ ] **Step 4: Run the tests and watch them pass**

  Run the Step 2 command. Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add src/agenticops/web/frontend/src/lib/richBlocks.ts src/agenticops/web/frontend/src/lib/renderMarkdown.ts \
  src/agenticops/web/frontend/src/__tests__/richBlocks.test.ts src/agenticops/web/frontend/src/__tests__/renderMarkdown.test.ts
git commit -m "feat(chat/web): find chart and mermaid blocks in an answer, validate chart data, guard mermaid source"
```

---

### Task 6: Rich answer components (charts, flowcharts, zoom, code copy)

Load the `dataviz` skill before writing `ChartBlock`.

**Files:**
- Modify: `src/agenticops/web/frontend/package.json` + `package-lock.json`. Run `npm install mermaid@^11` in `src/agenticops/web/frontend`.
- Create, in `src/agenticops/web/frontend/src/components/chat/rich/`:
  - `RichContent.tsx`
  - `ChartBlock.tsx`
  - `MermaidBlock.tsx`
  - `ZoomDialog.tsx`
- Create: `src/agenticops/web/frontend/src/lib/mermaidCache.ts`
- Modify: `src/agenticops/web/frontend/src/index.css` (`.md-pre-wrap` / `.md-copy` styles, both themes)
- Test: `src/agenticops/web/frontend/src/__tests__/mermaidCache.test.ts`

**Interfaces:**
- Consumes: Task 5's `splitRichBlocks`, `parseChartSpec`, `mermaidSource` and `renderMarkdown(md, { copyButtons: true })`.
- Produces:
  - `<RichContent text: string; streaming?: boolean; cacheKey?: string | number />`. It renders the segments: md through `renderMarkdown` with copy buttons; when `cacheKey` is set and not streaming, cached per (cacheKey, segment index), like `markdownCache`.
  - `renderMermaidCached(source: string, theme: "light" | "dark", render: (id: string, src: string) => Promise<string>): Promise<string>`, with one render per (source, theme), plus `mermaidCacheSize(): number` for the test.
  - `<ZoomDialog title: string; onClose(): void; children />`: a portal to `document.body`, `animate-[slideInRight_0.2s_ease-out]`, ESC closes, and − / + / fit controls that scale the content.

- [ ] **Step 1: Write the failing cache test**

```ts
it("renders a source once per theme, even when asked concurrently", async () => {
  const render = vi.fn(async (_id: string, src: string) => `<svg>${src}</svg>`);
  const [a, b] = await Promise.all([renderMermaidCached("A-->B", "light", render), renderMermaidCached("A-->B", "light", render)]);
  expect(a).toBe(b); expect(render).toHaveBeenCalledTimes(1);
  await renderMermaidCached("A-->B", "dark", render); expect(render).toHaveBeenCalledTimes(2);
});
it("a failed render is not cached", async () => {
  const bad = vi.fn(async () => { throw new Error("parse"); });
  await expect(renderMermaidCached("x", "light", bad)).rejects.toThrow();
  await expect(renderMermaidCached("x", "light", bad)).rejects.toThrow();
  expect(bad).toHaveBeenCalledTimes(2);
});
```

- [ ] **Step 2: Run the test and watch it fail**

  Run `npx vitest --run src/__tests__/mermaidCache.test.ts`. Expected: cannot resolve `@/lib/mermaidCache`.

- [ ] **Step 3: Implement the cache, then the components**

  - **`mermaidCache`.** A `Map<string, Promise<string>>` keyed by `${theme}\u0000${source}`. A rejected promise is deleted.
  - **`MermaidBlock`.**
    - Load mermaid with `const { default: mermaid } = await import("mermaid")`, inside the effect only.
    - Call `mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: dark ? "dark" : "default" })` before each render.
    - Read the theme from `document.documentElement.classList.contains("dark")`.
    - Render `mermaidSource(source)` with an id `m-<hash>`, and insert the SVG into the DOM.
    - Reserve `min-h-[120px]` until rendered.
    - On error, show the source as a `pre` plus the notice `chat.rich.mermaidFailed`.
    - Wrap the SVG in a horizontal-scroll box; a click opens `ZoomDialog`.
  - **`ChartBlock`.**
    - Fixed height 260 px. Inside a recharts `ResponsiveContainer`, use bar / line / area / pie per `spec.type`.
    - Show the title above and the unit in the tooltip and axis.
    - Use an 8-colour palette chosen with the dataviz skill, readable in both themes.
    - A click opens `ZoomDialog`, which shows the chart at 480 px.
    - `spec === null` shows the source as a `pre` plus `chat.rich.chartInvalid` («图表数据无法解析» / "Chart data could not be read").
  - **`RichContent`.** It owns the copy click: delegated on `[data-md-copy]`, it copies the sibling `pre`'s `textContent`.
    - Try `navigator.clipboard.writeText` first, then fall back to a hidden `textarea` with `execCommand("copy")`, because http origins have no clipboard API.
    - The button shows «已复制» for 1.5 s.
  - **Locale keys** (en + zh): `chat.rich.chartInvalid`, `chat.rich.mermaidFailed`, `chat.rich.zoomIn`, `chat.rich.zoomOut`, `chat.rich.zoomFit`, `chat.rich.copy`, `chat.rich.copied`, `chat.rich.enlarge`.

- [ ] **Step 4: Run the test and check the bundle**

  1. Run `npx vitest --run src/__tests__/mermaidCache.test.ts src/__tests__/locales.test.ts`.
  2. Run `npx tsc --noEmit`.
  3. Run `npm run build`.
  4. Run `ls dist/assets | grep -i mermaid`, then `grep -l "securityLevel" dist/assets/index-*.js`.

  Expected:
  - the tests pass and tsc exits 0;
  - the build has one or more separate mermaid chunks;
  - the entry chunk does NOT contain mermaid. The grep must find nothing in `index-*.js`.

- [ ] **Step 5: Commit**

```bash
git add src/agenticops/web/frontend/package.json src/agenticops/web/frontend/package-lock.json \
  src/agenticops/web/frontend/src/components/chat/rich src/agenticops/web/frontend/src/lib/mermaidCache.ts \
  src/agenticops/web/frontend/src/index.css src/agenticops/web/frontend/src/locales/en.json \
  src/agenticops/web/frontend/src/locales/zh.json src/agenticops/web/frontend/src/__tests__/mermaidCache.test.ts
git commit -m "feat(chat/web): answers render charts (recharts) and flowcharts (lazy mermaid, strict), zoomable; code blocks copy"
```

---

### Task 7: The message column (layout, work-steps block, action row, «下一步», back to bottom)

Load the `frontend-design` skill first.

**Files:**
- Create, in `src/agenticops/web/frontend/src/`:
  - `components/chat/WorkSteps.tsx`
  - `components/chat/MessageActions.tsx`
  - `lib/messageActions.ts`
  - `lib/toolLabels.ts`
- Modify, in `src/agenticops/web/frontend/src/components/chat/`:
  - `MessageList.tsx`
  - `SuggestionChips.tsx`
  - `TokenMetrics.tsx` (inline variant only if needed)
- Modify: `src/agenticops/web/frontend/src/pages/Chat.tsx` (passes `onRegenerate` and `onSaveReport`)
- Modify: the locales.
- Delete: `src/agenticops/web/frontend/src/components/chat/ToolCallChip.tsx`, after `grep -rn ToolCallChip src` shows no other user.
- Test:
  - `src/agenticops/web/frontend/src/__tests__/messageActions.test.ts`
  - `src/agenticops/web/frontend/src/__tests__/toolLabels.test.ts`

**Interfaces:**
- Consumes: Task 4's `splitWork` and `workTotals`; Task 6's `RichContent`.
- Produces:
  - `canRegenerate(messages: ChatMessage[], index: number, streaming: boolean): { ok: true; text: string } | { ok: false; reason: "not_last" | "streaming" | "attachments" | "no_question" }`
  - `toolLabelKey(name: string): string | null`. It returns `chat.tool.<name>` for the known names and `null` otherwise, so the caller shows the raw name. Known names:
    - `scan_agent`, `detect_agent`, `rca_agent`, `sre_agent`, `sre_query`, `executor_agent`, `reporter_agent`, `review_change`;
    - `enhanced_task`, `run_kubectl`, `run_aws_cli_readonly`, `run_on_host`.
  - `formatDuration(ms: number): string`: `850 ms` → `"0.9 秒"`-style via the locale key `chat.work.seconds`, and minutes above 60 s (`chat.work.minutes`). It lives in `lib/workSteps.ts`; its test goes in `workSteps.test.ts`.

- [ ] **Step 1: Write the failing tests**

```ts
const u = (o = {}) => ({ id: 1, role: "user", content: "q", created_at: "", ...o }) as ChatMessage;
const a = (o = {}) => ({ id: 2, role: "assistant", content: "ans", created_at: "", ...o }) as ChatMessage;
it("only the last answer, with its question's text", () => {
  expect(canRegenerate([u(), a()], 1, false)).toEqual({ ok: true, text: "q" });
  expect(canRegenerate([u(), a(), u({ id: 3 }), a({ id: 4 })], 1, false)).toEqual({ ok: false, reason: "not_last" });
});
it("not while streaming, not after a question with attachments, not without a question", () => {
  expect(canRegenerate([u(), a()], 1, true)).toEqual({ ok: false, reason: "streaming" });
  expect(canRegenerate([u({ attachments: [{ id: "x", filename: "f", size: 1, kind: "image" }] }), a()], 1, false))
    .toEqual({ ok: false, reason: "attachments" });
  expect(canRegenerate([a()], 0, false)).toEqual({ ok: false, reason: "no_question" });
});
it("tool labels", () => {
  expect(toolLabelKey("rca_agent")).toBe("chat.tool.rca_agent");
  expect(toolLabelKey("get_health_issue")).toBeNull();
});
```

  Add to `workSteps.test.ts`: `formatDuration` cases for 850, 52_000 and 125_000 ms, using a `t` that returns the key with `{n}` filled in.

- [ ] **Step 2: Run the tests and watch them fail**

  Run `npx vitest --run src/__tests__/messageActions.test.ts src/__tests__/toolLabels.test.ts src/__tests__/workSteps.test.ts`. Expected: module or function not found.

- [ ] **Step 3: Implement the helpers, then the components**

  **`WorkSteps`** takes `{ tools, content, live }`. It calls `splitWork`.
  - **Header while running:** a spinner with «正在处理 · 第 N 步».
  - **Header when done:** «已处理 N 步 · T» (T from `workTotals` / `formatDuration`), or «已处理 N 步» when `ms` is null.
  - **Open state.** Open while live; collapsed by default once done; the user's toggle wins.
  - **Each tool row:**
    - a status icon (running spinner / ✓ ok / ✕ error / ? unknown);
    - the label (the locale key, else the raw name in mono);
    - the summary (mono, muted, truncated with a `title`);
    - the duration.

    A row with a `result_preview` expands to show it.
  - **Text rows:** the narration in muted small text.
  - **Hidden** when there are no tools.

  **`MessageList`:**
  - **Centered column.** Rows sit inside `max-w-[760px] mx-auto px-4`.
  - **User message.** A right-aligned bubble `bg-muted rounded-3xl px-4 py-2.5 max-w-[85%]`, with attachments above the text as today.
  - **Assistant message.** Flat: no avatar, no bubble. In order:
    - `WorkSteps`;
    - `RichContent` with the answer (`cacheKey = msg.id`);
    - the status notice as today;
    - `MessageActions`;
    - on the last message only, `SuggestionChips`.
  - **Streaming trailer.** The same pieces with `live`, `RichContent streaming` and the caret. The «Thinking» indicator stays for the moment before the first token or tool.
  - **Back to bottom.**
    - Show a round «↓» button (`chat.jumpToBottom`) when the scroll is more than 200 px from the bottom; a click smooth-scrolls down and sticks again.
    - A `ResizeObserver` on the virtual inner container keeps the view at the bottom while stuck, which covers charts or mermaid growing a row.
  - **Empty state.** Remove the English «Start a conversation» block. An open session with no messages shows nothing; the welcome page is Task 9.

  **`MessageActions`** takes `{ msg, answer, canRegen, onRegenerate, onSaveReport, readOnly }`.
  - **Copy.** Copies the answer markdown.
  - **Regenerate.**
    - Disabled with a `title` from `chat.regen.<reason>` when `!ok`. For attachments: «附件已随原消息发送，请重新附加后再发».
    - Hidden for `not_last` and `no_question`.
    - Calls `onRegenerate(text)`.
  - **⋯ menu** (Radix DropdownMenu):
    - «存为报告», hidden when `readOnly`: calls `onSaveReport`, which opens the existing `SaveReportDialog`;
    - «复制为纯文本»: the answer node's `innerText`.
  - **Token metrics.** `TokenMetrics` sits at the right end of the row.

  **`SuggestionChips`.** A muted «下一步» label above rounded chips with a leading «↳». A click sends, as today.

  **`Chat.tsx`.** Pass `onRegenerate={(text) => sendMessage(text)}` and `onSaveReport={() => setShowSaveReport(true)}` to `MessageList`.

  **Locale keys** (en + zh):
  - `chat.work.running`, `chat.work.done`, `chat.work.doneNoTime`, `chat.work.seconds`, `chat.work.minutes`;
  - `chat.tool.<name>` for each known name;
  - `chat.actions.copy`, `chat.actions.copied`, `chat.actions.regenerate`, `chat.actions.more`, `chat.actions.saveReport`, `chat.actions.copyPlain`;
  - `chat.regen.attachments`, `chat.regen.streaming`;
  - `chat.nextSteps`, `chat.jumpToBottom`.

- [ ] **Step 4: Run the tests, tsc and the build**

  Run `npx vitest --run` (whole suite), `npx tsc --noEmit` and `npm run build`. Expected: all green, exit 0.

- [ ] **Step 5: Commit**

  Use `git add` with each path above, including the deleted `ToolCallChip.tsx` via `git rm`. Then:

  `git commit -m "feat(chat/web): ChatGPT-style message column — work-steps block, rich answers, actions, next steps, back to bottom"`

---

### Task 8: The composer (attachments inside the box, ＋ menu, keys, drop anywhere)

**Files:**
- Create, in `src/agenticops/web/frontend/src/`:
  - `lib/composerKeys.ts`
  - `lib/attachmentBadge.ts`
  - `components/chat/ComposerAttachment.tsx`, which replaces `AttachmentTray` + `AttachmentCard` in the composer
- Modify, in `src/agenticops/web/frontend/src/`:
  - `components/chat/ChatInput.tsx`
  - `pages/Chat.tsx` (drop target + hint)
  - the locales
- Delete: `src/agenticops/web/frontend/src/components/chat/AttachmentTray.tsx` and `AttachmentCard.tsx`, once nothing imports them (`grep -rn "AttachmentTray\|AttachmentCard" src`).
- Test:
  - `src/agenticops/web/frontend/src/__tests__/composerKeys.test.ts`
  - `src/agenticops/web/frontend/src/__tests__/attachmentBadge.test.ts`

**Interfaces:**
- Produces:
  - `shouldSend(e: { key: string; shiftKey: boolean; metaKey: boolean; ctrlKey: boolean; isComposing: boolean; keyCode?: number }, coarsePointer: boolean): boolean`
  - `attachmentBadge(name: string): { label: string; tone: "pdf" | "sheet" | "doc" | "slide" | "image" | "text" | "archive" | "other" }`. The label is the upper-case extension, at most 4 characters.
  - `ChatInput` new props:
    - `dropTargetRef?: React.RefObject<HTMLElement>`: drag listeners attach there, else to its own box;
    - `onDragChange?: (dragging: boolean) => void`;
    - `layout?: "dock" | "center"`: `center` = the welcome page's centered composer.

- [ ] **Step 1: Write the failing tests**

```ts
const k = (o = {}) => ({ key: "Enter", shiftKey: false, metaKey: false, ctrlKey: false, isComposing: false, ...o });
it("Enter sends on desktop; Shift+Enter is a newline", () => {
  expect(shouldSend(k(), false)).toBe(true);
  expect(shouldSend(k({ shiftKey: true }), false)).toBe(false);
});
it("never while an IME is composing (incl. Safari keyCode 229)", () => {
  expect(shouldSend(k({ isComposing: true }), false)).toBe(false);
  expect(shouldSend(k({ keyCode: 229 }), false)).toBe(false);
});
it("touch: Enter is a newline, Cmd/Ctrl+Enter still sends", () => {
  expect(shouldSend(k(), true)).toBe(false);
  expect(shouldSend(k({ metaKey: true }), true)).toBe(true);
});
it("other keys never send", () => expect(shouldSend(k({ key: "a" }), false)).toBe(false));

it("badges by type", () => {
  expect(attachmentBadge("Q3.PDF")).toEqual({ label: "PDF", tone: "pdf" });
  expect(attachmentBadge("m.xlsx").tone).toBe("sheet");
  expect(attachmentBadge("m.csv").tone).toBe("sheet");
  expect(attachmentBadge("a.docx").tone).toBe("doc");
  expect(attachmentBadge("s.pptx").tone).toBe("slide");
  expect(attachmentBadge("x.heic").tone).toBe("image");
  expect(attachmentBadge("app.log").tone).toBe("text");
  expect(attachmentBadge("setup.exe")).toEqual({ label: "EXE", tone: "other" });
  expect(attachmentBadge("README").label).toBe("FILE");
});
```

- [ ] **Step 2: Run the tests and watch them fail**

  Run `npx vitest --run src/__tests__/composerKeys.test.ts src/__tests__/attachmentBadge.test.ts`. Expected: module not found.

- [ ] **Step 3: Implement the helpers, then the composer**

  **Tones → classes:**

  | Tone | Badge colour |
  |---|---|
  | `pdf` | red-500 |
  | `sheet` | green-600 |
  | `doc` | blue-600 |
  | `slide` | orange-500 |
  | `image` | sky-500 |
  | `text` | slate-500 |
  | `archive` | amber-600 |
  | `other` | gray-400 |

  **`ComposerAttachment`** takes an `UploadItem`, or a rejected entry `{ name, text }`:
  - **Image.** A 60 px square thumbnail (local preview, or the server thumb as today).
    - While uploading or processing: a dark overlay with a circular progress ring (SVG). Uploading shows `item.progress`; processing shows an indeterminate spinning arc.
    - On failure: a red tint, the reason in the `title` and a retry.
    - ✕ at the top right, shown on hover on desktop and always on touch.
  - **Document.** A card at least 150 px wide: the coloured badge, the name, and either «n 页 · size» or the status line (processing / failed reason in red), plus ✕.
  - **Rejected.** A red card with the error text (`attachmentErrorText`) and ✕.

  **`ChatInput` layout:** one rounded box `rounded-3xl border shadow`. Inside it, top to bottom:
  1. **Attachment row.** `flex-wrap` on desktop, horizontal scroll on narrow screens (`max-[767px]:flex-nowrap overflow-x-auto`).
  2. **Textarea.** It auto-grows as today, up to `max-h-52`.
  3. **Bottom bar:**
     - «＋» opens a DropdownMenu with «上传文件» (the existing file input), «上传图片» (`accept="image/*"`) and, only on `(pointer: coarse)`, «拍照» (`accept="image/*" capture="environment"`);
     - the counter `chat.attach.counter`, shown only when there are attachments;
     - the `ModelSelector`;
     - send / stop.

  **Other composer behaviour:**
  - **Image preview.** Clicking a ready image thumbnail (it has a `serverId`) opens the existing `ImageLightbox` over the composer's ready images, starting at that one. This is the spec's «输入框里的新缩略图，同样能点开».
  - **Rejected files.** `validateFiles` errors become local rejected cards; the old one-line `attachError` goes. A card disappears on ✕, or when the message is sent.
  - **Keys.** `onKeyDown` uses `shouldSend(e.nativeEvent, coarse)`. `coarse` comes from `matchMedia("(pointer: coarse)")` via the existing `useMediaQuery`.
  - **Placeholder.** `chat.input.placeholder` becomes «问点什么……（可粘贴截图、拖入文件）» / "Ask anything… (paste a screenshot or drop files)"; the «Cmd/Ctrl+Enter 发送» hint goes.
  - **Send disabled.** The existing rule stays: disabled while uploading or processing, or when there is nothing to send.

  **Drop target.**
  - `Chat.tsx` passes the chat column's ref as `dropTargetRef` and keeps `dragging` state from `onDragChange`.
  - While dragging, it renders over the column: `pointer-events-none absolute inset-3 rounded-2xl border-2 border-dashed border-primary/60 bg-primary/5`, with a centered pill «放下即可添加» (`chat.attach.dropHint`).
  - The existing capture-phase listeners and cleanup move unchanged onto the target element.

  **Locale keys:** `chat.attach.menu`, `chat.attach.files`, `chat.attach.images`, `chat.attach.camera`, `chat.attach.dropHint`, and the `chat.input.placeholder` value.

- [ ] **Step 4: Run the tests, tsc and the build**

  Run `npx vitest --run`, `npx tsc --noEmit` and `npm run build`. Expected: green, exit 0.

- [ ] **Step 5: Commit**

  Use `git add` / `git rm` with each path above. Then:

  `git commit -m "feat(chat/web): attachments live inside the composer; ＋ menu, Enter to send (IME-safe), drop anywhere in the chat"`

---

### Task 9: Page shell, welcome page and mobile

**Files:**
- Modify, in `src/agenticops/web/frontend/src/`:
  - `components/layout/AppShell.tsx`
  - `components/layout/Sidebar.tsx` (rail variant)
  - `pages/Chat.tsx`
  - `components/chat/ImageLightbox.tsx` (swipe)
- Modify: `src/agenticops/web/frontend/index.html` (`viewport-fit=cover`)
- Modify: the locales.
- Create: `src/agenticops/web/frontend/src/lib/swipe.ts`
- Test: `src/agenticops/web/frontend/src/__tests__/swipe.test.ts`, plus a rail-route case in `__tests__/navGroups.test.ts`.

**Interfaces:**
- Produces:
  - `swipeStep(dx: number, dy: number, threshold?: number): -1 | 0 | 1`. Default threshold 50. A horizontal swipe left = +1 (next), right = −1 (previous). Vertical-dominant or short = 0.
  - `isRailRoute(pathname: string): boolean`, true for `/app/chat` and `/app/chat/*`. It goes in `lib/navGroups.ts`.

- [ ] **Step 1: Write the failing tests**

```ts
it("swipe", () => {
  expect(swipeStep(-80, 10)).toBe(1); expect(swipeStep(80, 5)).toBe(-1);
  expect(swipeStep(-30, 0)).toBe(0); expect(swipeStep(-80, 120)).toBe(0);
});
it("rail routes", () => {
  expect(isRailRoute("/app/chat")).toBe(true); expect(isRailRoute("/app/chat/abc")).toBe(true);
  expect(isRailRoute("/app/chats")).toBe(false); expect(isRailRoute("/app/issues")).toBe(false);
});
```

- [ ] **Step 2: Run the tests and watch them fail**

  Run `npx vitest --run src/__tests__/swipe.test.ts src/__tests__/navGroups.test.ts`. Expected: not found / not exported.

- [ ] **Step 3: Implement the helpers, then the shell and pages**

  **Shell rail (≥ 801 px, chat routes only):**
  - `AppShell` gives `Sidebar` a `rail` prop. The content wrapper switches `pl-[166px]` / `pl-[200px]` to `pl-[56px]`.
  - The rail is 56 px wide: the logo icon, the visible nav items as icon buttons (title = label, active state), group separators, and an «展开导航» button at the bottom.
  - That button opens the full 200 px sidebar as an overlay: fixed, z-40, with a scrim, `slideInRight`, closed by ESC or a click outside.
  - Other routes are unchanged.

  **Chat list:**
  - **Desktop (≥ 768 px).** The existing resizable flyout container, open by default: `usePersistedState("aiops-chat-list-open", true)` replaces `useState(false)`. The header button toggles it.
  - **Mobile (< 768 px).** The same button opens `SessionFlyout` in a left drawer: Radix Dialog, `w-[85vw] max-w-[320px]`, `slideInRight`, ESC closes. Picking a chat or «新对话» closes the drawer.

  **Header.** Keep the session name and link as today. On mobile, the menu button is at the left.

  **Welcome page:**
  - The heading is `chat.welcome`, whose value changes to «今天要排查什么？» / "What are we troubleshooting today?". The hint stays.
  - ≥ 768 px: the composer (`layout="center"`) sits under the heading, inside the centered block, with the starter chips below it.
  - < 768 px: the heading and chips are centered, and the composer docks at the bottom.

  **Mobile viewport:**
  - The page height uses `100dvh` instead of `100vh` (`h-[calc(100dvh-var(--topbar-h))]`).
  - The docked composer gets `pb-[max(env(safe-area-inset-bottom),0.75rem)]`.
  - `index.html` viewport gets `viewport-fit=cover`.

  **`ImageLightbox`.** `onTouchStart` / `onTouchEnd` call `swipeStep` → `onIndex`. On mobile, the image fills the width.

  **Charts and flowcharts on mobile.** Charts stay 100 % wide. Flowcharts scroll horizontally inside their box; `ZoomDialog` is full screen below 768 px.

- [ ] **Step 4: Run the tests, tsc and the build**

  Run `npx vitest --run`, `npx tsc --noEmit` and `npm run build`. Expected: green, exit 0.

- [ ] **Step 5: Commit**

  Use `git add` with each path above. Then:

  `git commit -m "feat(chat/web): icon rail on Chat, chat list open by default (drawer on mobile), centered welcome composer, mobile viewport"`

---

### Task 10: Gates and live E2E

Nothing is pushed in this task.

**Files:**
- Create: `docs/MVP-2.7.1-CHAT-E2E-REPORT.md`, holding the evidence: the commands, their results, and the screenshots under `docs/assets/chat-e2e-2026-11-07/`.

- [ ] **Step 1: Full test gates**

  1. Run `.superpowers/aiops-pytest.sh /tmp/full.log tests/`.
     Expected: the baseline 7339 passed, plus the new tests; the only failure is the known DNS one (`test_web_tools`).
  2. Run `npx vitest --run`. Expected: every file passes.
  3. Run `npx tsc --noEmit`. Expected: exit 0.

- [ ] **Step 2: Clean build in an empty directory**

  This catches `/Users/malibo/node_modules` leaking in.

  1. `git archive HEAD src/agenticops/web/frontend tests/fixtures | tar -x -C /tmp/chat-clean-XXXX`
  2. `npm ci && npm run build` there.

  Expected: exit 0, with a mermaid chunk present.

- [ ] **Step 3: Restart the local service on the new build**

  Run `npm run build` in the frontend, then `aiops service restart && aiops service status`. Expected: running, and `/api/health` returns 200.

- [ ] **Step 4: Desktop E2E with Playwright, on the real model**

  Use a new session for each scenario, and take a screenshot of each.

  1. **Statistics question.** Ask «过去 7 天各严重级别的告警数分别是多少？画成图» (any real counts from the platform).
     Expected:
     - a rendered chart (`svg.recharts-surface`), with no ASCII art;
     - a work-steps block that runs live, then collapses to «已处理 N 步 · T»;
     - the «下一步» chips.
  2. **Flow question.** Ask «画出告警进来到自动修复的处理流程».
     Expected: a mermaid SVG renders, and a click opens the zoom dialog; ESC closes it.
  3. **Markdown table.** A table answer renders as a table.
  4. **Refresh.** Reload the page, then expand the work steps. Each step shows the same summary, duration and result preview as before the reload, read from the DB.
  5. **Redaction.** Ask the agent to run `kubectl get ns --token=FAKE-TOKEN-1234567` on a lab cluster (fake token; the command may fail).
     Expected:
     - the step summary shows `--token=[REDACTED-SECRET]`;
     - `sqlite3 data/agenticops.db "select tool_calls from chat_messages order by id desc limit 1"` (or the configured DB) does not contain `FAKE-TOKEN`.
  6. **Drop anywhere.** Drag a PNG, a PDF, an XLSX and an EXE onto the middle of the message area. Use Playwright `browser_drop`, or `browser_run_code_unsafe` with a `DataTransfer`.
     Expected:
     - the light hint appears;
     - after the drop the files sit inside the composer, as a thumbnail with a ring, a red PDF card and a green XLSX card;
     - the EXE is a red card with the reason;
     - send stays disabled until processing ends.
  7. **Keys.** Enter sends, and Shift+Enter makes a newline. In `browser_run_code_unsafe`, dispatch a `keydown` Enter with `isComposing: true`; nothing is sent.
  8. **Back to bottom.** Scroll up in a long answer; the «↓» button appears, and a click returns to the bottom.
  9. **Regenerate.** On the last answer, a new answer appears below. On an answer whose question had an attachment, the button is disabled with the attachments tooltip.
  10. **Dark mode.** Switch the theme and screenshot a chart and a flowchart.

- [ ] **Step 5: Mobile E2E (Playwright `browser_resize` 390×844)**

  Check each:
  - the drawer opens and closes, and picking a chat closes it;
  - the composer stays at the bottom, and attachments scroll horizontally inside it;
  - the «＋» menu shows its items;
  - a chart fits the width;
  - a flowchart scrolls horizontally;
  - the lightbox changes image on a synthetic touch swipe (`browser_run_code_unsafe` dispatching `touchstart` / `touchend`);
  - every primary button has at least a 40 px hit box (`getBoundingClientRect`).

  The camera item shows only on a coarse pointer. Resize cannot emulate that, so record it as not checked here.

- [ ] **Step 6: Performance and lazy loading**

  1. Seed a throwaway session with 200 messages (tables and charts in the answers) through a short script on the local DB. Record the session id.
  2. Scroll it top to bottom in Playwright. Expected: no row overlaps, and the bottom stays stuck.
  3. With `browser_network_requests`, open a chat that has no mermaid. Expected: no `mermaid` chunk is requested.
  4. Delete the seeded session with `DELETE /api/chat/sessions/{id}`.

- [ ] **Step 7: The plain channels stay plain**

  Run `aiops chat "过去 7 天每天的告警数是多少？"` (CLI, headless). Expected: the answer contains no ```` ```chart ```` and no ```` ```mermaid ````.

- [ ] **Step 8: Write the report and commit it**

  Write `docs/MVP-2.7.1-CHAT-E2E-REPORT.md`: each step, PASS or FAIL, the evidence, and anything not checked (with the reason). Then commit it with its screenshots by explicit path.

  A failing step stops here. Fix it with systematic-debugging plus a failing test first, then rerun this task from Step 1.

---

### Task 11: Docs

**Files:** `docs/MVP-2.7.1-RELEASE.md`, `README.md`, `README_CN.md`, `CLAUDE.md`, `docs/WORKFLOW.md`

- [ ] **Step 1: Update each file**

  - **`docs/MVP-2.7.1-RELEASE.md`.**
    - A scope row and a new section «ChatGPT 风格的 Web Chat». What it does, the six reachable surfaces exactly as the spec's table, the rulings above, and the gates (the test counts from Task 10).
    - A link to the E2E report.
    - An upgrade note: `npm ci` (new dependency `mermaid`), rebuild the frontend, restart.
  - **`README.md` / `README_CN.md`.** The same one-row addition in the 2.7.1 release-history row, and in the feature list where Chat is described. Paragraphs and rows match one to one, with the same links.
  - **`CLAUDE.md`.**
    - Backend: in the Web module row, the SSE frames `tool_start.text_offset`, `tool_input`, and `tool_end.{duration_ms, result_preview, text_end}`; `chat/tool_steps.py` and its display-only redaction.
    - The main agent's `rich_output` (Web chat only).
    - Frontend: `lib/workSteps`, `lib/richBlocks`, `lib/mermaidCache`, `components/chat/rich/`, `WorkSteps`, `MessageActions`, `ComposerAttachment`, the rail on Chat.
    - Update the MVP-2.7.1 paragraph.
  - **`docs/WORKFLOW.md`.** In the chat section, one Mermaid diagram of a reply turning into the work timeline plus the answer plus rich segments, and a short «how to read a chat answer» tutorial.

- [ ] **Step 2: Check the docs**

  - `README.md` and `README_CN.md` changed the same rows (`git diff` side by side).
  - The CLAUDE.md file names match the tree: `ls` each path.

- [ ] **Step 3: Commit, then hand over**

```bash
git add docs/MVP-2.7.1-RELEASE.md README.md README_CN.md CLAUDE.md docs/WORKFLOW.md
git commit -m "docs(2.7.1): ChatGPT-style Web chat — release note, READMEs, CLAUDE.md, workflow"
```

  Then show the owner the E2E report and wait for their confirmation before any push.
