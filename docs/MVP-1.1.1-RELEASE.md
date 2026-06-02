# AgenticOps v1.1.1 Release — 并发会话 + 秒开会话

> **版本**: 1.1.1 | **日期**: 2026-06-02 | **分支**: `cycle3-skills-autonomy`

---

## 一、版本概述

v1.1.1 是聚焦 **Web 聊天体验** 的优化版本，解决两个长期痛点：

1. **会话读取慢**：打开历史会话要等数秒（全量加载所有消息 + 无虚拟化 + 每 5 秒全量刷新）
2. **不支持并发对话**：一个会话在流式输出时，再开另一个窗口，所有 output 卡在同一个会话内

核心思路：把 SSE 流式读取循环 **移出 React 组件树**，放进一个按 `session_id` 索引的模块级 store —— 流不再随组件卸载而中断，多会话可同时流式输出；配合游标分页 + 列表虚拟化，会话打开瞬间渲染。

> **设计理念**: 借鉴 Gemini/ChatGPT 的"多会话单应用 + 后台流式"交互模式，唯一指标 —— 多开 + 秒开。

---

## 二、并发会话 (Concurrent Sessions)

### 2.1 核心能力

| 能力 | 说明 |
|------|------|
| **`chatStream` store** | 模块级单例，按 `session_id` 持有 SSE fetch+解析循环（脱离 React 组件树） |
| **后台流式 (Gemini-style)** | 导航切换会话不中断生成；多会话可同时流式输出 |
| **`useSessionStream` 适配器** | `useSyncExternalStore` 读取单会话切片，返回与旧 `useChat` 完全相同的接口 |
| **Per-session 输入禁用** | 仅正在流式的会话禁用输入框，不再全局锁定 |
| **实时流式指示** | 会话列表对每个正在流式的会话显示脉冲 ● 圆点（`useActiveStreamingSessions`，缓存 join-key 防止逐 token 抖动） |
| **Token 合并** | 60ms 节流合并 token，消除逐 token 的 O(n²) markdown 重解析 |
| **后端隔离** | `contextvars`（`detail_level`/`scan_focus`/`trace_id`）天然隔离不同会话的并发流；同会话并发由 Strands agent 锁拒绝（一会话一轮，设计如此） |

### 2.2 数据流

```
send(A) ─► store: state[A].streaming, fetch POST /sessions/A/messages
           (HTTP 连接 + 读取循环归 STORE 所有，不随组件卸载)
send(B) ─► store: state[B].streaming, fetch POST /sessions/B/messages   ← 独立

导航 A→B→A : 组件重新订阅切片；store 内的读取循环不受影响（不再 abort）
on "done"(A) : 先清空 live 切片，再 onDone → 乐观追加到 cache + invalidate 列表
```

---

## 三、秒开会话 (Fast Session Open)

### 3.1 核心能力

| 能力 | 说明 |
|------|------|
| **游标分页 API** | `GET /api/chat/sessions/{id}/messages?limit=50&before=<msg_id>` 返回最新一页 + `next_cursor` |
| **Metadata-only 详情** | `GET /api/chat/sessions/{id}` 不再返回全量消息（`messages` 恒为 `[]`，已 deprecated） |
| **`useChatMessages` Hook** | `useInfiniteQuery`，最新 50 条上屏，向上滚动 `fetchOlder` 加载更老页 |
| **列表虚拟化** | `@tanstack/react-virtual`，仅可见行进入 DOM，无论历史多大 |
| **滚动锚定** | 加载更老页时锚定视口（不跳动）；新消息/token 时仅在用户处于底部才 stick-to-bottom |
| **DB 复合索引** | `chat_messages(session_id, id)` —— 此前该表零索引，游标范围扫描现为亚毫秒 |

### 3.2 游标契约

- 游标 = `ChatMessage.id`（单调自增，无时钟依赖）
- `before` 省略 → 最新 `limit` 条；`before=<id>` → `id < before` 的更老一页
- 每页内部按时间正序（oldest→newest）；前端 `pages.slice().reverse().flatMap()` 拼成单条 oldest→newest 列表
- `has_more=false` 时 `next_cursor=null`

---

## 四、缓存策略 (Caching)

三层缓存，**无服务端缓存**（DB 单用户 + 新索引使读取亚毫秒，YAGNI）：

| 层 | 说明 |
|----|------|
| **TanStack Query 页缓存** | 已加载页常驻；完成时乐观追加替代旧的 5 秒全量刷新 |
| **Bedrock prompt-cache** | 不变 —— 不同会话用独立前缀，并发安全 |
| **不可变消息 markdown memo** | `Map<msgId, html>`，虚拟化行重挂载时无需重解析 markdown |

---

## 五、技术统计

| 指标 | 数值 |
|------|------|
| Commits | 12 |
| 新/改文件 | 17（不含 spec/plan 文档） |
| 净变更 | +963 / −292 行（含删除旧 `useChat.ts` 167 行） |
| 新增前端文件 | 4（`chatStream.ts`, `markdownCache.ts`, `useSessionStream.ts`, `useChatMessages.ts`） |
| 删除文件 | 1（`useChat.ts` —— 被 store 取代） |
| 新测试 | 7 后端分页 + 4 前端 store 隔离 |
| 新依赖 | 1（`@tanstack/react-virtual`，与已装 react-query 同族） |
| 新 API 端点 | 1（`GET /sessions/{id}/messages`） |
| 新 DB 索引 | 1（`idx_chat_message_session_id`） |

---

## 六、架构变化

```
v1.1.0（旧）:
  Chat 页 ── useChat(sessionId) ── SSE 循环在组件内
            └─ 导航离开 → AbortController 中断流（卡死）
  GET /sessions/{id} → 全量历史（慢）→ messages.map() 全渲染（无虚拟化）

v1.1.1（新）:
  chatStream store（模块级，按 session_id）── SSE 循环在此（跨导航存活）
       ↑ useSessionStream（useSyncExternalStore 适配器，多会话并发）
  GET /sessions/{id}          → 仅元数据（快）
  GET /sessions/{id}/messages → 游标分页（最新页 + cursor）
       ↓ useChatMessages（useInfiniteQuery）→ 虚拟化 MessageList + markdown memo
```

---

## 七、Skills & Memory 运行态更新

v1.1.1 随发布快照同步了自主**记忆**与**技能**系统在运行中产生的状态更新 —— 这些不是新功能（核心能力见 [v1.1.0](MVP-1.1.0-RELEASE.md)），而是 cycle②/cycle③ 自治机制**实际跑起来**后的产物，一并纳入本次发布分支。

### 7.1 Agent Memory（运行态）

| 项 | 说明 |
|----|------|
| **`last_used` 时间戳推进** | 9 个 `agent-memory/*.md` 被 Curator 在注入时 touch，`last_used` 推进到 `2026-06-02` —— Reactivate-on-use 机制的可见证据 |
| **内容不变** | 仅时间戳变化，记忆正文/confidence/provenance 未改 |
| **效果** | 这些记忆因近期被使用而保持 `active`，不会被 Curator 误判为 stale 归档 |

### 7.2 Agent Skills（运行态 / frontmatter 规范化）

`normalize_skill_frontmatter` 对 3 个技能做了**非破坏性 provenance 回填**（技能正文未改）：

| Skill | 变更 |
|-------|------|
| `aws-compute` | 回填 `created_by=user` / `status=active` / `skill_version` / `created_at`；YAML 引号与缩进规范化 |
| `local-os-operator` | 同上 + tools 列表缩进规范化 |
| `web-research` | 同上 |

- **`created_by=user`** → 这 3 个为人工编写技能，被 Curator **永久 pinned**，绝不自动 stale/归档
- **向后兼容**：旧 SKILL.md 缺失的 provenance 字段被补齐，符合 cycle③ 规范；无字段语义丢失
- **未触及**：其余 12 个技能、技能正文、references/ 均未改动

> 这部分体现了"Agents 在安全边界内自主学习"原则的**日常运转**：记忆随使用自我保活、技能元数据自我规范化，全程无人工介入、无破坏性写入。

---

## 八、已知限制 & 后续计划

| 项目 | 状态 | 说明 |
|------|------|------|
| 硬刷新后流不续传 | By design | 后端已持久化部分回复，刷新后历史可见；本期不做服务端 job 模型 |
| 跨标签页/窗口同步 | Out of scope | 需服务端 fan-out，本期"多会话单应用"不覆盖 |
| `messages` 数组每次渲染重建 | Acceptable | 虚拟化按 id key 仅渲染可见行，无 DOM 抖动；如压测有瓶颈再 `useMemo` |
| 完成瞬间 ~16ms 空档 | Cosmetic | 流式气泡消失到持久化行出现之间一帧；不可感知 |
| 实时浏览器手测 | Pending | 已通过代码走查 + 自动化测试验证；建议合并前跑双会话 smoke 测试 |

---

## 九、升级指南

```bash
git pull
cd src/agenticops/web/frontend && npm install   # 拉取 @tanstack/react-virtual
# DB 索引在 init_db() 自动幂等创建，无需手动迁移
```

无新配置项。Postgres 同样兼容（同一 `database_url`）。

---

## 十、验证清单

- [x] 后端分页：7 tests passed（默认页/before 游标/末页/空会话/404/limit 上限/metadata-only）
- [x] 后端 chat 套件：28/28 相关测试通过，零回归
- [x] 前端 store：4 tests passed（token 流式+onDone / 并发隔离 / 错误路径 / active 会话上报）
- [x] 前端 `tsc --noEmit` clean + `npm run build` 成功 + 6/6 vitest 通过
- [x] DB 索引 `idx_chat_message_session_id` 创建且幂等
- [x] 端到端集成评审通过（分页顺序契约 + 乐观 temp-id 去重 + 无双渲染）
- [x] 旧 `useChat.ts` 删除，无残留引用
- [ ] 实时双会话浏览器 smoke 测试（建议合并前执行）

> **已知遗留**：`test_chat_session_rename.py::TestGenerateSessionTitle` 3 个测试失败 —— 经确认在本功能基线 `cf3e0ad` 之前即失败（真实 LLM vs mock 桩问题），与本次改动无关。

---

> **关联文档**: 设计 `docs/superpowers/specs/2026-06-01-concurrent-chat-sessions-design.md` | 实施计划 `docs/superpowers/plans/2026-06-01-concurrent-chat-sessions.md` | 用户文档 `docs/WORKFLOW.md`（Concurrent Chat Sessions 章节）
