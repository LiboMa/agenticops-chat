# AgenticOps v1.1.1 Release — Web 聊天体验 + 统一 Messaging

> **版本**: 1.1.1 | **日期**: 2026-06-02 | **分支**: `cycle3-skills-autonomy`

---

## 一、版本概述

v1.1.1 是聚焦 **Web 聊天体验** 的优化版本，解决两个长期痛点：

1. **会话读取慢**：打开历史会话要等数秒（全量加载所有消息 + 无虚拟化 + 每 5 秒全量刷新）
2. **不支持并发对话**：一个会话在流式输出时，再开另一个窗口，所有 output 卡在同一个会话内

核心思路：把 SSE 流式读取循环 **移出 React 组件树**，放进一个按 `session_id` 索引的模块级 store —— 流不再随组件卸载而中断，多会话可同时流式输出；配合游标分页 + 列表虚拟化，会话打开瞬间渲染。

> **设计理念**: 借鉴 Gemini/ChatGPT 的"多会话单应用 + 后台流式"交互模式，唯一指标 —— 多开 + 秒开。

v1.1.1 实际落地的完整范围（本次合并）：

1. **并发会话 + 秒开**（本文 §二/§三）—— 后台流式多开 + 游标分页虚拟化
2. **粘贴 / 拖拽多附件**（§七）—— Cmd+V 截图、拖拽、一条消息最多 5 个附件
3. **Chat UI 重构**（§八）—— open-webui 风格蓝/白、时间分组侧栏、扁平 AI 消息、悬浮胶囊输入框
4. **Agent 窗口配置修复**（§九）—— Full Context 对所有 agent 生效 + Web 配置持久化到 YAML
5. **统一 Messaging 设置**（§十）—— 合并 Notifications + IM Bots 两个 tab，新 `/api/messaging/*`

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

## 七、粘贴 / 拖拽多附件 (Chat Attachments)

Web 聊天输入框支持 **粘贴图片(Cmd+V)、拖拽文件、一条消息多附件**(最多 5 个,沿用现有 ACCEPTED_TYPES)。

| 能力 | 说明 |
|------|------|
| **粘贴图片** | `Cmd+V` 截图直接进附件(借鉴 open-webui:仅在真取到 image 时 preventDefault,纯文本粘贴不拦截) |
| **拖拽上传** | 拖文件进输入框;dragover 持续高亮 + dragleave contains 守卫(防 Firefox 闪烁)+ capture 阶段监听严格 cleanup(防内存泄漏) |
| **多附件** | 一条消息最多 5 个;按 name+size 去重;按稳定 id 移除(非数组下标,防并发删错) |
| **分类型大小校验** | 客户端校验对齐后端 file_reader:文本 512KB / 图片 5MB / 文档 5MB |
| **后端** | `form.getlist("file")` 循环 + 服务端 max-5 防护(防 curl 绕过);preprocessor/file_reader/ChatMessage 模型零改 |

> **设计理念**:对照 open-webui 真实实现(MessageInput/Chat/FilesOverlay)借鉴 8 个经过实战验证的模式,避开它们修过的 bug(Firefox 拖拽卡住 #21664、内存泄漏 #21968、重复上传 #10f06a64)。

## 八、Chat UI 重构 (open-webui 风格)

聊天界面重构为 **open-webui 风格、蓝/白主色、极简**。

| 区域 | 改动 |
|------|------|
| **会话侧栏** | 按时间分组(Pinned/Starred/Today/Yesterday/Previous 7/30 days/Older,纯函数 `groupSessions`)· 中性灰底活动态 + 蓝色流式点 · hover(且键盘可达)显示 pin/star/archive/delete · 去常驻 emoji 噪声 |
| **消息区** | 用户=淡蓝气泡 · AI=无气泡扁平文本(读长答案/日志最清爽)· 更大行距 · 行内代码中性 chip |
| **输入框** | 悬浮胶囊(圆角+轻阴影)· textarea 自动增高 · 圆形蓝色发送/红色停止 |
| **顶栏** | 标题居中 · 安静的 Save-as-Report 按钮 |

> 纯视觉重构:不碰任何 hook/后端/状态/SSE/分页/附件逻辑。light=蓝/白;dark 复用现有 `.dark` 主题(绿色强调)。

## 九、Agent 窗口配置修复 (2 bugs)

| Bug | 根因 | 修复 |
|-----|------|------|
| **Window 配置不持久** | `PATCH /api/settings` 只把 Report 配置写盘,agent_models(model/window/max_tokens)仅内存 | agent_models 改动也 `save_to_yaml()` + 清 session agent 缓存,当场生效 |
| **非 RCA/SRE 设不了 Full Context** | `get_agent_window_size` 的 override 判断是 `> 0`,吞掉了 `-1`(Full Context sentinel) | 改成 `!= 0`,让 `-1` 作为有效 override 通过;任意 agent 可设 Full Context |

> 之前 RCA/SRE 的 Full Context 是靠 `MODEL_WINDOW_DEFAULTS` 硬编码默认值(auto 路径),不是 override 路径——所以其他 agent 永远设不上。两个 bug 互相独立,均已修复 + 回归测试。

## 十、统一 Messaging 设置 (合并 Notifications + IM Bots)

把原来重复的 **Notifications + IM Bots 两个 Settings tab 合并为一个 Messaging tab**(三段:Bot Apps / Channels / Delivery Logs)。

| 项 | 说明 |
|----|------|
| **统一后端** | 新建 `/api/messaging/{schema,apps,channels,logs}` facade,封装现有 `channels.yaml` + `im-apps.yaml` + `NotificationLog`(零 YAML/DB schema 改动);老 `/api/notifications/*` + `/api/settings/{channels,im-apps}` 标 deprecated |
| **Bot App vs Channel** | App=inbound bot 凭据(Feishu/Slack/DingTalk/WeCom);Channel=outbound 路由(role: alert/chat);email/ses 作为 channel 类型 |
| **Schema 驱动表单** | `/api/messaging/schema` 描述每个类型的字段;Configure 弹窗用分段磁贴选类型 → 动态字段,告别手写 config JSON;密钥遮罩 + 眼睛揭示 |
| **2 个数据完整性 bug 修复** | ① 遮罩密钥回写守卫(防 `****xxxx` 覆盖真实 app_secret)② toggle 保留 role/preferred_format/alert_senders(防开关频道丢 role) |
| **借鉴** | 卡片式连接管理 + 状态徽章 + Test/Configure + restart 提示借鉴 Hermes Agents dashboard,渲染为我们的蓝/白 |

> **设计理念**:让用户更直接、简便地配置 IM bot / email / 双向 channel —— 一处管凭据 + 渠道 + 日志,动态表单替代 raw JSON。

## 十一、Skills & Memory 运行态更新

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

## 十二、已知限制 & 后续计划

| 项目 | 状态 | 说明 |
|------|------|------|
| 硬刷新后流不续传 | By design | 后端已持久化部分回复，刷新后历史可见；本期不做服务端 job 模型 |
| 跨标签页/窗口同步 | Out of scope | 需服务端 fan-out，本期"多会话单应用"不覆盖 |
| `messages` 数组每次渲染重建 | Acceptable | 虚拟化按 id key 仅渲染可见行，无 DOM 抖动；如压测有瓶颈再 `useMemo` |
| 完成瞬间 ~16ms 空档 | Cosmetic | 流式气泡消失到持久化行出现之间一帧；不可感知 |
| 实时浏览器手测 | Pending | 已通过代码走查 + 自动化测试验证；建议合并前跑双会话 smoke 测试 |

---

## 十三、升级指南

```bash
git pull
cd src/agenticops/web/frontend && npm install   # 拉取 @tanstack/react-virtual
# DB 索引在 init_db() 自动幂等创建，无需手动迁移
```

统一 Messaging 设置无需迁移:沿用现有 config/channels.yaml + config/im-apps.yaml,老 API 仍可用(deprecated)。

无新配置项。Postgres 同样兼容（同一 `database_url`）。

---

## 十四、验证清单

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
