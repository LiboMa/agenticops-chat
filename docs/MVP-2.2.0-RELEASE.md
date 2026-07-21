# MVP-2.2.0 Release Notes

> Version: 2.2.0 · Branch: `MVP-2.2.0` · Started: 2026-07-10 · Completed: 2026-07-21

## 🚀 重磅升级（Major Upgrade）

这是一次**信任层重构**级别的版本：解决"同一问题反复出现在 Issue 列表"和"RCA 结论无校验直驱自动修复"两个核心质量问题。所有事件（webhook 告警 / Agent 检测 / REST 创建）从此经过统一的 **Signal Gate 信号门**做去重/降噪判定，且每次判定可审计、可捞回；RCA 侧新增**五件套质量机制**——低置信度或被反驳的根因分析不再触发自动修复链。

| 子项 | 一句话 | 日期 |
|------|--------|------|
| **A** Signal Gate 信号门 | 三条创建路径统一判定：晋升/归并/噪音，全程留痕 + 一键捞回 | 2026-07-21 |
| **B** RCA 质量五件套 | thinking + 证据门禁 + Critic 对抗复核 + 置信度门控 + 事件记忆 | 2026-07-21 |
| **C** Agent 架构卫生 | 路由歧义裁决、prompt 残留清理、fable-5 成本修复、双重 fix-plan 作者消除 | 2026-07-21 |
| **D** Signals 视图 + RCA 反馈 UI | Issues 页第三个 Tab；RCA 卡片证据/Critic 徽标 + 👍/👎 | 2026-07-21 |

设计文档：`docs/superpowers/specs/2026-07-10-mvp-2.2.0-signal-gate-rca-quality-design.md`
实施计划：`docs/superpowers/plans/2026-07-16-mvp-2.2.0-signal-gate-rca-quality.md`
业界参照：arXiv 2604.03933（ES Guardian Agent）— 分层判定（规则层 $0 处理大头、LLM 只进灰区）与 Incident Memory 模式经其生产数据交叉验证。

---

## Sub-project A — Signal Gate（统一信号门）

### 问题（修复前）

- 三条 HealthIssue 创建路径各有一套互不相通的去重：agent 路径的 fingerprint 依赖 LLM 生成的标题文本（措辞一变即失效）；**webhook 路径不写 fingerprint 且无 resolved cooldown**（抖动告警每次 flap 都新建 Issue + 触发一次完整 Opus RCA）；**REST 路径零去重**。
- Prometheus 分组 payload 只取 `alerts[0]`，其余告警丢失；CloudWatch webhook 与轮询 provider 对同一 alarm 使用不同身份。
- 同资源合并不分类型（CPU 告警可被并进安全 Issue）。

### 方案（`services/signal_gate.py`，唯一判定入口）

**L1 确定性规则**（$0、同步、短路）：① 排除模式 → 噪音；② resolution 信号归并/喂 flap 窗口（永不建 Issue）；③ **fingerprint v2 精确命中** → 归并（occurrence+1、严重度上抬）；④ resolved cooldown（webhook 路径首次获得）；⑤ **flapping**（同指纹 30min 内 ≥3 条 → 噪音留痕）；⑥ 同资源**且同类型**合并。

**fingerprint v2** = sha256(account | provider | resource | **issue_type** | 上游 dedup key)——**标题不再参与身份**（仅无资源无上游键时兜底）。新增 16 类 `issue_type` 分类（detect prompt 要求必传；webhook 侧确定性映射）。

**L2 灰区 LLM 判定**（仅疑似近邻存在时一次 Haiku 调用）：只能输出 **merge 或 new**——**永远不能判噪音**；置信度 <0.7 或任何异常 → 晋升（fail-open）。判定原文写入 `gate_evidence` 可审计。

**Signal 台账**：`alert_events` 表泛化为信号台账（每个事件一行：kind/fingerprint/issue_type/disposition/reason/gate_evidence），保留 `signal_retention_days`（默认 30 天）。

### API / 行为

- `GET /api/signals`（disposition/kind/issue_type 过滤 + 游标分页）；`POST /api/signals/{id}/promote` 人工捞回成 Issue（`manual_override`）。
- `POST /api/health-issues` 经 gate（REST 零去重漏洞关闭；噪音返回 409 + 捞回指引）。
- Prometheus/Grafana 多告警 payload 逐条成 Signal（`parse_alerts`）；CloudWatch 身份统一为 AlarmArn，OK 通知成为 resolution 信号。
- 只有 promoted 触发通知/auto-RCA；merged/noise 静默（消灭重复通知与重复 RCA 成本）。
- `signal_gate_enabled=false` 回退旧行为（回滚阀）。

## Sub-project B — RCA 质量五件套

| # | 机制 | 实现 |
|---|------|------|
| 1 | **Extended thinking** | `agent_rca_thinking_budget: 4096`（settings.yaml，per-agent 通用配置）→ BedrockModel `additional_request_fields` |
| 2 | **证据门禁**（fail-closed） | `save_rca_result` 新增 `evidence` 参数；运行结束后纯代码核对每条 `evidence.ref` 是否真实出现在本次工具调用痕迹中；未命中 → `evidence_verified=false` + 置信度 ×0.6 |
| 3 | **Critic 对抗复核** | 一次 cheap-tier 调用试图反驳根因（supported/weak/refuted）；refuted → 置信度 ×0.5 |
| 4 | **置信度门控** | 最终 confidence < 0.6 或被反驳 → **不触发 auto-SRE**，Issue 标 `needs_review` + 事件 + 通知（0.2 置信度直驱自动修复的时代结束） |
| 5 | **事件记忆注入**（arXiv 2604.03933 模式） | 同指纹/同类型历史 Issue 的（根因、human/critic 判定、修复结果）确定性注入 RCA prompt——"此结论曾被执行失败驳斥"可见；历史是先验不是答案 |

**管线重排**：`save_rca_result` 变纯持久化（副作用移出）；后置管线（`services/rca_quality.py`）收拢在 rca_agent 运行结束处，所有入口（chat/auto/REST/CLI）天然全覆盖。

**反馈回路**：`POST /api/health-issues/{id}/rca-feedback`（👍/👎）——incorrect 自动写 rca agent-memory 纠错记忆；**修复执行失败自动把对应 RCAResult 标 `disputed_by_execution`**（`mark_fix_failed`）。

**可靠性**：`rca_timeout_seconds=900` 看门狗（超时记 failed 事件 + needs_review，不再无声卡 investigating）；`rca_max_iterations=40` 轮数护栏；`rca_started` 事件记录真实 RCA 模型（原来记错成默认层模型）；状态机补 `root_cause_identified→investigating` 回边（重跑 RCA 合法化）。

## Sub-project C — Agent 架构卫生

- **main 路由**：编号错乱修复（两个 9.7 → 9.5-9.10 顺序化）、"ADDITIONAL TASKS" 劣化段合并入正则；**GuardDuty 歧义裁决**：安全审计（产出 Issue）→ detect scope=security，只读 findings 查询 → sre_query。
- **detect**：prompt 残留伪注释行删除；docstring 与路由裁决对齐；新增 issue_type 分类表指令。
- **RCA 不再产 fix_plan**（prompt 级）：修复规划全权归 SRE，消灭双重修复作者；重复 "b." 编号修复。
- **reporter** 删除无工具支撑的 "Service Security Focus" 段（防编造）。
- **成本修复**：`claude-fable-5` 加入 token_cost_table（SRE 运行成本不再是 $0）+ MODEL_WINDOW_DEFAULTS 家族条目（fable-5/opus-4-8 校验警告消除）；CLAUDE.md 模型表与 settings.yaml 对齐。
- **归因修复**：`track_agent(parent_agent=...)` 不再硬编码 "main"——按线程名推断 pipeline/patrol/main（`infer_parent_agent`）。
- **KB 飞轮修复**：案例蒸馏改读真实（approved/executed）SRE FixPlan，不再存 RCA 从未执行的草稿方案。

## Sub-project D — 前端

- **Signals 视图**：Issues 页第三个 Toggle（晋升/归并/噪音过滤、判定理由列、merged/noise 一键捞回、15s 轮询）。
- **×N 徽标**：IssueRow 琥珀色 occurrence 徽标（gate 归并次数可见）。
- **RCA 质量面板**：IssueDetail RCA 卡片显示 `evidence ✓/✗`、`critic: supported/weak/refuted` 徽标（hover 见 Critic 理由）+ 👍/👎 人工判定按钮。

## 新增配置（settings.yaml）

```yaml
signal_gate_enabled: true          # 总开关（false = 旧行为）
signal_gate_llm_enabled: true      # L2 灰区判定
signal_gate_llm_model: ''          # 空 = cheap tier
signal_gate_confidence_min: 0.7
signal_gate_candidate_cap: 5
noise_flap_threshold: 3
noise_flap_window_minutes: 30
signal_retention_days: 30
rca_min_confidence_for_autofix: 0.6
rca_critic_enabled: true
rca_critic_model_id: ''
rca_timeout_seconds: 900
rca_incident_memory_enabled: true
rca_incident_memory_max: 3
rca_max_iterations: 40
agent_rca_thinking_budget: 4096
```

## 验收（spec §5.4，pytest 固化）

| # | 标准 | 测试 |
|---|------|------|
| 1 | 同一 webhook 重放 10 次 → 1 Issue / 10 Signal / 1 RCA | `test_signal_gate_paths.py::test_replay_10x_one_issue_one_rca` ✅ |
| 2 | 抖动告警达阈值 → noise 留痕 + 可捞回 | `test_flap_becomes_noise` + `test_signals_api_list_and_promote` ✅ |
| 3 | 跨路径同问题（措辞不同）→ 单一 Issue | `test_cross_path_same_problem_single_issue` ✅ |
| 4 | REST 重复 POST → 归并 | `test_rest_duplicate_merges` ✅ |
| 5 | confidence<0.6 / critic 反驳 → 无 auto-SRE + needs_review | `test_rca_quality.py::TestConfidenceGateAndCritic` ✅ |
| 6 | 虚构证据 → evidence_verified=false + ×0.6 | `test_fabricated_evidence_penalized` ✅ |
| 7 | 修复失败 → disputed_by_execution | `test_mark_fix_failed_disputes_rca` ✅ |
| 7b | 同指纹二次 RCA → INCIDENT MEMORY 可见 | `TestIncidentMemory` ✅ |
| 8 | fable-5 成本 > $0 | cost normalize 验证 ✅ |
| 9 | gate off → 旧行为 | `TestGateDisabled` ✅ |
| 10 | E2E + 主人确认后才 push | 待执行 |

**测试**：新增 3 个测试文件（test_signal_gate / test_signal_gate_paths / test_rca_quality，43 个用例）；全量套件 3600+ 通过。

## 已知边界（Future 见 spec §6）

- 单进程锁串行化 gate 判定（多 worker 需 DB 唯一约束，spec §6.3）。
- webhook resolution 信号只归并/喂 flap，不自动 resolve Issue（§6.5）。
- 修复失败只标记不自动重跑 RCA（防无限环，§6.6）。
- fable-5 费率为 Opus-4.8 档占位，官方价发布后修正。
