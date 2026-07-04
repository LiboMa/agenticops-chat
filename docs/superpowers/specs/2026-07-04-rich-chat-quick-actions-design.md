# Rich Chat 切片 1 — 问题原地定位 + 建议 Chips — Design Spec

> Status: approved design (brainstorm 2026-07-04,过程留档于本文件 §7) · Branch: `MVP-2.0.1`
> Sub-project B(富交互聊天)的第一个切片。B 的其余部分(图表、图片渲染)另行 spec。

## 1. 需求(用户原话拆解)

1. **B1 问题定位**:聊天里扫描到的问题(I#N 引用)可以"直接进行定位、检查"——不离开聊天上下文。
2. **B2 建议 chips**:每次聊天末尾,把大模型的反问/建议动作变成**快捷点击按钮**,点击即作为下次交互的输入。

用户已确认的三个决策:

| 决策 | 选择 |
|---|---|
| chips 来源 | **模型总是生成**(提示词结构化块;有反问时 chips=反问的答案选项,无反问时=建议的下一步动作) |
| I# 点击行为 | **右侧面板原地打开**(复用现有 ContextPanel;R# 保持跳转) |
| chips 点击行为 | **直接发送**(流式中隐藏;只挂最后一条 assistant 消息) |
| 传输机制 | **方案 A:提示词标记块 + done 事件携带**(零额外 LLM 调用;方案 B 的 Haiku 后置生成被否——多一次调用+1-2s 延迟,违背简约经济) |

## 2. B1 — 问题原地定位(改动 ~15 行,0 个新组件)

现状:`MessageList.tsx:34-40 handleRefClick` 把 `a.md-ref` 点击统一 `navigate()` 整页跳转;`ContextPanel`(issue 详情/RCA/fix plans/timeline 四 tab)已存在但只有 `contextIssueId` state 一个入口,**没有任何 setter 调用方**(死入口)。

改动:

1. `MessageList` Props += `onIssueRefClick?: (issueId: number) => void`。`handleRefClick` 中 pathname 匹配 `/app/issues/(\d+)` 时改调回调(fallback:无回调时保持 navigate);`/app/resources/N` 不变。
2. `Chat.tsx` 两处 `<MessageList>` 传 `onIssueRefClick={setContextIssueId}` —— 分栏、拖拽、关闭全部现成。
3. `ContextPanel` Props += `onAgentCheck?: () => void`;头部(I#N 标题旁)加"让 agent 检查"按钮(icon: magnifier,样式同现有 header 按钮)。`Chat.tsx` 传入 `() => sendMessage(t("chat.contextPanel.checkPrompt").replace("{id}", String(contextIssueId)))`,即发送:"检查 I#{id} 的当前状态,确认问题是否仍存在,并给出下一步建议"。streaming 时按钮禁用。

i18n:`chat.contextPanel.agentCheck`("让 agent 检查"/"Ask agent to check")、`chat.contextPanel.checkPrompt`(含 `{id}` 占位符的完整句式,en/zh;注意现有 `t()` 不支持插值,调用侧 `.replace()`)。

## 3. B2 — 建议 chips

### 3.1 提示词约定(main_agent.py 仅 main,OUTPUT FORMATTING 段追加,~60 tokens)

```
- End EVERY reply with exactly one line:
  <<SUGGEST>>["<action 1>", "<action 2>", "<action 3>"]
  2-3 short follow-up actions the user would likely take next, in the
  conversation's language. If you asked the user a question, make each
  suggestion a direct answer option to that question.
```

### 3.2 解析层(新纯函数模块 `src/agenticops/chat/suggestions.py`)

```python
SUGGEST_MARKER = "<<SUGGEST>>"

def extract_suggestions(text: str) -> tuple[str, list[str]]:
    """从回复文本剥离 <<SUGGEST>>[...] 块。

    Returns (clean_text, suggestions)。任何解析失败 → (标记行整行移除后的文本, [])。
    规则:只认最后一次出现的标记;JSON 数组解析;每条 strip 后 ≤60 字符(超长截断);
    最多 3 条;空串条目丢弃。无标记 → (原文, [])。
    """
```

### 3.3 后端管线(app.py `_generate()` 完成段 + models.py)

- `chat_messages.suggestions`:JSON 可空新列,迁移模式与 `chat_sessions.model_id` 完全相同(ALTER TABLE + insp 幂等)。
- 持久化块:`accumulated` → `extract_suggestions` → 存 **clean_text**;suggestions 非空则存列。
- `done` 事件 payload += `"suggestions": [...]`(空列表时可省略字段)。
- **error 路径不解析**:partial 正文按现状原样落库(标记块大概率不完整,强行解析无意义)。
- CLI(`cli/main.py` 流式显示后)与 IM 出口:显示/落库前过同一 `extract_suggestions` 剥标记,丢弃 suggestions(无按钮 UI)。

### 3.4 前端

- `api/types.ts` `ChatMessage` += `suggestions?: string[]`;messages API response 同步(后端 `ChatMessageResponse` += 该字段)。
- `chatStream.ts`:
  - 显示层过滤:渲染文本 = `content.split("<<SUGGEST>>")[0]`(标记完整出现后截断;之前最多闪现 `<<` 数十 ms,可接受)。
  - `done` case:解析 `data.suggestions` 存入 `StreamState.suggestions`;donePayload 传给缓存层,写入最后一条 assistant 消息的 `suggestions` 字段。
- 新组件 `components/chat/SuggestionChips.tsx`(~50 行):
  - Props `{ suggestions: string[]; onPick: (text: string) => void; disabled?: boolean }`
  - 视觉:横向 wrap 按钮组,`rounded-full border border-border px-3 py-1 text-xs text-muted-foreground hover:bg-muted hover:border-primary-400 hover:text-foreground transition-colors`;与 composer pill 同一设计语言。
- `MessageList`:仅**最后一条 assistant 消息**(index === last && !streaming)下渲染 chips;`onPick` → 上抛 `onSuggestionPick`(Chat.tsx 接 `sendMessage`)。历史消息不渲染(DB 里有数据,刷新后最后一条恢复)。

## 4. 错误处理

| 失败场景 | 行为 |
|---|---|
| 模型未输出 SUGGEST 块 | extract → (原文, []),无 chips,正文完好 |
| 块 JSON 畸形 / 截断 | 标记行整行移除,suggestions=[],不落半截标记 |
| 流 error 事件 | 不解析;partial 正文原样落库(现状不变) |
| chips 点击时已 streaming | chips 随 streaming 状态立即隐藏 |
| ContextPanel"让 agent 检查"时 streaming | 按钮禁用(同 composer) |

## 5. 测试

- **后端 pytest**(新 `tests/test_chat_suggestions.py`):extract_suggestions 单测(正常/无标记/畸形 JSON/超 3 条截断/超 60 字符截断/中英文/多次出现取最后);持久化断言(clean_text 落库、suggestions 列、done payload);迁移幂等。
- **提示词预算**:`test_prompt_budget.py` 现有带宽(±25%)必须不触发;触发则先调查再考虑重 pin。
- **前端**:`npx tsc --noEmit` + `npm run build`;vitest:chips 渲染条件(最后一条/流式隐藏/空数组不渲染)。
- **E2E(Playwright)**:发消息 → chips 出现 → 点击 → 文本作为新用户消息发出并开始流式;聊天中点 I#N → 右侧 ContextPanel 打开(URL 不变)→"让 agent 检查"发出检查消息。

## 6. 明确不做(YAGNI)

- R# 资源原地面板(保持跳转)
- 历史消息的 chips 回显(只挂最后一条)
- IM(Feishu)chips(无按钮承载;仅剥标记)
- 建议个性化/点击统计
- 图表与图片富渲染(sub-project B 的下一切片,另行 spec)

## 7. Brainstorm 过程留档

- 侦察确认:`renderMarkdown.ts:52-57` I#/R# 自动链接;`MessageList.tsx:34-40` 统一拦截点;`ContextPanel` 四 tab 组件完整但无打开入口(`setContextIssueId` 零调用方);done 事件 payload 在 `app.py:4560`;前端 done 解析在 `chatStream.ts` switch。
- 方案对比:A(提示词标记块,推荐)vs B(Haiku 后置生成,多一次调用+延迟,否)vs 纯前端正则解析(不可靠,否)。用户选 A。
- 交互三决策(chips 来源/I# 行为/点击行为)经 AskUserQuestion 确认,均取推荐项。
