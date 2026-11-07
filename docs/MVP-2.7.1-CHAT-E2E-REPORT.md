# MVP-2.7.1 · ChatGPT 风格 Web Chat — 端到端验证报告

2026-11-07/08 · 本机，分支 `MVP-2.7.1`（`cd4f0d2` → `8a57088`），`aiops service`，真实模型（Main = Opus 5.5，Bedrock） · Playwright（Chromium）· 设计：`docs/superpowers/specs/2026-11-07-chatgpt-style-chat-design.md` · 计划：`docs/superpowers/plans/2026-11-07-chatgpt-style-chat.md`

测试账户 `e2e-chat`（writer，非管理员，验证结束后停用），测试会话都开在这个账户下。

## 结论

规定的场景全部通过，另有一项没测，见文末「没验证的」：
- **桌面端 10 项**：富内容渲染、工作过程、刷新后内容一致、脱敏、拖入附件、按键、回到底部、重新生成、深色模式。
- **移动端 7 项**。
- **性能 3 项**。
- **纯文本渠道 1 项**。

E2E 过程中发现 6 个问题，都已修复，每个都先写了失败的测试或实测数据，再修复，见「E2E 中发现并修复的问题」。

## 闸门

| 闸门 | 结果 |
|---|---|
| 后端全量 `pytest tests/`（临时库） | 7360 passed · 99 skipped · 4 failed。4 个失败都与本改动无关：<br>• 2 个 `test_claude5_bedrock_models::TestClaude5SettingsSync`：本机未提交的 `config/settings.yaml`（主人自己的模型选择）；<br>• 1 个 `test_prompt_budget::test_no_cjk_in_base_prompts`：本机未提交的 `reporter_agent.py` 中文提示行；<br>• 1 个 `test_web_tools::test_invalid_headers_json`：本机 DNS 的已知误报。<br>前 3 个在干净的 HEAD 检出上重跑：127 passed |
| 前端 `vitest --run` | 70 个文件，769 个测试全部通过 |
| `tsc --noEmit` | 0 |
| `/tmp` 空目录 `npm ci && npm run build && vitest` | 全部 exit 0；产物里有独立的 `mermaid.core-*.js` |

## 桌面端（1440×900）

| # | 场景 | 结果 | 证据 |
|---|---|---|---|
| 1 | **统计问题出图**：「各严重级别的未关闭健康问题各有多少个，并画成图」 | PASS | 柱状图按真实数据渲染，两个系列，有图例，图例文字用正文颜色，没有 ASCII 图；表格正常；有操作栏和「下一步」建议<br>![](images/chat-e2e-2026-11-07/chart-final.png) |
| 1b | **工作过程实时显示** | PASS | 运行中逐步出现，每步带摘要（如 `severity=high status=open`）和耗时；完成后收成一行<br>![](images/chat-e2e-2026-11-07/live-steps2.png) |
| 2 | **流程图**：「一条告警从 webhook 进来到自动修复完成的流程」 | PASS | mermaid SVG 渲染，`.aiops-mermaid svg` = 1，没有 ASCII；点开后可以缩放到 125%，ESC 关闭<br>![](images/chat-e2e-2026-11-07/mermaid.png) ![](images/chat-e2e-2026-11-07/zoom.png) |
| 3 | **markdown 表格** | PASS | 见 1 |
| 4 | **刷新后内容一致** | PASS | 重新载入会话后点开工作过程，前几步（`get_active_account` 0.3 秒、`list_health_issues limit=500` 0.3 秒……）与实时显示一致，数据来自库里的 `tool_calls` |
| 5 | **脱敏** | PASS | 让 agent 调 `search_agent_memory`，传入 `postgresql://admin:S3cretPass42@db:5432/app`：<br>• 工作过程摘要显示为 `postgresql://admin:[REDACTED-SECRET]@db:5432/app`；<br>• 库里 `chat_messages.tool_calls` 中找不到 `S3cretPass42`；<br>• 单元测试覆盖四种写法（`--password` 的值、`aws_secret_access_key <值>`、`Bearer` token、URL 的 `user:pass@`）以及 ARN 不被误盖 |
| 6 | **拖入对话区任意位置**（PNG / PDF / XLSX / EXE） | PASS | 拖到消息区中央就出现淡色提示。放下后：<br>• 附件进到输入框里：图片缩略图带圆形进度，PDF 是红色卡片、XLSX 是绿色卡片，处理完显示「1 page · 1 KB」「5 KB」；<br>• EXE 显示为红色卡片并写明原因；<br>• 计数「3/20 · 6 KB / 200 MB」；<br>• 处理完成前发送键为灰色（`sendDisabledEarly: true`），完成后可用<br>![](images/chat-e2e-2026-11-07/drag-over.png) ![](images/chat-e2e-2026-11-07/drop-early.png) ![](images/chat-e2e-2026-11-07/drop-done.png) |
| 6b | **带附件发送** | PASS | 模型读了三个附件，并把 XLSX 的数据画成了柱状图<br>![](images/chat-e2e-2026-11-07/attach-answer.png) |
| 7 | **按键** | PASS | Shift+Enter 换行；发一个 `isComposing: true` 的 Enter，不会发送；Enter 发送 |
| 8 | **回到底部** | PASS | 向上翻后出现「↓」按钮，点击后回到底部，按钮消失 |
| 9 | **重新生成** | PASS | 最后一条回答可用：点击后再发一次原问题，出现新的用户消息和新回答，重新生成按钮仍只在最后一条回答上。原问题带附件时按钮置灰，提示「The attachments went with the original message — attach them again and send.」 |
| 10 | **深色模式** | PASS | 图表和流程图（mermaid dark 主题）都清晰可读<br>![](images/chat-e2e-2026-11-07/dark-chart.png) ![](images/chat-e2e-2026-11-07/dark-mermaid.png) |
| — | **骨架** | PASS | 全局导航收成图标栏；对话列表默认展开；空对话时输入框居中<br>![](images/chat-e2e-2026-11-07/welcome-desktop.png) |

## 移动端（390×844）

| 场景 | 结果 | 证据 |
|---|---|---|
| 对话列表抽屉 | PASS | 从左上角按钮打开；选中一个对话后抽屉关闭并跳转<br>![](images/chat-e2e-2026-11-07/m-drawer.png) |
| 输入框贴底 | PASS | 输入框在 y≈753，在视口底部<br>![](images/chat-e2e-2026-11-07/m-session.png) |
| 输入框里的附件横向滚动 | PASS | 附件行 `flex-wrap: nowrap` + `overflow-x: auto` |
| 「＋」菜单 | PASS | 有「Upload files」「Upload images」。「拍照」只在触屏（`pointer: coarse`）下出现，见「没验证的」 |
| 图表 / 流程图适配宽度 | PASS | 图表 100% 宽；流程图缩到 352 px 宽显示，点开可全屏缩放 |
| 大图预览左右滑动 | PASS | 合成 touchstart/touchend 后，`a.png 1/2` 切换为 `b.png 2/2`；同时验证了点输入框里的缩略图能打开预览<br>![](images/chat-e2e-2026-11-07/m-lightbox.png) |
| 主要按钮的点击区域 | PASS（修复后） | Send、＋、复制、重新生成、⋯、对话列表都是 44×44 px |

## 性能与按需加载

| 场景 | 结果 | 证据 |
|---|---|---|
| 没有流程图的对话不下载 mermaid | PASS | 新开页面打开统计对话，没有任何 mermaid / flowDiagram / dagre 请求；打开流程图对话时才加载 `mermaid.core`、`flowDiagram`、`dagre` |
| 200 条消息的长对话（临时造数：表格，每 10 条一张图） | PASS（修复后） | 打开时停在底部（距底 1 px）；用鼠标滚轮翻到最顶，200 条全部加载到「问题 0」；滚动过程中行重叠 0 次；回到底部后保持吸底。测试会话已删除（DELETE 204） |

## 纯文本渠道

| 场景 | 结果 | 证据 |
|---|---|---|
| CLI 不出现富块 | PASS | `aiops chat "按严重级别统计…并画出告警到自动修复的处理流程"`：输出里 ```` ```chart ```` 0 处，```` ```mermaid ```` 0 处，CLI 照旧输出纯文本。IM 和定时任务走同一个默认构建（`create_main_agent()` 不带 `rich_output`），`tests/test_main_agent_rich_output.py` 已锁定 |

## E2E 中发现并修复的问题

1. **步骤耗时虚高**（`4256b86`）。
   - 现象：一次并行的 44 个调用，单步耗时显示为 14 秒、13 秒……0.6 秒，总计「4 分 39 秒」，而这一轮实际只用了约 2 分钟。
   - 原因：从模型开始写这次调用时就开始计时；总计又是各步耗时相加。
   - 修复：输入写完、开始执行时才计时，每步记录 `started_ms`；总计改为实际时间跨度。旧消息没有 `started_ms`，仍然相加。
   - 测试：`test_a_step_is_timed_from_when_it_runs_not_from_when_the_model_began_writing_it`，`workTotals` 跨度用例。
2. **对话列表太挤**（`4256b86`）。
   - 现象：220 px 宽时，标签和上下文挤在一行，标题只剩「Chat 2…」。
   - 修复：标题单独一行；可见性标签和上下文放在第二行，用浅色小字；默认宽度改为 260 px。
3. **图例文字用了系列颜色**（`4256b86`）。按 dataviz 规范改为正文颜色。
4. **被拒附件的卡片重复文件名，以及「1 pages」**（`6b4100b`）。测试：`attachments.test.ts`「composer card copy」。
5. **手机上点击区域不够**（`84d3beb`）。
   - 现象：实测 26–38 px，根字号是 15 px，rem 尺寸会缩小。
   - 修复：改成固定的 44 px。
6. **长对话打开时停在半截**（`40ad813`）。
   - 现象：200 条消息的对话打开后，距底部还有 2104 px。
   - 原因：行的实际高度比估计的高（有表格、图表），虚拟列表调整滚动位置时触发的 scroll 事件被当成「用户上翻」。
   - 修复：只有用户手势（滚轮、触摸、按键、指针）才会取消吸底。
   - 测试：`stickToBottom.test.ts`。

## 没验证的

- **移动端「拍照」菜单项。** 它只在 `pointer: coarse`（触屏）下出现，Playwright 调整窗口大小模拟不出触屏，需要在真机上看一下。
- **IM / 定时任务的真实回答。** 这两条路径的提示词与 CLI 是同一个默认构建，已由单元测试锁定，没有真的发一条飞书消息或跑一次定时任务。

## 顺带观察到的（不在本次范围，供主人决定）

- **`list_health_issues` 无法统计总数。** 结果超过约 6000 字符会被截断，而且不能翻页。为了统计总数，模型把查询拆成了 32 个组合，这一轮跑了约 2 分钟、44 步。模型自己的建议是给这个工具加计数和分页。
- **模型对「带凭证样子的命令」会返回空回答。** 让 agent 执行 `kubectl get ns --token=FAKE-…` 时，模型输出 0 token，库里存了一条空的已完成回答，界面上什么也不显示。这是 S5 起就有的行为：空回答没有提示。
- **嵌套列表。** 自研 markdown 渲染器不支持嵌套列表，子项会被拉平。
- **CLI 输出末尾。** headless 模式下回答末尾会原样带上 `<<SUGGEST>>[…]` 那一行。这是现有行为。
