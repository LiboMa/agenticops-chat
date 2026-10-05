# Issue / Change 统一工单模板（方案 A）设计

> **日期**：2026-10-04
> **分支**：`MVP-2.6.1`（worktree `.worktrees/mvp-2.6.1`）
> **状态**：待主人评审本 spec
> **来源**：`docs/design/2026-10-03-issue-change-ui-proposals.html`。该文件第 0 页「现状诊断」列出带编号的问题 I-a…I-i、C-a…C-g、L-a…L-g；「方案 A」页有线框 A-1…A-4；另有「公共修复」P1–P16 和「推荐」页。
>
> **主人决定**：
> - 2026-10-04 选方案 A。
> - 推荐页列出的四个「需要拍板的点」全部按推荐执行：
>   1. 问题分 4 个阶段；
>   2. 资源移出问题枢纽、单独进侧栏，信号改为 `/app/signals`；
>   3. 三套反馈合并为一个「你的判断」；
>   4. 修复方案不做独立列表。
>
> 线框以评审稿为准，本文不重复画。本文是实现的约束：评审稿和本文冲突时，以本文为准。

## 1 目标与可量化标准

主人原话：「Issue 页面看上去和使用上非常的乱……使 Issue / fix plan / Change 等功能更加规划、更加合理。」

**目标**：问题和变更共用一套详情模板。打开任何一张工单，一屏内能回答三件事：现在在哪一步、为什么停在这里、下一步谁做什么。两个列表共用一个表格组件。

**验收标准**（每条都能在 vitest 或走查里判定）：

1. 两个详情页的首屏都只有一个状态指示：一个状态行，包含状态、原因、等谁和**唯一一个主按钮**。7 步步进器、5 段进度条、头部三枚状态标签都不再出现在详情页上。
2. 主按钮由纯函数 `issuePhases` / `changePhases` 算出，与 §4 的映射表逐行一致，每一行都有单测。
   - 列表的「等谁 / 下一步」列也用同一个函数，所以列表和详情不会说两种话。
3. 一次失败的原因句在页面上只出现**一次**，放在状态行。执行卡只展示检查证据。
   - 用 C#1 形状的数据做组件测试：失败句的出现次数等于 1。
4. 问题详情不再有 tab，变更详情也不再是一页平铺。两者都改为一列阶段卡：
   - 已结束的阶段折叠成一句话；
   - 当前阶段展开；
   - 还没到的阶段只写一句「谁、在什么条件下推动它」，不放按钮；
   - 失败、回滚、拒绝、取消时，阶段列表在出事的那一段收尾，不再画后面的阶段。
5. 问题详情只剩一处反馈：「你的判断」，四选一，一次提交。
   - 👍👎、定位三选一、「误报 / 确认」三个旧控件都删掉。
6. 页面上可见的状态文案都走 locale，zh / en 成对出现，locale-parity 测试通过。
   - 列表不再显示原始枚举值，比如 `rca_done`；
   - 详情不再显示写死的英文，比如 `RCA Complete`、确认对话框文案；
   - 空字段不再显示：例如 `Model: |`，以及告警原始的 `unknown` / `—`。
7. 旧链接都不失效：
   - `/app/issues/:id?tab=<旧 tab>`；
   - `/app/issues?view=resources|signals`；
   - `/app/plans?…`（2.6.1 已有的重定向）；
   - 通知里的深链。
   每条映射都有单测。
8. 门禁（每一期都要过）：
   - `tsc --noEmit` 0 错误；
   - vitest 全过；
   - `vite build` 成功；
   - locale-parity 通过；
   - 后端全量 pytest 不低于当期基线。本设计开始时为 6357 passed / 85 skipped，另有 1 个已知的本机 DNS 假失败。

## 2 范围

**本 spec 包含四期，A1–A4，每期都能单独发布：**

| 期 | 内容 | 对应 |
|---|---|---|
| **A1** | 和信息架构无关的公共修复：P2、P6、P8、P11、P12、P13、P14、P15、P16，加上 P5 的后端字段 | 评审稿「公共修复」页 |
| **A2** | 模板组件 + 问题详情套用模板。组件有 StatusLine、PhaseCard、FactsRail、ActivityList、PlanView、VerdictBlock；另加 `lib/issuePhases.ts`、`lib/activity.ts`。同时完成 P1、P3（问题侧）、P4、P5、P7、P9、P10 | 方案 A · A2 |
| **A3** | 变更详情用同一批组件重组，另加 `lib/changePhases.ts`。同时完成 P3（变更侧）和 C-a…C-g | 方案 A · A3 |
| **A4** | 统一列表 WorkItemTable + 信息架构调整：资源独立入口、`/app/signals`、旧链接重定向 | 方案 A · A4 |

**本 spec 不包含：**

- A5「关联」：按资源反查同一资源上未关闭的工单（C-f），需要新增按资源过滤的 API 参数。
- 方案 B 的「待我处理」。
- 方案 C 的看板。
- 审计页改动。审计页的内容这次没能核实，只保留它在侧栏的位置。

## 3 信息架构与路由

**侧栏：**

- 之前：仪表盘 · 对话 · 问题（内含 问题 / 资源 / 信号 三个视图）· 变更 · 审计 · …
- 之后：仪表盘 · 对话 · 问题 · 变更 · **资源** · 审计 · …
- 信号不进侧栏，从两处进入：问题列表工具栏的「原始信号 →」，以及问题详情右栏「来源」一行的「合并信号 N 条 →」。

**路由（A4）：**

| 路径 | 之前 | 之后 |
|---|---|---|
| `/app/issues` | 问题枢纽，带 `?view=` 和 `?scope=` | 只放问题列表，保留 `?scope=`。带 `?view=resources` 时用 `replace` 跳到 `/app/resources`，带 `?view=signals` 时跳到 `/app/signals`，其余参数原样带上 |
| `/app/resources` | 不存在 | 新路由，渲染从 `IssuesAndPlans.tsx` 抽出来的 `ResourcesView`，行为不变（含「显示已缺席」开关） |
| `/app/signals` | 不存在 | 新路由，渲染现有的 `SignalsPanel` |
| `/app/issues/:id` | 用 `?tab=investigate\|fixPlan\|execution\|verification\|timeline` 选 tab | 改用 hash 锚点：`#diagnose` / `#plan` / `#run` / `#accept` 让对应阶段卡滚到可见并展开，`#activity` 让右栏「动态」展开。旧 `?tab=` 的映射：`investigate→#diagnose`、`fixPlan→#plan`、`execution→#run`、`verification→#accept`、`timeline→#activity`。映射时用 `replace`，所以不会多一条历史记录 |
| `/app/changes/:id` | 一页平铺 | 同样用 hash：`#request` / `#review` / `#plan` / `#run` / `#accept` / `#activity` |

**路由映射是一个纯函数**：`lib/workitemRoutes.ts`，负责旧参数到新地址的转换，配有单测。A2 先上线问题详情的 `?tab=` 映射，A4 再上线列表的 `?view=` 映射。

## 4 阶段模型（纯函数，单测覆盖每一行）

**阶段：**

- 问题：① 诊断（`diagnose`）→ ② 方案（`plan`）→ ③ 审批并执行（`run`）→ ④ 验收（`accept`）
- 变更：① 申请（`request`）→ ② 审核（`review`）→ ③ 方案（`plan`）→ ④ 审批并执行（`run`）→ ⑤ 验收（`accept`）

后三段（方案 → 审批并执行 → 验收）用同一组卡片和同一个 PlanView 渲染。

**「RCA 已过闸门」的定义**，与后端 `services/rca_quality` 的门一致：最新一次 RCA 的 `confidence ≥ rca_min_confidence_for_autofix`，并且 `critic_verdict ≠ "refuted"`。阈值从 `GET /api/settings` 新增的只读字段读取（§8）。

**`issuePhases(issue, rca, plan, latestRun, settings)` 的映射：**

| 问题状态与条件 | 当前阶段 · 子状态 | 等谁 | 主按钮 |
|---|---|---|---|
| `open` / `investigating` / `acknowledged` | ① · 进行中 | RCA 智能体 | 无（「⋯」菜单里有「运行 RCA」） |
| `root_cause_identified`，RCA 未过闸门 | ① · 待复核 | 你 | 「复核根因」：滚到「你的判断」 |
| `root_cause_identified`，RCA 已过闸门，或 `rca.human_verdict = "correct"` | ② · 待生成 | SRE 智能体 / 你 | 「生成修复方案」 |
| `root_cause_identified`，最新一次运行 `failed`（执行失败或验收被拒，RCA 已记为 disputed） | ② · 需新方案（③ 显示上一次运行的证据） | 你 | 「生成修复方案」；原因句 = 那次运行的 `verification_reason` 或验收理由 |
| `fix_planned`，方案处于 `pending_approval` 或 `draft` | ③ · 待审批 | 审批人 | 「批准并执行」 |
| `fix_approved`，方案 `approved`，还没有运行 | ③ · 需重试 | 你 | 「重试执行」 |
| `fix_executing` | ③ · 执行中 | 执行器 | 无（「⋯」菜单里有「取消执行」） |
| `fix_executed`，且最新一次运行是 `pending_acceptance` | ④ · 待验收 | 你 | 「接受结果」，旁边是「拒绝」 |
| `fix_executed`，最新一次运行 `passed`（`executor_auto_resolve=false` 时才会停在这里） | ④ · 已通过 | 你 | 「标记已解决」 |
| `resolved` / `dismissed` | 终态横幅 | — | 无（「⋯」菜单里有「重新打开」） |

> **2026-10-05 最终评审 C1 修订**：上表「`fix_approved`，方案 `approved`，还没有运行 → 需重试」一行的前提不成立。批准后 `trigger_auto_execute` 在后台线程里直接跑执行器，整段运行期间不写 FixExecution 记录（结束时才由 `save_execution_result` 写入），方案一直是 `approved`、问题一直是 `fix_approved`；按原表，页面会在整段运行期间说「已批准，未入队 · 等你」并把「重试执行」作为唯一主按钮，点下去会让第二个执行器并发跑同一方案。改为：「运行中」的信号取时间线——该方案最新一条 `execution_started` 之后同一问题没有 `execution_completed`，且开始不足 `executor_total_timeout` 秒（后端 `pipeline_service.plan_run_in_flight`，前端 `lib/issueDetail.inFlightAutoRun`，同一定义）。有这个信号时 ③ 为「执行中 · 等执行器 · 无主按钮」，「重试执行」只留在「⋯」里，并由后端兜底：`POST /api/fix-plans/{id}/execute` 在信号成立时返回 409「A run of this plan is already in progress」。没有信号（自动执行关闭，或在开始前就失败了）才是「需重试 · 重试执行」；时间线还没加载或加载失败时是中性状态，不说「未入队」。为此 `GET /api/settings` 多一个只读字段 `executor_total_timeout`（`PATCH` 收到返回 400），§8「不改」一段里「问题详情在 ③ 显示『需重试』」的说法以本段为准。

**`changePhases(cr, activePlan, latestRun)` 的映射：**

| 变更状态 | 当前阶段 · 子状态 | 等谁 | 主按钮 |
|---|---|---|---|
| `draft` | ① | 申请人 | 「发起审核」 |
| `under_review` | ② · 进行中 | SRE 智能体 | 无 |
| `needs_clarification` | ② · 待澄清 | 申请人 | 「回答审核方」：聚焦阶段卡里的输入框 |
| `planned` | ④ · 待审批 | 审批人 | 「批准并执行」 |
| `approved` | ④ · 需重试 | 你 | 「重试执行」 |
| `executing` | ④ · 执行中 | 执行器 | 无 |
| `needs_review` | ⑤ · 待验收 | 验收人 | 「标记完成」，旁边是「标记失败」 |
| `completed` | 终态，在 ⑤ 收尾 | — | 无 |
| `failed` / `rolled_back` | 终态，在 ④ 收尾 | — | 「复制为新变更」 |
| `rejected` | 终态，在审核或审批那一段收尾 | — | 「复制为新变更」 |
| `cancelled` | 终态，在取消时所处的那一段收尾 | — | 「复制为新变更」 |

**「⋯」菜单**里放全部次要动作，保留今天能做的一切：

- 问题：重新运行 RCA · 跳过复核直接生成修复方案 · 手动标记已解决 · 忽略 · 重新打开。
- 变更：拒绝 · 取消 · 复制为新变更 · 全部展开。

每个动作只在今天的规则允许时出现。例如 `canCancel` 只在这些状态为真：`draft`、`needs_clarification`、`planned`、`approved`。

## 5 组件契约

新组件放在 `components/workitem/` 和 `components/plans/`，只接 props、不自己取数据，取数据的事由页面完成。

| 组件 | 作用 | 输入 |
|---|---|---|
| `StatusLine` | 首屏唯一的状态指示：工单号、标题、徽章、状态名、原因（最多两行，超出折叠）、等谁、唯一主按钮、「⋯」菜单；出错时下方显示 ErrorBanner（409 / 403 的后端原话） | `{ref, title, badges, statusLabel, reason, waitingFor, primary?, menu[], error?}` |
| `PhaseCard` | 一个阶段：卡头是 `<button>`，Enter / 空格可折叠；`done` 显示一句话摘要，`current` 展开，`future` 显示一句说明，`failed` 红框并自动展开；外层有「全部展开」 | `{id, index, title, state, summary, children}` |
| `FactsRail` | 右栏「关键事实」：没有值的行不渲染 | `{rows: {label, value, href?}[]}` |
| `ActivityList` | 右栏「动态」：一事件一句话，连续重复的事件合并成「×N」，原始 JSON 收在「原始事件 (N)」开关里 | `{entries}`，由 `lib/activity.ts` 生成 |
| `PlanView` | 修复方案和实施方案共用：方案名（`plan_label`）、版本、哈希、批准哈希是否一致；步骤 / 预检 / 后检 / 回滚四个计数；用现有 `RunbookStep` / `CheckItem` / `RollbackPlan` 渲染；变更多一行「与请求的差异」（来自 `steps_diff`），修复方案没有这一行 | `{plan, kind, stepsDiff?}` |
| `VerdictBlock` | 「你的判断」，四选一（§6.1） | `{issueId, rca, onDone}` |
| `WorkItemTable` | 问题和变更两个列表共用；列依次为 # · 标题（含副标题）· 状态（阶段点 + locale 状态名）· 等谁 / 下一步 · 严重度或风险 · 账户 · 更新时间 | `{rows, columns, onRowClick}` |

**`lib/activity.ts`**：每种事件对应一个 locale 句子模板，`activity.<event>`。`authz.denied` / `authz.denied_shadow` 翻成一句话：「规则 X 拦下了 Y 的 Z」。现有 `PipelineTimeline` 的数据来源不变，只换渲染。

## 6 页面组装

### 6.1 问题详情（A2）

**布局**：左栏是 StatusLine + 4 张阶段卡，右栏是 FactsRail + ActivityList。

- **① 诊断**：
  - RCA 根因原文；
  - 置信度条，带阈值竖线，下面写出推导：原始置信度 → ×0.6（证据核验未通过）→ 最终值，并与阈值比较。评审员结论写成人话，`weak` 不扣分；
  - 未核实的引用列表；
  - 定位卡：候选、证据标签、路径；
  - 「贡献因素」「建议」「局部拓扑」默认折叠；
  - VerdictBlock。
- **局部拓扑（P11）**：默认只画锚点的 1 跳邻居加因果路径，最多 15 个节点。非路径节点悬停才显示标签。有「显示全部 N 个」开关，打开后就是今天 LocalGraph 的完整视图。
- **② 方案**：PlanView，加上方案的批准状态。
- **③ 审批并执行**：
  - 审批记录：谁、何时、哪个版本、哈希、理由；
  - 执行记录：保留今天的执行证据，`ExecutionEvidence`；
  - 「批准并执行」打开 ReasonDialog。对话框标题是「批准并执行 I#n 修复方案 vN」，副标题显示哈希，理由选填，这一点和今天一样。
- **④ 验收**：显示判定 `VerificationChip` 和原因；待验收时显示「接受结果 / 拒绝」，理由必填。
- **右栏关键事实**：
  - 锚点显示锚定资源的名称和类型，链接到资源详情，不再显示告警原始 `resource_id`（P8）；
  - 另有根因资源、账户、严重度、来源（含「合并信号 N 条 →」）、检测时间、Trace。

**VerdictBlock 的四个选项**，都只调用现有端点：

| 选项 | 调用 | 约束 |
|---|---|---|
| 根因和定位都正确 | `POST /api/health-issues/{id}/rca-feedback`，带 `{verdict:"correct", location_verdict:"correct"}`，再 `POST …/feedback`，带 `{type:"confirmed"}` | 定位是 `absent` / `invalid` 时，不发 `location_verdict` |
| 部分正确（根因对，定位不全或排序不对） | `rca-feedback`，带 `{verdict:"correct", location_verdict:"partial"}`，再 `feedback`，带 `confirmed` | 定位不是 `valid` / `partial` 时，这个选项置灰并说明原因（后端会返回 409） |
| 根因错误 | `rca-feedback`，带 `{verdict:"incorrect", location_verdict:"incorrect"（有定位时）, note}` | 备注必填 |
| 这不是问题（误报） | `feedback`，带 `{type:"false_positive", note}`（后端会把问题置为 dismissed） | 备注必填 |

两次调用按顺序发。第二次失败时 ErrorBanner 写明哪一次成功了，不回滚。刷新复用现有的失效逻辑。

### 6.2 变更详情（A3）

**布局**：同一模板，5 张阶段卡。

- **① 申请**：申请人、外部单号、目标、理由、申请里的步骤。
- **② 审核**：
  - SRE 的结论、动作、策略决定；
  - 策略理由只显示 3 条，其余折叠；
  - 影子影响的数字和图默认收起，并注明「仅供参考」，前提是 `policy_graph_impact_enforce=false`，和今天一样；
  - 待澄清时，输入框放在这张卡里。
- **③ 方案**：PlanView，加上 `steps_diff`。
- **④ 审批并执行**：
  - 「批准并执行」打开 ReasonDialog，理由必填，哈希在**打开对话框时**取定（Ruling E-T5b）；
  - 「重试执行」只在状态为 `approved` 时出现；
  - 执行卡只放检查证据，不重复原因句（P3）。
- **⑤ 验收**：`needs_review` 时显示「标记完成 / 标记失败」，理由必填。系统已判定失败时只写一句「系统已判定失败（见执行 #n）」。

### 6.3 列表（A4）

**问题列表**：

- 4 行叠放的筛选压成一行：状态、严重度、范围（`?scope=`）、账户四个下拉，加排序、搜索和「原始信号 →」；
- 表格用 WorkItemTable。

**变更列表**：保留今天的筛选（状态 / 账户 / 申请人 / 时间窗）和「新建变更申请」，表格换成 WorkItemTable。

## 7 必须保留的现有行为（每条都有现成测试或新增测试守住）

**问题详情：**

1. 当问题处于 `fix_approved` / `fix_executing`，或有运行处于 `pending` / `running` 时，每 5 秒轮询一次，有上限；状态一变，就更大范围地失效缓存并重新拉取执行记录（94530d0）。
2. 只有问题处于 `fix_executed` 时，才能验收它的**最新一次**运行（Ruling E-T4a）。
3. `resolved` / `dismissed` 问题的方案不提供「批准」（`canApprovePlan`）；`approvalBlockedReason` 照旧显示。
4. 执行记录拉取失败时显示 ErrorBanner。
5. 待验收时，问题和变更顶部的原因是同一句（`needs_review_reason` 和 `verification_reason` 是同一来源）。
6. LocalGraph 的「在全景图中查看」深链保留，链接形如 `/app/galaxy?focus=`。
7. 合并告警（MergedAlertsSection）的内容移到右栏「来源」一行和信号页；用到的数据不变。

**变更详情：**

8. 批准的对象是 `activeChangePlan`，即最新的非终态方案（Ruling E-T5a），不是 `cr.plans[0]`。
9. 外部单号链接（`externalRefLink`）、申请步骤的标记（`planStepMarks`）、`isHintResolved` 照旧。
10. 「复制为新变更」只在 `canCopy` 的状态出现，打开现有 NewChangeDialog 并预填。
11. 取消、拒绝都要填理由（ReasonDialog）。

**所有弹层**都用 `animate-[slideInRight_0.2s_ease-out]`，并能用 ESC 关闭（项目规则）。

## 8 数据与 API

**新增：**

- `GET /api/settings` 加一个只读字段：`rca_min_confidence_for_autofix`（数字，即 `settings.rca_min_confidence_for_autofix`）。
- `PATCH /api/settings` 收到这个字段时返回 400，做法与 `policy_graph_impact_enforce` 相同。

**不新增端点。复用：**

- `GET /api/health-issues/{id}`、问题的 RCA 端点、`/api/fix-plans?health_issue_id=`、`/api/fix-executions?fix_plan_id=`、时间线端点；
- `POST /api/health-issues/{id}/rca-feedback`、`POST /api/health-issues/{id}/feedback`；
- `PUT /api/fix-plans/{id}/approve`、`POST /api/fix-plans/{id}/reject`、`POST /api/fix-plans/{id}/execute`、`POST /api/fix-executions/{id}/accept`；
- `/api/changes/*`，包括已实现的批准即执行（e762b9a）；
- `GET /api/graph/focus`、`/api/signals`。

**不改：**

- 修复方案侧「已批准、未入队」时，`trigger_auto_execute` 只写一条日志，不发通知；变更侧会发 `execution_not_queued`。这处不对称本 spec 不改，记作已知缺口。UI 侧的处理是：问题详情在 ③ 显示「需重试 · 重试执行」，所以没有通知也能看出状态。

## 9 六个可达面

| 面 | 本 spec |
|---|---|
| CLI | **非目标**。`aiops chat`、`/change`、`/approve`、`/accept` 不变 |
| Web API | **做（极小）**。只在 `GET /api/settings` 加一个只读字段 `rca_min_confidence_for_autofix`，`PATCH` 收到它返回 400；不新增端点 |
| Web UI | **做**。重写 `pages/IssueDetail.tsx` 和 `pages/ChangeDetail.tsx`；`pages/IssuesAndPlans.tsx` 只留问题，资源和信号拆成新页面 `/app/resources`、`/app/signals`；`components/plans/ChangePlansTab.tsx` 改用 WorkItemTable（`pages/Changes.tsx` 的标题和「新建变更申请」按钮不变）。新增 `components/workitem/{StatusLine,PhaseCard,FactsRail,ActivityList}.tsx`、`components/plans/PlanView.tsx`、`components/issue/VerdictBlock.tsx`、`components/ui/WorkItemTable.tsx`，以及 `lib/{issuePhases,changePhases,activity,workitemRoutes}.ts` 和对应测试。还要改 `components/layout/NavItems.tsx`（加「资源」）、`App.tsx`（路由和重定向）、`locales/{zh,en}.json`。详情页不再使用 `IssueStatusStepper`、`PipelineStepper`、`IssueActionBar`、`ChangeStepper`；这些组件别处还在用的保留，没人用了就删掉 |
| Agent tool | **非目标** |
| Schedule | **非目标** |
| Notification | **非目标**。通知里的深链 `/app/issues/:id`、`/app/changes/:id` 照常打开，旧 `?tab=` 也能映射 |

## 10 错误与边界

- **接口错误**：409 / 403 的后端原话显示在状态行下方的 ErrorBanner 里，不弹 toast。典型文案：「方案已更新到 v2，请重新查看」「按职责分离规则，申请人不能批准自己的变更」。
- **缺数据**：
  - 没有 RCA：① 显示「进行中」或「未运行」，「⋯」菜单里有「运行 RCA」。
  - 定位为 `absent`：定位卡写「本次 RCA 没有给出定位」，VerdictBlock 的「部分正确」置灰。
  - 没有方案：② 写一句「谁、在什么条件下推动它」。
- **字段为空**：不渲染这一行，不显示 `unknown` / `—` / `|`。
- **长文本**：状态行原因最多两行，其余展开查看。命令与 RCA 原文不翻译。
- **英文更长**：主按钮固定在右侧、不换行。

## 11 测试

**纯函数（vitest）：**

- `issuePhases`、`changePhases`：§4 两张表逐行覆盖，含「已过闸门 / 未过闸门」「`critic_verdict=refuted`」「最新运行是 `pending_acceptance`」「终态收尾的位置」；
- `activity`：句子模板；重复合并；`authz.denied` 的翻译；
- `workitemRoutes`：旧 `?tab=` / `?view=` 的映射；
- VerdictBlock 四个选项生成的请求体，抽成纯函数测试。

**视图模型测试**：前端没有 Testing Library / jsdom，本 spec 也不为它新增依赖。页面先由纯函数 `issueDetailModel` / `changeDetailModel` 算出「状态行 + 阶段卡 + 右栏」要显示的内容，再渲染；测试只断言这些纯函数的输出：

- C#1 形状的数据：模型里失败句只出现一次；
- I#1 形状的数据：只有一个主按钮，且是「复核根因」。

**locale-parity**：新增的键 zh / en 成对出现。

**后端**：

- 新增一个测试：`GET /api/settings` 含 `rca_min_confidence_for_autofix`，`PATCH` 返回 400；
- 全量 pytest 不低于基线。

**现有测试**：`issueDetail`、`changeDetail`、`changeStepper`、`issueScope`、`plans`（legacy 重定向）等测试里，被删除或改名的函数先迁移再删。不允许因为页面重写而减少对第 7 节行为的覆盖。

**走查**：每一期在 chaos-lab 上用真实的 I#n / C#n 走一遍。与当前联合 E2E 的关系见 §12。

## 12 分期、提交与部署

- **执行方式**：A1 → A2 → A3 → A4 依次做。每期 TDD：先提交失败的纯函数测试，再提交实现；跑完当期全部门禁才提交。只做本地提交，推送仍等主人确认。
- **部署顺序**（主人 2026-10-03 已定）：
  1. 先在当前镜像 fe7e9fd 上走完联合 E2E 第 2、6、7 项；
  2. 再部署包含「批准即执行」的新镜像，重走第 3 项。
  本 spec 的 A1–A4 在那之后合进同一批镜像，或下一批镜像，由主人定。
- **文档**：每期结束更新这些文档：
  - `CLAUDE.md` 前端一节的页面与组件清单；
  - `docs/WORKFLOW.md` 的 Web 操作段落；
  - `docs/MVP-2.6.1-RELEASE.md`：新增一节「2.6.1 之后：统一工单模板（方案 A）」，与「变更批准即执行」同列为联合 E2E 期间主人要求的改动（主人若要另起 2.6.2 发布说明，只是把这一节挪过去）；
  - 如果涉及 README，`README.md` 与 `README_CN.md` 在同一提交内同步。

## 13 刻意不做

- 独立的修复方案列表页。跨工单的「待批」留给方案 B。
- 把问题和变更合并成同一个实体或同一个列表：两个列表共用一个表格组件即可。
- 批量操作、拖拽、看板。
- 新增端点，以及按资源过滤的参数（属于 A5）。
- 审计页改动。
- 修复方案侧「未入队」时的通知（§8）。

## 14 风险

- **问题详情里的隐式逻辑多**：轮询、失效范围、验收资格、`approvalBlockedReason`。
  缓解：先把这些逻辑抽进 `lib/*` 的纯函数并补测试，再换页面；第 7 节逐条守住。
- **折叠可能藏起有人依赖的信息**，比如局部图和策略理由。
  缓解：「全部展开」；hash 锚点能直达某一阶段；局部图有「显示全部」开关。
- **旧深链**：通知、聊天里的 `I#` / `C#` 链接、`?tab=`。
  缓解：`workitemRoutes` 统一映射，并有测试。
- **两个大页面一起重写，改动量大**：`IssueDetail.tsx` 现有 1259 行，`ChangeDetail.tsx` 现有 732 行。
  缓解：A2、A3 分开做；共享组件在 A2 里先用在问题详情上，验证过再用到变更详情。
