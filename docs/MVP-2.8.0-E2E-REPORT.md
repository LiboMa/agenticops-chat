# MVP-2.8.0 E2E 报告

每个阶段跑完都在这里追加一节。只追加，不改写前面的内容。

## S1（2026-11-09）

### 环境

- 代码：worktree `.worktrees/mvp-2.8.0`，分支 `MVP-2.8.0`。前端用 worktree 自己 `npm run build` 出来的 dist。
- 实例：一个独立的 uvicorn 进程，地址 `127.0.0.1:8001`，`--workers 1`，环境变量设为：
  - `AIOPS_DATA_DIR=/tmp/aiops-280-e2e/data`
  - `AIOPS_DATABASE_URL=sqlite:////tmp/aiops-280-e2e/agenticops.db`
  - `AIOPS_LOG_DIR=/tmp/aiops-280-e2e/logs`
  - `AIOPS_API_AUTH_ENABLED=true`
- 数据库：本地 `data/agenticops.db` 的副本。
  - 用 sqlite 的在线备份 API 从只读打开的源库复制：源库是 WAL 模式，直接 `cp` 可能漏掉还在 `-wal` 里的提交。
  - 副本里的 17 个定时任务全部停用，所以这个实例的调度器什么都不会跑。
  - 主人正在运行的 :8000 服务、真实数据库和主检出都没有碰。
- 账户：`e2e-admin`（管理员）、`e2e-viewer`（只读）、`e2e-editor`（只读，能只读打开 Settings）。都是用 `aiops users create` 在副本库里建的。
- 浏览器：Playwright，时区 `Asia/Shanghai`，界面语言中文。宽度 1440 / 390 / 320 px。

### 结果

| # | 检查 | 结果 | 证据 |
|---|---|---|---|
| 1 | 安全页正常加载 | PASS | 六个模块都有内容；趋势显示「最近 30 天没有评分记录」，是请求成功后的空状态<br>![](images/mvp-2.8.0-s1-e2e/s1-security-normal.jpg) |
| 2 | 拦截 `/api/security/findings` 返回 503 | PASS | 只有发现模块显示「加载失败 · Service Unavailable」+「重试」，其他模块照常显示 |
| 3 | 拦截 `/api/security/recommendations` 返回 `[]` | PASS | 显示「没有待处理的建议。」，是空状态，不是错误<br>![](images/mvp-2.8.0-s1-e2e/s1-security-503-empty.jpg) |
| 4 | 先加载成功，再让刷新失败 | PASS | 继续显示旧的发现，上方是「刷新失败，正在显示上次成功获取的数据 · 数据截至 23:48 UTC」+「重新获取」<br>![](images/mvp-2.8.0-s1-e2e/s1-security-stale.jpg) |
| 5 | 慢网络：发现接口延迟 4 秒 | PASS | 发现模块显示「加载中...」，别的模块已经显示内容 |
| 6 | 长标识符标题：I#374（标题是一整串 ARN）和计划 #148 | PASS | 390 / 320 px 下 `scrollWidth == clientWidth`<br>![](images/mvp-2.8.0-s1-e2e/s1-issue-374-390.jpg) ![](images/mvp-2.8.0-s1-e2e/s1-plan-148-320.jpg) |
| 7 | 改到的 8 个页面在 390 / 320 px 下都没有整页横向溢出 | 修复后 PASS | 页面：问题、计划、安全、定时任务、任务详情、设置、报告、对话。第一轮实测有 4 个页面溢出：计划里的长命令文本（多出 10–54 px）、Schedules 页头（多出 16–86 px）、Settings 的 Galaxy 模型行和连接器表（多出 61 px）、Reports 页头（多出 17 px）。修复在 `c54abba`，复测全部为 `scrollWidth == clientWidth` |
| 8 | 聊天输入区（R04） | PASS | 390 px 下文本框宽 336 px（≥ 300），320 px 下 266 px（≥ 250）；输入长中文加一段多行代码后，页面没有横向滚动<br>![](images/mvp-2.8.0-s1-e2e/s1-chat-390.jpg) |
| 9 | 设置开关，管理员 | PASS | 13 个 `role=switch`，每个都有名称（Auto RCA、Auto Fix Pipeline、Executor……）。聚焦后按 Space 切换为 false，再按一次回到 true。焦点环可见 |
| 10 | 设置开关，`e2e-editor` | PASS | 13 个开关都是 `:disabled`（外层是 `fieldset disabled`），按 Space 不改变状态 |
| 11 | 全局搜索：键盘全流程 | 修复后 PASS | Enter 打开后，焦点在 combobox 上。输入「security」后，播报「20 条结果」。按 ↓↓，`aria-activedescendant` 指向 `role=option`、`aria-selected=true` 的那一行。Tab / Shift+Tab 都留在弹层内。按 Esc 关闭。<br>第一轮实测：关闭后焦点落在 `<body>`。原因是 Radix 把焦点还给 `Dialog.Trigger`，而这个弹层没有 Trigger。修复在 `eeeacdf`（打开时记下来源元素），复测焦点回到搜索按钮。输入「374」再按 Enter，跳到第一条结果<br>![](images/mvp-2.8.0-s1-e2e/s1-palette-results.jpg) |
| 12 | 全局搜索：拦截 `/api/search` 返回 503 | PASS | 显示「搜索失败」+「重试」，读屏播报「搜索失败」，不显示「没有找到」<br>![](images/mvp-2.8.0-s1-e2e/s1-palette-failed.jpg) |
| 13 | 定时任务列表 | PASS | 新建一个停用、从没跑过的任务：「已停用 · 尚未运行 · 还没有执行记录」，运行时间为「—」。<br>`k8s-discovery`：「失败」+ kubectl 的错误摘要。<br>一次性任务：「一次性」，不再显示「Running / Completed」。<br>`security-incremental-poll` 显示「结束于 Sep 3」：这是数据库里真实的最新一条，这个任务在本地 9 月 3 日之后没再跑过，84 条记录里最新的就是这条<br>![](images/mvp-2.8.0-s1-e2e/s1-schedules.jpg) |
| 14 | 任务详情的「立即运行」 | PASS | `k8s-discovery`：点了之后先显示「已提交，等待执行记录」，随后出现 `#2285 运行中`（页面自动刷新出来的），跑完后是「失败」，带错误；列表里同一行也是「失败」<br>![](images/mvp-2.8.0-s1-e2e/s1-schedule-submitted.jpg) ![](images/mvp-2.8.0-s1-e2e/s1-schedule-after-run.jpg) |
| 15 | 没有 outcome 的历史工具步骤 | PASS | 会话「EOS/EOL Coverage Assessment Needed」里有 11 条旧的工具调用。展开工作过程后，那一步是灰点 +「结果未知」，以前是成功色的蓝点<br>![](images/mvp-2.8.0-s1-e2e/s1-worksteps-unknown.jpg) |
| 16 | 报告列表按 UTC 日分组 | PASS | 浏览器时区是 `Asia/Shanghai`，分组标题却是「2026年11月8日周日（UTC）」这样的 UTC 日。R#157 创建于 UTC 11-07 16:09（上海已是 11-08 00:09），它在「2026年11月7日周六（UTC）」组里，时间显示「16:09 UTC」<br>![](images/mvp-2.8.0-s1-e2e/s1-reports-utc.jpg) |

### 跑 E2E 时发现并修复的问题

1. **长文本把页面撑宽**：计划里的长命令、两个页头、Settings 的两处在 320 / 390 px 下撑宽页面。修复在 `c54abba`，复测见第 7 项。
2. **全局搜索关闭后焦点丢失**：落到 `<body>`。修复在 `eeeacdf`，复测见第 11 项。
3. **一次性任务的说明后面多了一个分隔符**：显示成「一次性 ·」。修复在 `bbfa0cb`。

### 看到了，但不属于 S1（留给后面的阶段）

- 账号卡片：
  - `Agenticops-CN` 显示 100.0 分：采集失败时的假满分，S3 修；
  - 两个账号都显示「821 未关闭」：这是全局数，S3 修。
- 雷达没有标明属于哪个账号；有的暴露路径可达性是原始值 `n/a`：S3。
- 设置项名称是英文：S8。
