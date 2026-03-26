# 实施计划：Chat Session 持久化与 Agent 长期记忆

## 概述

按三阶段渐进实施：Phase 1（短期）覆盖会话持久化、保真重建、元数据、TTL 和 CLI；Phase 2（中期）覆盖对话摘要；Phase 3（长期）覆盖跨会话记忆。最后通过往返一致性测试收尾。

后端使用 Python，前端使用 TypeScript/React。

## Tasks

### Phase 1：短期 — 会话持久化与元数据

- [x] 1. 数据模型扩展与配置变更
  - [x] 1.1 为 ChatSession 模型添加 pinned/starred/archived 字段
    - 在 `src/agenticops/models.py` 的 `ChatSession` 类中新增 `pinned: Mapped[bool]`、`starred: Mapped[bool]`、`archived: Mapped[bool]` 三个布尔字段，默认值均为 `False`
    - 扩展 `ChatSessionUpdate` Pydantic 模型，支持 `pinned`、`starred`、`archived` 可选字段
    - 扩展 `ChatSessionResponse` Pydantic 模型，返回 `pinned`、`starred`、`archived` 字段
    - _需求: 3.1, 3.2, 3.3_

  - [x] 1.2 在 config.py 和 settings.yaml 中添加 session_ttl_minutes 配置
    - 在 `src/agenticops/config.py` 中新增 `session_ttl_minutes: int = Field(default=30, ...)` 配置项
    - 在 `config/settings.yaml` 中添加 `session_ttl_minutes: 30` 默认值
    - _需求: 4.1, 4.2_

  - [x] 1.3 更新 API 端点支持元数据字段
    - 修改 `PATCH /api/chat/sessions/{id}` 端点，处理 `pinned`、`starred`、`archived` 字段更新
    - 修改 `GET /api/chat/sessions` 端点，返回新字段并支持 `include_archived` 查询参数（默认不返回归档会话）
    - _需求: 3.4, 3.5, 3.6, 3.9, 3.10_

  - [x] 1.4 编写元数据 CRUD 的单元测试
    - 在 `tests/test_chat_api.py` 中测试 PATCH pinned/starred/archived 的 API 行为
    - 测试 GET sessions 的 include_archived 过滤逻辑
    - _需求: 3.1-3.6, 3.9, 3.10_

- [x] 2. HistoryLoader 保真重建
  - [x] 2.1 实现 `_rebuild_tool_messages()` 函数
    - 在 `src/agenticops/web/session_manager.py` 中新增 `_rebuild_tool_messages(tool_calls: list) -> list[dict]` 函数
    - 将 DB 中的 `tool_calls` JSON 还原为 Strands SDK 的 `toolUse` + `toolResult` 消息对
    - `toolResult` 使用占位内容 `"(result from previous session)"`
    - _需求: 2.1, 2.2, 2.4_

  - [x] 2.2 修改 `_load_history_messages()` 调用保真重建逻辑
    - 当 assistant 消息包含有效 `tool_calls` 时，调用 `_rebuild_tool_messages()` 生成 toolUse/toolResult 消息对
    - 解析失败时回退到现有的文本前缀 `[Used tools: ...]` 方式，并记录 warning 日志
    - _需求: 2.1, 2.2, 2.3_

  - [x] 2.3 编写属性测试：toolUse 结构还原正确性
    - **Property 1: toolUse 结构还原正确性**
    - 使用 hypothesis 生成随机 tool_calls JSON，验证输出符合 Strands SDK 格式
    - **验证: 需求 2.1**

  - [x] 2.4 编写属性测试：toolResult 配对与占位内容
    - **Property 2: toolResult 配对与占位内容**
    - 验证每个 toolUse 都有且仅有一个对应的 toolResult，且内容为占位文本
    - **验证: 需求 2.2, 2.4**

- [x] 3. ChatSessionManager TTL 可配置化
  - [x] 3.1 修改 ChatSessionManager 从配置读取 TTL
    - 修改 `src/agenticops/web/session_manager.py` 中 `ChatSessionManager.__init__()` 从 `settings.session_ttl_minutes` 读取 TTL 值
    - _需求: 4.1, 4.3_

  - [x] 3.2 编写属性测试：TTL 过期清理
    - **Property 5: TTL 过期清理**
    - 使用 hypothesis 生成随机 TTL 值和 last_activity 时间，验证 `_remove_stale()` 正确清理过期实例
    - **验证: 需求 4.3**

- [x] 4. 前端延迟创建与会话恢复
  - [x] 4.1 实现 `useLazySessionCreate` hook
    - 在 `src/agenticops/web/frontend/src/hooks/` 下新建 `useLazySessionCreate.ts`
    - 提供 `sendFirstMessage(content, file?)` 方法：先创建 ChatSession，再发送消息
    - 返回 `creating` 状态标志
    - _需求: 1.3_

  - [x] 4.2 修改 Chat.tsx 实现延迟创建逻辑
    - 移除现有的 `useEffect` 自动创建会话逻辑
    - 无 URL sessionId 时：检查 `localStorage.getItem('aiops-last-session-id')`，有效则 navigate，无效则显示欢迎界面
    - 用户离开页面时保存当前 sessionId 到 localStorage
    - localStorage 中 sessionId 对应会话不存在时清除记录并显示欢迎界面
    - _需求: 1.1, 1.2, 1.4, 1.5, 1.6, 1.7_

  - [x] 4.3 扩展 SessionFlyout 支持元数据操作
    - 在会话列表项中显示 📌（pinned）和 ⭐（starred）图标
    - 添加 hover 菜单支持 pin/star/archive 操作，调用 PATCH API
    - 实现排序逻辑：pinned → starred → 普通（按 last_activity_at 降序）
    - 添加"显示归档"开关，默认隐藏归档会话
    - _需求: 3.4-3.10_

  - [x] 4.4 扩展前端 TypeScript 类型和 API hooks
    - 在 `src/agenticops/web/frontend/src/api/types.ts` 的 `ChatSession` 接口中添加 `pinned`、`starred`、`archived` 字段
    - 在 `useChatSessions.ts` 中添加 `useUpdateChatSession` mutation hook（支持 PATCH pinned/starred/archived）
    - _需求: 3.4, 3.5, 3.6, 1.8_

  - [x] 4.5 编写属性测试：会话列表排序不变量
    - **Property 3: 会话列表排序不变量**
    - 使用 fast-check 生成随机会话列表，验证排序结果满足 pinned > starred > 普通的优先级
    - **验证: 需求 3.7**

  - [x] 4.6 编写属性测试：归档会话默认隐藏
    - **Property 4: 归档会话默认隐藏**
    - 使用 fast-check 验证默认过滤后不包含 archived 会话
    - **验证: 需求 3.9**

- [x] 5. Checkpoint — Phase 1 验证
  - 确保所有测试通过，如有疑问请向用户确认。

- [x] 6. CLI 会话管理与消息持久化
  - [x] 6.1 扩展 ChatContext 添加 db_session_id 字段
    - 在 CLI 的 `ChatContext` 类中新增 `db_session_id: Optional[int]` 和 `db_session_uuid: Optional[str]` 字段
    - _需求: 9.4_

  - [x] 6.2 修改 CLI 启动流程支持 --resume 和 --session 参数
    - `aiops chat` 默认创建新 DB Session
    - `aiops chat --resume` 恢复最近活跃的非归档会话
    - `aiops chat --session <id>` 恢复指定会话
    - 启动时加载历史消息并注入 Agent
    - _需求: 9.8_

  - [x] 6.3 重写 `/session` slash 命令支持 DB 操作
    - `/session list`：从 DB 查询 ChatSession 列表，显示 id、name、message_count、last_activity、pinned/starred
    - `/session resume [id|name]`：切换到指定 Session（无参数 = 最近活跃非归档会话）
    - `/session rename <id> <name>`：更新 DB 中会话名称
    - `/session pin <id>`、`/session star <id>`、`/session archive <id>`：切换对应状态
    - 保留 `/session save` 和 `/session load` 的本地 JSON 向后兼容
    - _需求: 9.1, 9.2, 9.3, 9.5, 9.6, 9.7, 9.9_

  - [x] 6.4 实现 CLI 消息持久化
    - CLI 中每条用户消息和 Agent 回复写入 `chat_messages` 表
    - 与 Web Dashboard 共享同一份对话记录
    - DB 写入失败时记录 warning 日志，降级为非持久化模式
    - _需求: 9.4_

  - [x] 6.5 编写属性测试：CLI 会话消息持久化一致性
    - **Property 13: CLI 会话消息持久化一致性**
    - 验证 CLI 写入的消息通过 DB 查询能获取到相同内容和角色
    - **验证: 需求 9.4**

  - [x] 6.6 编写 CLI 会话管理单元测试
    - 测试 `/session list`、`/session resume`、`/session pin`、`/session star`、`/session archive`、`/session rename` 命令
    - 测试 `--resume` 和 `--session` 启动参数
    - _需求: 9.1-9.9_

- [x] 7. Checkpoint — Phase 1 完成
  - 确保所有 Phase 1 测试通过，如有疑问请向用户确认。

### Phase 2：中期 — 对话摘要

- [x] 8. 对话摘要服务
  - [x] 8.1 创建 SessionSummary 数据模型
    - 在 `src/agenticops/models.py` 中新增 `SessionSummary` 模型，包含 id、session_id（FK）、summary_text、message_range_start、message_range_end、created_at
    - _需求: 5.2_

  - [x] 8.2 实现 SummaryService 类
    - 在 `src/agenticops/web/` 下新建 `summary_service.py`
    - 实现 `generate_summary(messages, session_id)` 方法，使用 Haiku 模型生成 ≤500 token 的摘要
    - 实现 `get_summaries(session_id)` 方法，按时间排序返回摘要列表
    - 摘要生成失败时记录 error 日志，不阻塞对话
    - _需求: 5.1, 5.2, 5.4, 5.5_

  - [x] 8.3 集成摘要到 HistoryLoader
    - 修改 `_load_history_messages()` 加载会话摘要，作为上下文前缀注入到消息历史之前
    - _需求: 5.3_

  - [x] 8.4 编写属性测试：摘要注入完整性
    - **Property 6: 摘要注入完整性**
    - 验证 HistoryLoader 返回的消息列表包含所有摘要内容，且摘要在历史消息之前
    - **验证: 需求 5.3**

  - [x] 8.5 编写属性测试：摘要长度约束
    - **Property 7: 摘要长度约束**
    - 验证 SummaryService 生成的摘要 token 数不超过 500
    - **验证: 需求 5.4**

- [x] 9. Checkpoint — Phase 2 完成
  - 确保所有 Phase 2 测试通过，如有疑问请向用户确认。

### Phase 3：长期 — 跨会话记忆

- [x] 10. 结构化事实记忆
  - [x] 10.1 创建 AgentMemoryFact 数据模型
    - 在 `src/agenticops/models.py` 中新增 `AgentMemoryFact` 模型，包含 id、category、key、value、confidence_score、source_session_id、created_at、updated_at
    - 添加 `(category, key)` 唯一约束
    - _需求: 6.1_

  - [x] 10.2 实现 MemoryService 事实记忆部分
    - 在 `src/agenticops/web/` 下新建 `memory_service.py`
    - 实现 `extract_facts(session_id, messages)` 方法，使用 LLM 从对话中提取结构化事实
    - 实现 `get_facts(min_confidence=0.7)` 方法，返回高置信度事实
    - 实现 upsert 逻辑：相同 (category, key) 更新 value 和 confidence_score
    - _需求: 6.2, 6.3, 6.4_

  - [x] 10.3 添加事实记忆 API 端点
    - `GET /api/memory/facts`：查询结构化事实
    - `DELETE /api/memory/facts/{id}`：删除指定事实
    - _需求: 6.5_

  - [x] 10.4 集成事实记忆到 Agent 创建流程
    - 在 `ChatSessionManager.get_or_create()` 中调用 `MemoryService.get_facts()` 获取高置信度事实
    - 将事实注入到 Agent 的 system prompt 中
    - _需求: 6.4_

  - [x] 10.5 编写属性测试：事实 Upsert 幂等性
    - **Property 8: 事实 Upsert 幂等性**
    - 使用 hypothesis 生成含重复 key 的事实序列，验证 DB 中只保留一条记录
    - **验证: 需求 6.3**

  - [x] 10.6 编写属性测试：高置信度事实过滤
    - **Property 9: 高置信度事实过滤**
    - 验证 `get_facts(min_confidence=0.7)` 仅返回 score >= 0.7 的记录
    - **验证: 需求 6.4**

- [x] 11. 向量化经验记忆
  - [x] 11.1 创建 AgentMemory 数据模型
    - 在 `src/agenticops/models.py` 中新增 `AgentMemory` 模型，包含 id、session_id、memory_type、content_text、embedding_vector、created_at
    - _需求: 7.1, 7.6_

  - [x] 11.2 实现 MemoryService 经验记忆部分
    - 实现 `extract_experiences(session_id, messages)` 方法，提取问题描述/根因/解决方案并生成 embedding
    - 实现 `search_experiences(query_text, top_k=3, min_score=0.6)` 方法，向量相似度搜索
    - 实现 `build_memory_context(session_id, initial_context)` 方法，构建注入 system prompt 的记忆上下文
    - _需求: 7.2, 7.3, 7.4, 7.5_

  - [x] 11.3 添加经验记忆 API 端点
    - `GET /api/memory/experiences`：查询向量化经验
    - _需求: 7.1_

  - [x] 11.4 集成经验记忆到 Agent 创建流程
    - 在 `ChatSessionManager.get_or_create()` 中调用 `MemoryService.build_memory_context()` 注入历史经验
    - 注入格式包含来源 session_id 和 created_at 时间戳
    - _需求: 7.3, 7.4_

  - [x] 11.5 编写属性测试：经验注入格式完整性
    - **Property 10: 经验注入格式完整性**
    - 验证注入文本包含每条经验的 session_id 和 created_at
    - **验证: 需求 7.4**

  - [x] 11.6 编写属性测试：相似度阈值过滤
    - **Property 11: 相似度阈值过滤**
    - 验证 `search_experiences(min_score=0.6)` 仅返回 score >= 0.6 的记录
    - **验证: 需求 7.5**

- [x] 12. 会话结束/归档时触发记忆提取
  - [x] 12.1 在会话归档和结束流程中集成 SummaryService 和 MemoryService
    - 会话归档时触发 `MemoryService.extract_facts()` 和 `MemoryService.extract_experiences()`
    - Agent TTL 过期清理时触发摘要和记忆提取
    - 提取失败时记录 error 日志，不影响正常流程
    - _需求: 5.1, 6.2, 7.2_

- [x] 13. Checkpoint — Phase 3 完成
  - 确保所有 Phase 3 测试通过，如有疑问请向用户确认。

### Phase 4：往返一致性测试

- [x] 14. 记忆序列化往返一致性
  - [x] 14.1 编写属性测试：MemoryFact 往返一致性
    - **Property 12: 记忆序列化往返一致性（MemoryFact）**
    - 使用 hypothesis 生成随机 MemoryFact 对象，验证序列化到 DB 再反序列化后等价
    - **验证: 需求 10.1**

  - [x] 14.2 编写属性测试：AgentMemory 往返一致性
    - **Property 12: 记忆序列化往返一致性（AgentMemory）**
    - 使用 hypothesis 生成随机 AgentMemory 对象（不含 embedding_vector），验证 content_text 和 metadata 往返一致
    - **验证: 需求 10.2**

  - [x] 14.3 编写属性测试：SessionSummary 往返一致性
    - **Property 12: 记忆序列化往返一致性（SessionSummary）**
    - 使用 hypothesis 生成随机 SessionSummary 对象，验证 summary_text 往返一致
    - **验证: 需求 10.3**

- [x] 15. Final Checkpoint — 全部完成
  - 确保所有测试通过，如有疑问请向用户确认。

## 备注

- 标记 `*` 的子任务为可选测试任务，可跳过以加速 MVP 交付
- 每个任务引用了具体的需求编号，确保可追溯性
- Checkpoint 任务确保增量验证
- 属性测试验证通用正确性属性（hypothesis / fast-check）
- 单元测试验证具体示例和边界情况
- 三层记忆独立容错，任一层失败不阻塞其他层
