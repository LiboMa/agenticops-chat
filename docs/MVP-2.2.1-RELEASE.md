# MVP-2.2.1 Release Notes — Effort（thinking）策略

> Version: 2.2.1 · Branch: `MVP-2.2.0` · Date: 2026-07-27 · 依赖 MVP-2.2.0

## 一句话

模型的**思考深度（effort）**从"一个写死的常量"变成**分场景决策**：后端自动管线按 issue 情况自动升档（无人在场时系统自己定），前端 chat 交给用户一键覆盖（人在场时人定）。**这是一次带实验设计的迭代 —— 目的是让"thinking 到底有没有让 RCA 变准"第一次成为可以从库里查出来的数字。**

设计与计划：`docs/superpowers/plans/2026-07-27-mvp-2.2.1-effort-policy.md`

## 修复前的三个事实

| 事实 | 后果 |
|------|------|
| `agent_rca_thinking_budget: 4096` 是静态常量，从未被验证 | critical 生产故障与"EC2 缺标签"拿到**相同**思考预算——同时错两个方向 |
| `agent_main_thinking_budget: 0` | chat 里的 Opus **完全不思考**，用户无任何手段开启 |
| 唯一开关是 YAML + 重启，且 7 个 agent 共用一套语义 | 想给 chat 开思考，就会**同时**改到自动管线；两者被锁死 |

## A — 后端：升级策略（Auto，无人在场）

判据只有两个输入（**故意做窄，保证效果可归因**）：

| 触发 | 加档 |
|------|------|
| `severity == critical` | +1 |
| 重跑（上次 `needs_review` 或 RCA 被 `refuted` / `disputed_by_execution`） | +1 |
| 两者同时 | +2（可叠加） |

- 每档 `thinking_escalation_step`（默认 4096）→ 普通 4096、critical 8192、critical+重跑 12288。
- **base=0 时任何升档都不生效**（关就是关，升级不能凭空打开思考）。
- **归因失败 = 不涨价**：拿不到 issue / DB 异常 → 一律回落 base（fail-safe，绝不因为读不到数据而多花钱）。
- 单一真源 `resolve_rca_effort(issue_id)`：**模型拿到的预算与事件里记录的预算永远一致**。
- `rca_started` 事件 detail 新增 `thinking_budget` + `escalate_reason` —— 没有这条，本次迭代的全部意义消失。

## B — 前端：per-session 覆盖（人在场）

- chat 输入框的 model pill（`ModelSelector`）popover 底部新增 **Thinking effort** 段：Auto / Off / Standard / Deep。
- 非 Auto 时 pill 上显示小徽标（`· deep`）。
- `chat_sessions.effort` nullable 列（**NULL = Auto，行为与 2.2.0 逐字节一致**），沿用 `model_id` 的 `""` sentinel 范式。
- 切换只淘汰**该 session** 的 agent 缓存；流式进行中切换返回 409（沿用 model 的锁）。
- 列表端点一并返回 `effort`（否则刷新后 pill 会回弹）。

## C — 安全边界

Bedrock 要求 `thinking_budget_min <= budget < max_tokens`。**上下界都在解析时挡住**，非法值一律降级为"关闭思考"+ WARNING，**绝不把非法请求送进 Bedrock**。`max_tokens` 太小以至于放不下任何合法预算时同样返回 0。

> 踩坑记录：`thinking_effort_presets` 的 `off` 键在 YAML 里**必须加引号** —— YAML 1.1 把裸 `off`/`on` 解析成布尔值，会直接让 pydantic 校验失败、进程起不来。

## 新增配置（settings.yaml）

```yaml
thinking_escalation_step: 4096   # 每档加多少 token
thinking_budget_min: 1024        # Bedrock 下限，低于此值视为关闭
thinking_effort_presets:
  "off": 0                       # 引号必需（YAML 裸 off = false）
  "standard": 4096
  "deep": 12288
```

## 明确不做（避免污染可度量性）

- ❌ blast radius / 图谱影响面作为升级因子 —— 口径模糊，加进去就无法归因是哪个因子起作用。
- ❌ Settings 页的全局 effort 开关 —— 既不知道任务难度也不知道当前预算的钝器，用户设一次就再不改，只会退化成"永远 Deep"（贵）或"永远 Off"（差）。
- ❌ executor 的 effort（恒为 0）—— 执行要确定性，不要它"再想想"。
- ❌ SSE 推送 reasoning 内容到前端（独立需求，记入 Future）。

## 验收

| # | 标准 | 状态 |
|---|------|------|
| 1 | 普通/critical/critical+重跑 → 4096 / 8192 / 12288 | ✅ `TestRcaEscalation` |
| 2 | base=0 时升档不生效 | ✅ `test_off_stays_off_under_escalation` |
| 3 | 非法 budget（<1024 或 ≥max_tokens）绝不进 Bedrock | ✅ `TestThinkingFields` + clamp 测试 |
| 4 | 归因失败一律回落 base | ✅ `test_none_issue_is_fail_safe` |
| 5 | effort=NULL 的 session 行为与 2.2.0 逐字节一致 | ✅ `test_no_override_matches_2_2_0_behaviour` |
| 6 | 老库 `init_db()` 自动补列且幂等 | ✅ `test_ensure_column_is_idempotent` |
| 7 | `thinking_request_fields` 保持 2.2.0 契约（7 处调用点不改） | ✅ `test_legacy_wrapper_unchanged` |
| 8 | 真实环境 E2E + 主人确认后才 push | 待执行 |

**测试**：新增 `tests/test_effort_policy.py`（26 用例，全绿）；`npx tsc --noEmit` + `npm run build` 通过。

## 实验设计（本次的真正目的）

上线跑一周后按 `thinking_budget` 分组，对比 `confidence` / `evidence_verified` 通过率 / `critic_verdict=refuted` 数量（SQL 见 plan §5）。

**若高 budget 组无显著提升 → 把 base 降回 0，并把这个结论写进文档。负结果也是结果，比留着一个未验证的常量好。** 若显著提升 → 考虑抬高 base。

## Future

1. SSE 推送 reasoning 流到前端（展示思考过程）。
2. CLI `/effort` 斜杠命令（与 `/model` 同构）。
3. detect/sre 的 effort 策略（**等 RCA 实验结论出来再决定，不盲目铺开**）。
4. 按 `issue_type` 的 effort 策略。
5. token 预算感知的动态降档。
