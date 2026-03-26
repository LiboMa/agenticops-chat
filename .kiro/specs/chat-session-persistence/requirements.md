# 需求文档：Chat Session 持久化与 Agent 长期记忆

## 简介

本功能为 AgenticOps 的 Chat 系统提供三阶段增强：（1）短期会话持久化，让前端能记住并恢复上次会话，同时改善 Agent 重建时的历史消息保真度；（2）中期对话摘要记忆，在 SlidingWindowConversationManager 裁剪消息时生成摘要，避免上下文丢失；（3）长期跨会话记忆，让每个 Agent 具备结构化事实记忆和向量化经验记忆能力。

## 术语表

- **Frontend**：AgenticOps 的 React 18 + TypeScript 前端应用
- **SessionManager**：后端 `ChatSessionManager` 类，管理每个会话的 Agent 实例生命周期
- **HistoryLoader**：后端 `_load_history_messages()` 函数，从数据库加载历史消息并转换为 Strands Message 格式
- **ChatSession_Model**：SQLAlchemy ORM 中的 `ChatSession` 数据库模型
- **ChatMessage_Model**：SQLAlchemy ORM 中的 `ChatMessage` 数据库模型
- **ConversationManager**：Strands SDK 的 `SlidingWindowConversationManager`，负责滑动窗口裁剪
- **SummaryService**：新增的对话摘要生成服务，使用轻量模型（Haiku）生成滚动摘要
- **MemoryService**：新增的长期记忆服务，负责记忆提取、存储和检索
- **VectorStore**：现有的向量存储基础设施（SQLite 本地 / PostgreSQL 云端），使用 Titan V2 embedding
- **localStorage**：浏览器本地存储 API

---

## 需求

### 需求 1：前端会话恢复与延迟创建

**用户故事：** 作为运维工程师，我希望重新打开或刷新 Chat 页面时不会自动创建空会话，而是恢复上次使用的会话；只有当我真正发送消息时才创建新会话。

#### 验收标准

1. WHEN 用户导航到 `/app/chat`（无 sessionId 参数）时，THE Frontend SHALL NOT 立即创建新的 ChatSession，而是显示一个空白的欢迎/输入界面
2. WHEN 用户导航到 `/app/chat`（无 sessionId 参数）且 localStorage 中存在有效的 sessionId 时，THE Frontend SHALL 自动导航到该会话，而非显示空白界面
3. WHEN 用户在空白界面中发送第一条消息时，THE Frontend SHALL 先创建新的 ChatSession，然后发送该消息
4. WHEN 用户离开 Chat 页面时，THE Frontend SHALL 将当前 sessionId 保存到 localStorage
5. IF localStorage 中保存的 sessionId 对应的会话已被删除或不存在，THEN THE Frontend SHALL 清除该 localStorage 记录并显示空白欢迎界面
6. THE Frontend SHALL 使用键名 `aiops-last-session-id` 存储最近使用的 sessionId
7. WHEN 页面刷新时，THE Frontend SHALL 恢复当前 URL 中的 sessionId 对应的会话，而非创建新会话
8. WHEN 用户手动重命名一个会话时，THE Frontend SHALL 调用 PATCH `/api/chat/sessions/{sessionId}` 更新会话名称，并在会话列表中实时反映更改

---

### 需求 2：Agent 历史消息保真重建

**用户故事：** 作为运维工程师，我希望 Agent 重建后能准确记住之前使用过的工具和调用结果，这样对话上下文不会因为 Agent 实例过期而丢失关键信息。

#### 验收标准

1. WHEN HistoryLoader 加载 assistant 角色的消息且该消息包含 tool_calls 数据时，THE HistoryLoader SHALL 将 tool_calls 还原为 Strands SDK 兼容的完整 `toolUse` 结构，而非当前的文本前缀 `[Used tools: ...]`
2. WHEN HistoryLoader 加载的历史消息中包含 tool_calls 时，THE HistoryLoader SHALL 为每个 toolUse 生成对应的 `toolResult` 消息，以满足 Bedrock API 的消息交替要求
3. IF tool_calls 数据格式损坏或无法解析，THEN THE HistoryLoader SHALL 回退到当前的文本前缀方式，并记录警告日志
4. THE HistoryLoader SHALL 在还原 toolResult 时使用占位内容 `"(result from previous session)"` 标识该结果来自历史恢复

---

### 需求 3：会话元数据扩展（Pinned / Starred / Archived）

**用户故事：** 作为运维工程师，我希望能置顶、收藏和归档会话，这样我可以快速访问重要对话并保持会话列表整洁。

#### 验收标准

1. THE ChatSession_Model SHALL 包含 `pinned` 布尔字段，默认值为 `false`
2. THE ChatSession_Model SHALL 包含 `starred` 布尔字段，默认值为 `false`
3. THE ChatSession_Model SHALL 包含 `archived` 布尔字段，默认值为 `false`
4. WHEN 用户请求置顶一个会话时，THE Frontend SHALL 调用 PATCH `/api/chat/sessions/{sessionId}` 更新 `pinned` 字段
5. WHEN 用户请求收藏一个会话时，THE Frontend SHALL 调用 PATCH `/api/chat/sessions/{sessionId}` 更新 `starred` 字段
6. WHEN 用户请求归档一个会话时，THE Frontend SHALL 调用 PATCH `/api/chat/sessions/{sessionId}` 更新 `archived` 字段
7. THE Frontend SHALL 在会话列表中按以下优先级排序：pinned 会话在最前 → starred 会话次之 → 普通会话按最近活动时间降序
8. THE Frontend SHALL 在会话列表中为 pinned 会话显示📌图标，为 starred 会话显示⭐图标
9. THE Frontend SHALL 默认隐藏已归档的会话
10. WHEN 用户切换"显示归档"开关时，THE Frontend SHALL 在会话列表底部显示已归档的会话

---

### 需求 4：Agent 实例 TTL 可配置

**用户故事：** 作为系统管理员，我希望能通过配置文件调整 Agent 实例的存活时间，这样我可以根据服务器资源情况灵活控制内存占用。

#### 验收标准

1. THE SessionManager SHALL 从 `settings.session_ttl_minutes` 读取 TTL 值，而非使用硬编码的 30 分钟
2. THE `settings.yaml` SHALL 支持 `session_ttl_minutes` 配置项，默认值为 30
3. WHEN Agent 实例超过配置的 TTL 时间未活动时，THE SessionManager SHALL 自动清理该实例并释放内存

---

### 需求 5：对话摘要生成

**用户故事：** 作为运维工程师，我希望 Agent 在长对话中不会遗忘早期讨论的内容，这样我在复杂排障过程中不需要重复描述问题背景。

#### 验收标准

1. WHEN ConversationManager 的滑动窗口即将裁剪消息时，THE SummaryService SHALL 使用轻量模型（Haiku）对即将被裁剪的消息生成摘要
2. THE SummaryService SHALL 将生成的摘要存储到 `session_summaries` 数据库表中，包含 session_id、summary_text、message_range_start、message_range_end 和 created_at 字段
3. WHEN SessionManager 重建 Agent 实例时，THE HistoryLoader SHALL 加载该会话的所有摘要，并作为上下文前缀注入到 Agent 的消息历史中
4. THE SummaryService SHALL 生成的每条摘要长度不超过 500 个 token
5. IF 摘要生成失败，THEN THE SummaryService SHALL 记录错误日志并继续正常的消息裁剪流程，不阻塞用户对话

---

### 需求 6：跨会话结构化事实记忆

**用户故事：** 作为运维工程师，我希望 Agent 能记住我的偏好设置和基础设施上下文（如常用区域、命名规范、团队分工），这样我不需要在每个新会话中重复说明。

#### 验收标准

1. THE MemoryService SHALL 维护 `agent_memory_facts` 数据库表，包含 id、category（如 `user_preference`、`infra_context`、`team_info`）、key、value、confidence_score、source_session_id、created_at 和 updated_at 字段
2. WHEN 一个会话结束或被归档时，THE MemoryService SHALL 使用 LLM 从对话历史中提取结构化事实
3. IF 新提取的事实与已有事实的 key 相同，THEN THE MemoryService SHALL 更新已有记录的 value 和 confidence_score，而非创建重复条目
4. WHEN SessionManager 创建新的 Agent 实例时，THE MemoryService SHALL 检索该用户的高置信度事实（confidence_score >= 0.7）并注入到 Agent 的 system prompt 中
5. THE MemoryService SHALL 支持用户通过 API 查看和删除已存储的事实记忆

---

### 需求 7：跨会话向量化经验记忆

**用户故事：** 作为运维工程师，我希望 Agent 能从过去的排障经验中学习，在遇到类似问题时自动参考历史解决方案，这样可以加速问题定位和修复。

#### 验收标准

1. THE MemoryService SHALL 维护 `agent_memories` 向量表，复用现有 VectorStore 基础设施（Titan V2 embedding + SQLite/PostgreSQL）
2. WHEN 一个会话结束或被归档时，THE MemoryService SHALL 从对话中提取关键经验片段（问题描述、根因分析、解决方案），生成 embedding 并存储到 `agent_memories` 表
3. WHEN SessionManager 创建新的 Agent 实例时，THE MemoryService SHALL 根据当前会话的初始上下文（如关联的 HealthIssue）执行向量相似度搜索，检索最相关的历史经验（top 3）
4. THE MemoryService SHALL 将检索到的历史经验以结构化格式注入到 Agent 的 system prompt 中，包含来源会话 ID 和时间戳
5. IF 向量搜索返回的结果相似度低于 0.6，THEN THE MemoryService SHALL 不注入该结果，避免引入无关上下文
6. THE `agent_memories` 表 SHALL 包含 id、session_id、memory_type（`problem`、`root_cause`、`solution`）、content_text、embedding_vector、created_at 字段

---

### 需求 9：CLI 会话管理与恢复

**用户故事：** 作为运维工程师，我希望在 CLI（`aiops chat`）中也能列出、恢复和管理数据库中的 Chat Session，这样 CLI 和 Web Dashboard 的会话可以互通，我可以在 CLI 中继续 Web 上的对话。

#### 验收标准

1. WHEN 用户执行 `/session list` 时，THE CLI SHALL 从数据库查询 ChatSession 列表（而非本地 JSON 文件），显示 session_id、name、message_count、last_activity_at、pinned/starred 状态
2. WHEN 用户执行 `/session resume <session_id 或 name>` 时，THE CLI SHALL 从数据库加载该会话的历史消息，重建 Agent 实例，并在当前 REPL 中继续该会话
3. WHEN 用户执行 `/session resume` （无参数）时，THE CLI SHALL 恢复最近活跃的会话（按 last_activity_at 降序取第一个非归档会话）
4. WHEN 用户在 CLI 中发送消息时，THE CLI SHALL 将消息持久化到数据库的 ChatMessage 表，与 Web Dashboard 共享同一份对话记录
5. WHEN 用户执行 `/session pin <session_id>` 或 `/session star <session_id>` 时，THE CLI SHALL 更新数据库中对应会话的 pinned/starred 字段
6. WHEN 用户执行 `/session archive <session_id>` 时，THE CLI SHALL 更新数据库中对应会话的 archived 字段
7. WHEN 用户执行 `/session rename <session_id> <new_name>` 时，THE CLI SHALL 更新数据库中对应会话的 name 字段
8. THE CLI SHALL 在启动 `aiops chat` 时自动创建一个新的 ChatSession 并持久化到数据库，除非用户通过 `aiops chat --resume` 或 `aiops chat --session <id>` 指定恢复已有会话
9. THE CLI 的 `/session save` 和 `/session load` 命令 SHALL 保持向后兼容，继续支持本地 JSON 文件的 context 保存/加载

---

### 需求 10：记忆序列化与反序列化的往返一致性

**用户故事：** 作为开发者，我希望记忆数据在存储和读取过程中保持完整性，这样不会因为序列化问题导致记忆丢失或损坏。

#### 验收标准

1. FOR ALL 有效的 MemoryFact 对象，THE MemoryService SHALL 保证序列化到数据库再反序列化后产生等价的对象（往返一致性）
2. FOR ALL 有效的 AgentMemory 对象（不含 embedding_vector），THE MemoryService SHALL 保证 content_text 和 metadata 在存储和读取后保持一致
3. FOR ALL 有效的 SessionSummary 对象，THE SummaryService SHALL 保证 summary_text 在存储和读取后保持一致
