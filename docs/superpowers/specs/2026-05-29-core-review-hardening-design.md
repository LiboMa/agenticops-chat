# ① 核心审查与加固 — 设计文档

- **日期**: 2026-05-29
- **分支**: `Agenticops-always-memorized`
- **周期**: ① of 3（①核心审查加固 → ②记忆系统质变 → ③Skills自主化）
- **范围**: Agent 架构/提示词 + WebUI/CLI/Chat 的已验证 Bug 修复、低风险优化、结构性重构（大文件拆分）
- **不含**: 记忆系统的能力升级（→②）、Skills 自主化架构（→③）

---

## 1. 背景与目标

对 AgenticOps 的 7-agent 架构、提示词组装、WebUI/CLI/Chat 链路做全面检查，修复潜在 Bug 并提升优化点，为后续 ②记忆 / ③Skills 的质变打下稳固地基。

所有发现经过**对抗式验证**（24 候选 → 19 confirmed / 2 partial / 3 refuted）。本文档只包含**已对照真实源码确认**的项，被推翻的不修。

### 验收成功标准（可量化）
1. 18 个确认问题全部修复或明确归档，每个修复配最小回归测试。
2. `app.py`（6476 行）拆为主文件 + ~19 router 模块；`main.py`（4918 行）拆为 main + renderers/slash/service/commands/dispatch。
3. 全程 `py_compile` + `tsc --noEmit` + 现有 `pytest` 全绿 + `uvicorn` 启动 `/api/health` 返回非 5xx。
4. 拆分为**纯机械移动**：零逻辑变更，每个模块独立 commit，diff 可逐一审查。

---

## 2. 验证结论：被推翻的候选（不修）

| 候选 | 推翻证据 |
|------|----------|
| executor 不加载 memory | `executor_agent.py:212` 确实传 `agent_name="executor"`，memory 正常注入 |
| 消息截断无提示 | `session_manager.py:157-158` 截断会追加可见标记 `\n... (truncated)` |
| focus_section 提示注入 | 输入经 `VALID_SCAN_FOCUS` 校验 + 常量字典映射，无法注入 |
| stream 仍用默认 boto 链 | 已在凭证存储周期修复（`boto_session=get_bedrock_boto_session()`） |

---

## 3. 确认问题清单与修复方案

### 3.1 高优先级 — Streaming 与数据一致性

#### F1. `stream-error-partial`（high / 高回归风险）
- **现象**: `app.py:5659-5670` stream 中途异常时持久化半截文本，`input_tokens/output_tokens` 仍为初始 0；user 消息已在 `5549` 写入，无回滚。
- **方案（轻量 — pending 标记，已选）**:
  - **不加 DB 列**（`ChatMessage` 现有 `token_usage` JSON nullable，无 `status` 列）。失败时在 assistant 消息的 `token_usage` JSON 写入 `{"error": "<摘要>", "input": ..., "output": ...}` 作为错误元数据；或在 `content` 末尾追加明确的失败标记。避免触及 migration（超范围）。
  - user 消息**保留**（便于用户重试），不改事务边界。
  - SSE `error` 事件携带可读错误，前端区分"失败"与"完成"。
- **回归测试**: mock `stream_async` 在中途 `raise`，断言 (a) user 消息留存 (b) assistant 消息携带错误元数据 (c) 不抛未捕获异常。

#### F2. `cli-slash-no-persist`（high）
- **现象**: `main.py:4174-4189` slash 命令提前 `continue`，跳过 `_cli_persist_message`；agent 消息却在 `4267` 持久化 → CLI 历史不一致。
- **方案**: 在 slash 分支 `continue` 前，持久化 user 输入 + 命令结果（`role="system"` 或 `"assistant"`，与 Web `/channel`、`/send_to` 路径一致）。
- **回归测试**: 执行一个返回字符串的 slash 命令，断言 DB 出现 user + system 两条记录。

#### F3. `cli-token-metric-divergence`（high）
- **现象**: REPL 用 `accumulated_usage`（`main.py:4238`）、headless 用 `latest_agent_invocation`（`main.py:3819`）、Web 用 `latest_agent_invocation`（`app.py:5592`）—— 三处口径不一。
- **方案**: 统一为 `accumulated_usage`（语义最一致：覆盖一轮里所有 sub-agent 调用）。封装单一 helper `extract_token_usage(result)`，三处共用。
- **回归测试**: 构造含多次 sub-agent 调用的 mock metrics，断言三条路径返回同一聚合值。

#### F4. `sm-tool-rebuild-fragile`（high）
- **现象**: `session_manager.py:41-93` `_rebuild_tool_messages()` 遇任何不匹配（非 list / 缺 name / 异常）整体返回 `[]`，调用方降级为文本前缀，丢失全部结构化工具上下文。
- **方案**: 改为逐条解析——有效的 tool call 重建，无效的跳过并 `logger.warning` 具体原因；仅在全空时回退文本。缺失字段给合理默认。
- **回归测试**: 喂入「部分有效 + 部分损坏」的 tool_calls JSON，断言有效条目被重建、损坏条目被跳过且有日志。

### 3.2 中优先级 — 健壮性与静默降级

#### F5. `preamble-retry-brittle`（high severity）
- **现象**: `preamble.py:179` `_TRANSIENT_MARKERS=("timed out","read timeout","connection reset","throttling")` 子串匹配，漏掉 `"timeout"`、`"service unavailable"`、`"throttled"`、`ThrottlingException` 等。
- **方案**: 优先用 botocore `ClientError.response["Error"]["Code"]` 匹配已知瞬态错误码集合（`ThrottlingException`/`ServiceUnavailable`/`RequestTimeout`/`ModelTimeoutException` 等）；保留子串匹配作兜底但扩充词表；对未匹配但最终失败的错误记日志以暴露覆盖缺口。
- **回归测试**: 参数化注入各类瞬态/非瞬态异常，断言瞬态触发重试、非瞬态直接抛出。

#### F6. `sm-memory-inject-unvalidated`（high）+ F7. `sm-memory-exc-swallow`（med）
- **现象**: `session_manager.py:490-507` memory context 仅判真值即拼接进 system_prompt，无格式校验；异常被 `except Exception` 吞掉仅 warning。
- **方案**: 注入前校验 `isinstance(str)` + 非空 + 长度上限；异常区分"检索失败可继续"（warning）与"严重错误"（error 级日志 + 指标）。
- **注**: 此项触及记忆注入，但只做**防御性加固**，不改记忆能力（能力升级归 ②）。
- **回归测试**: mock `build_memory_context` 返回非字符串 / 抛异常，断言不污染 prompt、不抛未捕获异常、日志级别正确。

#### F8. `preamble-memory-swallow`（med）
- **现象**: `preamble.py:156-159` 裸 `except Exception` 吞掉 memory 加载失败。
- **方案**: 收窄为 `except (IOError, OSError, FileNotFoundError)`（缺文件可恢复），其他异常上报 error 级。
- **回归测试**: mock `load_agent_memory` 抛 `PermissionError` 时上报 error；抛 `FileNotFoundError` 时静默继续。

#### F9. `detect-parallel-downgrade`（med）
- **现象**: `detect_agent.py:272-277` 账户加载失败裸 `except` + warning，静默降级单 agent，无指标。
- **方案**: 保留降级（可用性优先），但升级为 error 级日志 + 在结果摘要里显式标注"降级原因"，让降级可见。
- **回归测试**: mock `_load_accounts` 抛异常，断言走单 agent 路径且摘要含降级标注。

#### F10. `sm-ttl-race`（med）
- **现象**: `session_manager.py:444-462` TTL 清理在全局锁释放后才调 `_trigger_summary_and_memory`，与并发 `get_or_create` 竞态。
- **方案**: 清理时对该 session 持有 per-session 锁再触发 summary；或将 summary 任务投递到串行化队列（按 session_id 串行）。取**前者**（改动小）。
- **回归测试**: 并发触发同一 session 的清理与 `get_or_create`，断言无重复 summary、无状态错乱（用线程 + barrier 复现）。

#### F11. `stream-session-race`（med）+ F12. `stream-cancel-not-propagated`（med）
- **方案 F11**: 写 assistant 消息前复查 `ChatSession` 是否仍存在，不存在则优雅结束 SSE。
- **方案 F12**: `_generate` 事件循环内周期检查 `await request.is_disconnected()`，断开则 `break` 并停止消费 `stream_async`。
- **回归测试**: F11 删除 session 后断言写入被跳过且无 FK 异常；F12 mock 断开后断言循环提前退出。

#### F13. `agents-batch-mode-inconsistent`（med）
- **现象**: scan/detect/rca 的 `set_batch_mode` try/finally 位置与嵌套结构不一致（`detect_agent.py:265-362`/`scan_agent.py:159-206`/`rca_agent.py:193-283`）。
- **方案**: 抽 `@contextmanager batch_mode()`（进入设 True、退出必复位 False），三个 agent 统一改用 `with batch_mode():`。
- **回归测试**: 在 `with batch_mode()` 内抛异常，断言退出后 batch mode 一定复位。

### 3.3 低优先级 — 优化

#### F14. `preamble-no-cache`（low / 中回归风险）
- **现象**: `build_system_prompt()` 每次 agent 实例化重算（含 skills XML 抓取、memory 加载）。
- **方案**: 谨慎——按 `(base, include_account, include_skills, agent_type, agent_name, detail_level)` 做带失效的缓存；skills/memory 变更需失效。**先测量再决定**：若实测开销 <50ms 则降级为"仅文档说明"，不引入缓存复杂度（符合"不加没用的功能"）。
- **回归测试**: 若实现缓存——断言相同入参命中、detail_level 变化后失效。

### 3.4 设计意图澄清（不改行为）

#### F15. `detect-dual-tools-divergence`（已定：只补文档 + 断言）
- **结论**: 单 agent（多账户，带 `assume_role`/`get_active_account`）vs 并行 agent（账户锁定，预解析）是**设计意图**，非 bug。
- **方案**: 两条路径加注释说明意图；加一个测试**锁定**两条路径各自的预期工具集（防未来误改）。

### 3.5 Skills Bug（已定：提前 yaml-escape + atomic-write 到①）

#### F16. `evo-yaml-escape`（high）
- **现象**: `evolution.py:43-49,86-92` `description: "{description}"` f-string 拼 YAML，描述含引号/换行即破坏。
- **方案**: 用 `yaml.safe_dump` 生成 frontmatter，或对值用 `json.dumps`（JSON 是合法 YAML 子集）。
- **回归测试**: 描述含 `"` 和 `\n`，断言生成的 SKILL.md 能被 `yaml.safe_load` 正确解析。

#### F17. `evo-no-atomic-write`（med）
- **现象**: `evolution.py:50,93` 直接 `write_text`，崩溃留半截文件。
- **方案**: 写临时文件 + `Path.replace()` 原子重命名。
- **回归测试**: 断言写入后文件完整；（可选）mock 写中断验证不留半截。
- **注**: `evo-bedrock-parse-lenient`（partial）留给 ③（届时生成流程会重做）。

---

## 4. 结构性重构 — 大文件拆分

**执行铁律：先完成 §3 全部修复并验证通过，再开始拆分。** 拆分是纯机械移动，零逻辑变更。

### 4.1 `web/app.py`（6476 行）→ 主文件 + `web/routers/`

抽出 19 个 router（FastAPI `APIRouter`，主文件 `app.include_router`）：
`accounts, resources, issues, fix_plans, reports, schedules, notifications, knowledge_base, chat_sessions, settings, auth, audit, agent_logs, skills, search, memory, webhooks, misc`（+ 既有 graph router）。

**必须留在 `app.py`**（与单例强耦合，移出会引入循环依赖）：
- `api_send_chat_message`（streaming chat，耦合 `_chat_sessions`）
- IM 回调 `_handle_im_message` / bot 状态（耦合 `_im_sessions`）
- `lifespan` 钩子、middleware（`TraceIdFilter`/`APIAuthMiddleware`/CORS）
- 跨 router 复用的 helper 抽到 `web/helpers.py`：`_health_issue_to_anomaly_response`、`_build_account_name_map`、`_enrich_report`、`_auto_learn_dismissed`

**单例传递规则**：`_executor_service`、`_chat_sessions`、`_im_sessions` 通过 `app.state` 注入 router，**禁止** router 直接 `from app import ...`（杜绝环）。

**安全抽取顺序**（验证给出）：misc → accounts → resources → webhooks → issues → fix_plans → knowledge_base → reports → schedules → skills → search → auth → audit → agent_logs → memory → settings → notifications(仅 channel CRUD) → chat_sessions(仅 CRUD)。

### 4.2 `cli/main.py`（4918 行）→ main + 5 模块

| 新模块 | 职责 | 约行数 |
|--------|------|--------|
| `renderers.py` | output_table/json/yaml/markdown、print_with_truncation | ~150 |
| `slash.py` | 全部 `_slash_*`、`SLASH_COMMANDS`、`handle_slash_command` | ~1800 |
| `service.py` | 服务生命周期（start/stop/status/restart/logs、PID 管理） | ~330 |
| `commands.py` | 全部 Typer `@*_app.command()`、app 与子命令 typer | ~1200 |
| `dispatch.py` | `chat()` REPL、`_run_headless`、`_cli_persist_message`、`_cli_setup_db_session` | ~850 |
| `main.py`（重构后） | app 定义、logging、entry point、注册子模块 | ~600 |

**无环导入顺序**（验证给出，必须遵守）：
`context → formatters → renderers → slash → service → commands → dispatch → main`
- 铁规：**`slash.py` 绝不 import `dispatch.py`/`commands.py`**；只有 `dispatch.py` 单向 import `slash.py`。
- `console` 单例：消除 `main.py` 与 `formatters.py` 的双 console，统一到 `formatters.py`。
- `SLASH_COMMANDS` 注册表随 `_slash_*` 一起移入 `slash.py`。

### 4.3 拆分验证（每模块一 commit）
每抽出一个模块：`py_compile`（或 `tsc --noEmit` for 前端无关）→ 现有 `pytest` 全绿 → `uvicorn` 启动 `/api/health` 非 5xx → CLI `aiops --help` + 一条 slash 命令烟测。任一失败则回退该步。

---

## 5. 执行阶段总览

| 阶段 | 内容 | 验收 |
|------|------|------|
| P0 | 分支已就位（`Agenticops-always-memorized`） | ✅ 已完成 |
| P1 | §3.1 高优先级 4 项（含 F1 pending 标记） | 每项回归测试 + 全套 pytest 绿 |
| P2 | §3.2 中优先级 9 项 | 同上 |
| P3 | §3.3 优化（F14 先测量）+ §3.4 文档断言 + §3.5 Skills 2 项 | 同上 |
| P4 | §4.1 `app.py` → routers/（19 步，逐模块 commit） | 每步全量测试 + uvicorn 烟测 |
| P5 | §4.2 `main.py` → 5 模块（逐模块 commit） | 每步全量测试 + CLI 烟测 |

每阶段结束跑一次完整回归。先测完再提交（用户铁律）。

---

## 6. 风险与缓解

| 风险 | 缓解 |
|------|------|
| F1 改动 stream 持久化逻辑 | 选了最轻量 pending 标记方案；不改事务边界；强回归测试 |
| 大文件拆分引入循环依赖 | 严格遵守验证给出的单向导入顺序 + app.state 注入单例 |
| 拆分中途逻辑漂移 | 纯机械移动；逐模块独立 commit；每步全量回归 |
| F14 过度工程 | 先测量，<50ms 则不实现缓存（不加没用的功能） |
| 触及记忆/skills 代码与 ②③ 冲突 | ① 只做防御性加固，不碰能力；改动点已在 §3.2/§3.5 圈定 |

---

## 7. 明确不做（YAGNI / 留给后续周期）

- 记忆系统能力升级（持久化/增强/自主优化）→ **②**
- Skills 自主化（agent 自主 create/patch/edit、Curator 生命周期）→ **③**
- `evo-bedrock-parse-lenient` 的类型校验 → **③**（生成流程将重做）
- 新增可观测后端 / OpenTelemetry（无 tracing backend，超范围）
- 速率限制、消息编辑/删除、Web 导出等"特性 GAP"（非本周期目标，按需另议）
