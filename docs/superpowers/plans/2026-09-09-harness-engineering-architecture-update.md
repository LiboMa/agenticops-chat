<!-- Harness Engineering 计划 · 2026-09-09 · 状态：主人已批准方向并对 §六 四项决策拍板（见附录 B）；下一步 = 阶段 0 第一个 PR：L0 宪法评审 -->

# Harness Engineering 计划：用 Skills / Loops / 系统提示词三条轴完成整体架构更新（供 Review）

## Context

`docs/AGENTIC-SRE-READINESS-AUDIT-2026-08-29.md` 已经定义了目标架构：**Investigation Runtime**（InvestigationRun / 竞争假设 /
Typed Tasks / 证据账本 / 停止条件）、**Trust Kernel**（RCA fail-closed、RcaRun lease、独立 VerifyGate、trust invariants）、
**Outcome-weighted Memory**。它回答了"要变成什么"，没回答"harness 怎么搭"。本计划只回答后者：**把 harness 当产品来设计**——
系统提示词是契约不是教程，循环是带预算与停止原因的状态机不是"让 agent 转到它觉得完了"，Skills 是能力包不是文档。

### 现状（已核实，是本计划的起点，不是批评）

| 轴 | 现状 | 证据 |
|---|---|---|
| **系统提示词** | 每个 agent 一段 1,000–2,600 token 的手写命令式散文；Main 有 12+ 条编号路由规则，其中 9.5–12 实际是**工具用法清单**；组装顺序已按缓存稳定性排好（base → skills XML → output rules → memory 最后）；有 golden 预算测试（skills XML < 5k 字符、总装 < 20k） | `agents/main_agent.py:77-208`，`agents/preamble.py:117-179`，`tests/test_prompt_budget.py` |
| **循环** | Strands 单 agent 事件循环（RCA `max_iterations=40`），服务层串起 auto-RCA → 质量门 → SRE → 审批 → 执行 → resolved；RCA 有 900s 看门狗（线程不可杀，超时只打标）；质量门是 **fail-soft**（evidence 空 → `verified=None` 不阻断；critic 异常 → 跳过）；Executor 自报 success → 代码写 `resolved` | `services/rca_service.py:47-100`，`services/pipeline_service.py`，审计 §3.3 / §3.4 |
| **Skills** | 16 个知识型技能（决策树 + 参考）+ 部分带 `tools:` 动态注册；三层披露（XML 索引 → activate → reference）；agent 可写草稿；Curator 按 `last_used` 老化；广域导入 + 整包扫描 + 沙箱已落地。**激活路由是提示词里的手写表**（`_SKILL_ROUTES_COMMON`） | `skills/loader.py:295-330`，`agents/preamble.py:47-73`，`skills/curator.py` |
| **Strands 能力利用** | ~5/20 个 Agent 参数；hooks、structured_output、Interrupt/HITL（executor 有 HITL 开关但默认关）、SessionManager 未用 | 记忆 `strands-sdk-gaps.md`；`grep HookProvider` 为空 |

### 目标一句话

**LLM 只做三件事：规划、解释、写作；其余全部由 harness 的确定性代码做**——选任务、记账、查预算、判停止、验结果、写状态。
每一次"agent 说它做完了"都要有一个不经过 agent 的代码路径来核实。

---

## 一、系统提示词：从"教程"到"分层契约"

### 1.1 五层结构（按变化频率排序，前缀稳定 = Bedrock 缓存命中）

```
L0  Constitution（平台宪法，所有 agent 共享，季度级才变）
    - 身份与边界（只读/规划/执行三权分立；resolved 只有 VerifyGate 能写）
    - Trust invariants 的 agent 侧表述（"证据不足就 abstain；不确定就说不确定；不得自证成功"）
    - 通用输出契约（I#/R# 引用、<<SUGGEST>> 行、语言跟随用户）
L1  Role（本 agent 的职责与禁区，月级）
    - 只写"做什么、不做什么、何时停"，不写"怎么调工具"
L2  Capability Index（skills XML + 工具族索引，随 SKILL.md 变）
    - 由代码生成；激活建议来自技能元数据，不再手写路由表
L3  Output Rules（周级；结构化输出用 schema 替代散文格式要求）
L4  Memory（每次构建变；保持最后）
——— 以上是 system prompt ———
Run Context（每次运行变，**放进第一条 user message 而不是 system prompt**）
    - InvestigationRun 的 scope / 预算 / 覆盖要求 / 已有假设与证据摘要 / 拓扑上下文 / 事件记忆
```

现有 `build_system_prompt` 已经是 L1→L2→L3→L4 的骨架，只需：① 抽出 L0 常量并置顶；② 把 RCA 现在拼进 system prompt 的
`_build_topology_context` / `_build_incident_memory` 这类**每次都变**的块移到 Run Context（否则每次 RCA 都打穿缓存前缀）。

### 1.2 "工具用法"从提示词迁到工具描述

Main 的规则 9.5–12（skills / schedules / notifications / share_content / monitoring / web-research / document-analysis）
是工具说明，Strands 会把 `@tool` 的 docstring 作为 tool spec 发给模型——**同一信息不该出现两次**。迁移后 Main 的 L1 只剩
路由原则（意图 → 专家）+ 安全门（execute 前必查 approved），预计从 ~2,570 token 降到 ~900。golden 测试把新预算 pin 住。

### 1.3 契约化的三段新协议（写进 RCA / SRE / Executor 的 L1）

- **Evidence protocol**：每条证据 = `{source, query, target, window, observed_at, role: supports|refutes, hypothesis_id}`；
  "找不到就写 `collection_status=unavailable`，不得省略"。
- **Stop / abstain protocol**：把审计 §8.4 的两张清单原样写进去，并要求结论必须带 `reason_codes[]`（§6.3 词表）。
- **No self-certification**：Executor 的 L1 明确"你的 post-check 只是**观察**，不是**判定**；判定由 VerifyGate 做"。

### 1.4 结构化输出替代散文格式

RCA 结论、`RCAQualityDecision`、`VerificationSpec`、Planner 的假设列表：用 Strands `structured_output_model=`（pydantic）
接收，删掉对应的 OUTPUT_RULES 散文。解析失败 = `RCA_OUTPUT_UNPARSEABLE` reason code → needs_review，不再靠字符串命中。

### 1.5 提示词的测试

- 扩展 `tests/test_prompt_budget.py`：每层 token 预算 pin；**每条 L1 规则都必须对应一个工具或一个 eval 场景**（规则→覆盖矩阵，
  由测试从提示词文本提取编号规则并比对清单，防止"规则只在散文里活着"）。
- 缓存命中率成为可观测指标：`cost_service` 已有 cache_read/cache_write 记账，按 agent 出一条"前缀稳定性"曲线。

---

## 二、循环：从"agent 内自由游走"到"harness 状态机 + agent-in-the-loop"

### 2.1 Investigation Loop（新，替代"一次 RCA agent 调用"）

```
create(run)                       # InvestigationRun: scope, budgets(tool_calls/tokens/time/cost), coverage_required, lease
 └─ scoping   : 实体解析（代码 + 一次小模型调用）；歧义 → needs_input（只问一个最有信息量的问题）
 └─ planning  : LLM 一次结构化调用 → 3–7 个可证伪假设 + 每个假设的"最小区分实验"
 └─ collecting: **代码**按 信息增益/成本/风险 选下一个 Typed Task → 执行（确定性工具或子 agent 的有界调用）
                → 写 EvidenceRecord（带 tool_call_id、window、digest）→ 更新 hypothesis 支持/反驳
                → 每步检查：预算 / lease / 覆盖；越界即停并记 stop_reason
 └─ evaluating: LLM 一次结构化调用 → 各假设置信度；代码套 coverage gate + critic → RCAQualityDecision(accept|abstain|needs_review)
 └─ concluded / insufficient_data / expired
```

- 每个 Typed Task（§8.3 的 10 种）= 一个 `@tool`，有输入/输出 schema、超时、重试、预算扣减、幂等键；**大多数不需要 LLM**。
- Strands 用法：collecting 里若需要"会读日志的眼睛"，调用**有界**子 agent（`max_iterations` 小、只暴露该 task 的工具、
  structured output），而不是让 RCA agent 一个上下文跑 40 轮。
- Hooks：`BeforeToolInvocation` 做预算与 lease 检查（超预算直接拒调用并写 reason code）；`AfterToolInvocation` 自动写证据账本
  骨架（tool_call_id / 参数 / digest），agent 只补 `role` 与 `hypothesis_id`。这是 hooks 第一次进入生产路径。

### 2.2 Remediation Loop（改：VerifyGate 成为唯一写 `resolved` 的路径）

```
approved → executing → executed → verifying ──passed──→ resolved → VerifiedEpisode
                                     │  ├─failed───→ rollback → verifying_rollback
                                     │  ├─timeout──→ needs_review
                                     │  └─uncertain→ needs_review
```

- VerifyGate 读持久化的 `VerificationSpec`，用**确定性 probe adapter**（首批 3 个：CloudWatch alarm+metric 窗口、K8s rollout/ready/
  restart、HTTP/SLO 端点），带基线窗口与稳定窗口，与 Executor **不同代码路径**、不读 Executor 的自然语言结论。
- `update_health_issue_status(... resolved)` 对 agent 工具**下线**；只保留服务层 `verify_gate.mark_resolved(run_id, spec_id, evidence)`。
- Trust invariants（§7.5 七条）写成 `tests/test_trust_invariants.py`，每条一个用例，CI 必过。

### 2.3 Lease 与晚到隔离

`RcaRun(run_id, generation, lease_expires_at)`；所有保存工具带 `run_id`；看门狗超时 → `expired` + generation++；
晚到写入 → `LATE_RESULT_IGNORED`（不触发 SRE / 通知 / 记忆）。这把"线程不可杀"从阻塞条件变成可观测事件。

### 2.4 学习循环（改：只有 verified 才涨权重）

`VerifiedEpisode` 由 VerifyGate 通过时生成；Memory/Skill/KB 的"成功经验"入口从 `resolved` 事件改挂到 `VerifiedEpisode`；
`fix failed / rollback / reopened / human incorrect` 降权。Curator 的老化信号从 `last_used` 扩到 `verified_success_rate`。

### 2.5 已有循环的最小改动

- 巡检（HealthPatrol）、Signal Gate、Scheduler：**不动**，它们已经是确定性代码循环。
- auto-RCA 入口：`_run_auto_rca` 改为创建 InvestigationRun 并驱动 2.1；旧路径保留一个 feature flag 期（见阶段）。

---

## 三、Skills：从"知识文档"到"能力包"

### 3.1 frontmatter 增量（向后兼容，缺省即今天的行为）

```yaml
kind: knowledge | tools | probe | procedure     # 缺省 knowledge
trust: pinned | verified | draft                # pinned=人写；verified=经 replay+人批；draft=agent/imported
applies_to:                                     # 供代码做激活建议与记忆检索，替代提示词里的手写路由表
  resource_types: [EC2, EKS, RDS]
  symptoms: [latency, oom, crashloop]
budgets: {tool_calls: 20, timeout_s: 120}       # kind=tools/probe 时生效
```

### 3.2 三个新技能族（都是确定性代码，LLM 不参与执行）

| 族 | 内容 | 与循环的关系 |
|---|---|---|
| `investigate-*`（Typed Tasks） | FetchMetricWindow / SearchLogs / InspectChange / QueryTrace / InspectKubernetes / TraverseGraph / CompareBaseline / TestHypothesis 各一个 `@tool` | 2.1 collecting 的可选动作集 |
| `verify-*`（Probe adapters） | cloudwatch / kubernetes / http-slo（首批），后续 prometheus / logs / trace / graph-invariant | 2.2 VerifyGate 的唯一执行面 |
| `procedure-*` | 从 VerifiedEpisode 蒸馏出的调查策略（§10.2 Procedure 层），`trust=verified` 才可被 planner 引用 | 2.4 学习循环的产物 |

技能包脚本仍走沙箱（无凭证无网络）——所以 **probe/task 是 `@tool`（经 provider 层拿目标账户凭证），不是沙箱脚本**；沙箱脚本
只做本地计算（解析、统计、成型）。这条边界要写进 `ADDING_SKILLS.md`。

### 3.3 激活从散文变元数据

`_SKILL_ROUTES_COMMON` 删除；`build_system_prompt` 的 L2 由 `applies_to` 生成"本次运行建议激活：…"（放 Run Context），
agent 仍可自主 `activate_skill`。Curator 与 planner 共用同一份 `applies_to` 索引。

### 3.4 晋升与老化挂到结果

`promote_skill` 之上加 `verify_skill(name)`：对 `procedure-*` 要求至少 N 次 VerifiedEpisode 引用；Curator 对 `trust=draft`
且 `verified_success_rate=0` 的技能加速老化。人写技能（pinned）规则不变。

---

## 四、评估 harness（没有它，以上都无法 Review）

- **Eval 集**：`docs/cases/`（10 个闭环用例）+ `infra/eks-chaos-lab` L1/L2 场景 → 转成可重放的 `evals/*.yaml`：输入（告警/问句）、
  期望（accepted_hypothesis 或 abstain、允许的 reason_codes、是否允许自动修复、VerifyGate 期望结论）。
- **三类指标**：正确率（RCA 命中）、**弃权正确率**（该 abstain 时 abstain 了）、**零不安全自动修复**（硬门，任一失败即红）。
- 跑法：`pytest evals/ -m eval`（默认不入全量，成本原因）；每个阶段结束跑一遍并把结果写进对应 release note。
- 提示词/循环任何改动，先看 eval 再看单测——这是 harness 工程与普通工程的区别。

---

## 五、阶段与 Review 点（每阶段可独立合并、可独立回退）

| 阶段 | 内容 | 退出标准 | Review 问题 |
|---|---|---|---|
| **0 基础**（1–2 周） | 提示词分层重构（行为不变）；Run Context 移出 system prompt；hooks 接入（审计日志 + 预算计数，先只记录不拦截）；structured output 用于 RCA 结论；eval 集 v0（10 用例可重放） | golden 预算测试更新并全绿；eval v0 基线数字入库；缓存命中率不降 | L0 宪法文本您是否认可（它将进入所有 agent） |
| **1 Trust Kernel** | fail-closed `RCAQualityDecision`（纯函数 + reason codes）；RcaRun lease；VerifyGate + 3 个 probe；`resolved` 只走 VerifyGate；7 条 trust invariants 测试 | 无任何路径能让 agent 写 resolved；eval "零不安全自动修复"为 0；旧 resolved 路径删除 | 首批 3 个 probe 选哪三个（我建议 CloudWatch / K8s / HTTP-SLO）；验证稳定窗口默认多长 |
| **2 Investigation Runtime** | InvestigationRun / Hypothesis / EvidenceRecord 表；Typed Tasks 8 个工具；planner/evaluator 结构化调用；停止/弃权；Chat 首句实体解析（默认 A1 Investigate，不要求 Issue ID） | eval 正确率 ≥ 基线且弃权正确率上升；单次调查 token 中位数 ≤ 旧 RCA | 假设数上限（3–7）与预算默认值；哪些 Typed Task 先做 |
| **3 Skills 能力包** | frontmatter 增量；`applies_to` 驱动激活；`verify-*` / `investigate-*` 技能族落位；散文路由表删除 | Main 提示词 ≤ 1,000 token；技能激活命中率（激活的技能被后续工具调用使用）可观测 | 人写技能是否需要补 `applies_to`（我建议由我补草稿、您批） |
| **4 Outcome-weighted Memory** | VerifiedEpisode；权重涨跌规则；§10.3 检索排序；Curator 挂结果 | 无 verified 的经验不再进高置信记忆（测试）；记忆注入的 top-N 按新分数 | 检索权重公式是否按审计原样采用 |

不做（本计划范围外）：GNN、`graph/`+`galaxy/` 物理合并、多租户、Swarm/A2A。

---

## 六、我需要您在 Review 时拍板的事

1. **顺序**：阶段 1（Trust Kernel）是否必须先于阶段 2？我的判断是**必须**——先把"agent 不能自证成功"钉死，再让它更聪明地查；
   反过来是给一个能自证成功的系统更多权限。
2. **旧路径共存期**：阶段 1–2 期间 `auto_rca_enabled` 下用 feature flag `investigation_runtime_enabled` 双跑（旧路径只记录不动作）
   还是直接切换？双跑成本约 +1 次 RCA/事件。
3. **Chat 首句默认进 A1 Investigate**（不再要求先有 Issue ID）——这是产品行为变化，需要您点头。
4. **L0 宪法**：我会先起草一版（≤ 300 token），作为阶段 0 的第一个 PR 单独给您审。

## 验证（贯穿）

- 单测：trust invariants 7 条、prompt 分层预算、每个 Typed Task/probe 的 schema 与幂等；全量 `pytest tests/ -q` 保持全绿。
- eval：每阶段跑 `evals/`，三类指标写进 release note；"零不安全自动修复"任一失败阻断合并。
- live：阶段 1 在 EKS chaos lab 重跑 L2 场景，证明 VerifyGate 能在"命令返回 0 但告警 5 分钟后复燃"的场景判 failed。
- 绝不落密与 E2E + 主人确认后才推的规则不变。

---

## 附录 A · L0 Constitution 草案（阶段 0 第一个 PR 的评审对象，≤ 300 token，进入所有 agent 的 system prompt 顶部）

```text
PLATFORM CONSTITUTION (applies to every AgenticOps agent)

1. Three powers, never one hand. Investigation agents read; the SRE agent plans; only the
   Executor changes infrastructure, and only inside an approved plan. No agent marks an issue
   resolved — the VerifyGate does, from probes it runs itself.
2. Evidence or abstain. A conclusion carries the evidence that supports it and the alternatives
   it rules out. When evidence is missing, a source is unavailable, or two explanations remain
   close, say so and stop (abstain / needs_review) instead of choosing the most plausible story.
3. No self-certification. A command exiting 0, a pod Running or a metric dipping is an
   observation, not a verdict. Report what you observed; the verdict belongs to a separate
   verification step.
4. Stay in budget and in scope. Respect the run's tool, token and time budgets and its
   account / region / service scope; when a budget is exhausted, stop with a reason code
   rather than guessing.
5. Credentials are addressed, never assumed. Every cloud call names its account; ambiguity is
   a question back to the user, not a default.
6. Say what you did not do. Unavailable data, skipped checks and permission failures are part
   of the answer.
7. Write for the operator: lead with the finding, cite I#/R# references, keep to the user's
   language, and end with the <<SUGGEST>> line.
```

设计说明：每一条都对应一个可测试的 harness 机制（1→VerifyGate 与工具下线；2→stop/abstain protocol 与 reason codes；
3→VerifyGate 独立代码路径；4→hooks 预算检查与 lease；5→凭证铁律；6→EvidenceRecord.collection_status；7→既有输出契约）。
宪法里**没有**任何工具名——工具用法属于 tool spec，不属于宪法。

## 附录 B · 决策日志

| # | 决策 | 结论 | 日期 |
|---|------|------|------|
| 1 | 阶段 1（Trust Kernel）先于阶段 2 | **是**：先钉死「不能自证成功」，再让它更聪明 | 2026-09-09 |
| 2 | 阶段 1–2 旧路径共存方式 | **feature flag 双跑**：`investigation_runtime_enabled`；新路径动作，旧路径只记录，供 eval 对照 | 2026-09-09 |
| 3 | Chat 首句默认进 A1 Investigate（不要求 Issue ID） | **是**：实体唯一即自动开调查；多候选只问一个问题；A1 只查不动手 | 2026-09-09 |
| 4 | L0 宪法先单独评审 | 已按此执行：见附录 A | 2026-09-09 |
