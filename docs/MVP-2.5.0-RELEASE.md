# MVP-2.5.0 Release Notes — 云安全审查（Cloud Security Review）

> Version: 2.5.0 · Branch: `MVP-2.5.0` · Date: 2026-08-29（P1 Stages 0–7 交付：2026-08-31） · 主题：安全态势体检 + 精确可达性关联
>
> **状态：P1（Stages 0–7）已实现、通过真实账户只读 E2E、并于 2026-08-31 经主人确认 push 到 `origin/MVP-2.5.0`** —— 证据见 `docs/MVP-2.5.0-E2E-REPORT.md`。P1.5 / P2 / P3 见下方路线图。
>
> **本文件是云安全审查方向的顶层基线 —— 之后所有新建的安全相关研发（P1 → P3 及后续）都必须挂靠本文件的「四条精确度原则」与「路线图」。**
>
> P1 详细实施设计：`docs/superpowers/specs/2026-08-29-cloud-security-review-p1-design.md`

## 一句话

把散落在云厂商各服务里的安全信号，收敛成一份**准实时、可复现、消除误报**的安全态势 —— 评分看得到趋势、发现溯得到证据、暴露链算的是"互联网到底能不能打进来"，而不是"配置看起来危不危险"。

## 定位（为什么做、做给谁）

选定两个价值面（用户明确取舍 A + C），砍掉纯守护/自动修（那是既有自动管线的职责，不在本方向）：

| 面 | 交付 | 相对云原生工具（Security Hub 等）的增量 |
|----|------|------------------------------------------|
| **A 定期体检** | 全账户安全评分 + 趋势曲线 + 定期 `security-review` 报告 | 原生只给"当前 findings 列表"，不给可复现的**评分趋势**与**跨账户体检交付物** |
| **C 深度洞察** | 攻击路径/暴露链、证据接地的优化建议 | 各服务是孤岛：原生不会告诉你"这个 critical CVE 在一台**互联网真实可达**、且挂了高权限 Role 的实例上" —— **跨源关联链是我们的立身之本** |

**目标函数（唯一）：拿到最准确的数据、给出最精确的结果。** 成本、覆盖广度都让位于此。

## 研发宪法：四条精确度原则（★ 不可协商）

本方向所有研发必须同时满足这四条。任何一条被违反的实现，无论多"智能"，都视为降低而非提升准确度：

1. **采集只采信官方判定，绝不用 LLM 重判客观事实。** GuardDuty / Security Hub / Inspector / Config 的 findings 是云厂商确定性判定的结果，原样采集、原样呈现。让 LLM 去重新判断"这个 CVE 算不算 critical"只会引入幻觉。**采集层 100% 确定性代码，零 LLM。**
2. **精确度来自跨源关联，不来自单点告警。** 单看一条配置（如 SG 开放 22）无法判断真实风险；必须多源关联到真实暴露状态才算数（见原则 3）。降误报的杠杆在关联，不在采集更多。
3. **可达性 / 攻击路径用确定性图算法，LLM 只叙事、不定论。** 这是 galaxy 已验证的教训（llm 边 advisory-only、fail-closed 验证）。可达性推演必须确定性、且**保守偏报**：数据不全时标"未确定"而非"安全"—— 精确度取向下宁可多标可疑供人工复核，绝不漏报真威胁。
4. **评分对标客观基线，建议必须证据接地。** 评分用 CIS 等基线的客观 pass/fail，不自创权重（分数可复现可审计）。LLM 生成的优化建议套用既有 `services/rca_quality.py` 的门：每条建议必须 grounded 在具体 `resource_id` + 检查证据，再过 critic，refuted 即丢弃。**LLM 唯一的合法位置，是"云原生给不了的跨源叙事与收缩建议"，且必须可验证。**

## 架构（全部挂在现有基础设施上，不新造机制）

```
                              ┌─ 快频增量采集(默认10min) ─┐
scheduler cron loop ──────────┤  官方 findings + 高危变更   ├─→ 关联引擎 ─→ signal_gate ─→ HealthIssue ─→ Dashboard 高亮
(复刻 GalaxyBuild system job)  └─ 慢频态势采样(默认60min) ─┘  (可达性三态)   (去重/去噪)      (auto_rca=False)
                                          态势快照 + CIS 客观评分 ─→ SecuritySnapshot ─→ /api/security ─→ Security 页(趋势/暴露链)
                                                    │
                                     证据接地 LLM 建议 + critic ─→ SecurityRecommendation
```

复用既有子系统，避免重造：

| 需求 | 复用 | 说明 |
|------|------|------|
| 周期任务 | `scheduler.py` 的 GalaxyBuild "纯 Python system job"模式 | 三处编辑（config field + dispatch 分支 + startup seed），不走 agent |
| 发现入库/去重/去噪 | `services/signal_gate.process_signal(SignalInput)` | 发现→Signal→HealthIssue，指纹自动折叠重复；不新造发现表 |
| 可达性关联 | `graph/` 引擎（typed directed nx graph + `can_reach_internet`） | 底座正确，需**有意义的扩展**（见 P1 边界） |
| 建议质量门 | `services/rca_quality.py`（evidence check + critic）模式 | 建议接地/critic 直接套用同一范式 |
| 多账户凭证 | provider 层 `resolve_credentials` | 采集全程走目标账户凭证，fail-closed |
| 前端页/图/报告 | `pages/AgentMetrics.tsx`(recharts)、`routers/cost.py`、`report/generator.py` | 均有现成范例镜像 |

## 路线图

| 期 | 目标 | 边界（明确到不含糊） |
|----|------|----------------------|
| **P1（当前）** | 双频采集 + **含 NACL 的精确可达性关联** + CIS 评分 + 证据接地建议 + Dashboard 高亮 + Security 页 + `security-review` 报告 | 可达性做到 **SG 规则 + 公网IP + 子网/IGW 路由 + NACL 有序规则 + 运行态** 的有向 internet→instance:port 评估。攻击路径 = 关联引擎输出的**网络层暴露链** Top-N |
| **P1.5** | ENI 关联 + ELB 前门 | `describe_network_interfaces` 覆盖 ELB/RDS 等非 EC2 的 SG 绑定；`describe_load_balancers` scheme 覆盖 ALB/NLB 前置暴露 |
| **P2** | 攻击路径的**权限维度**富化 | 暴露链 + 实例 IAM 权限等级（暴露 × 权限 = 真实爆炸半径排序）；合规框架映射（CIS 起步，等保 2.0 视中国区账户需要排入） |
| **P3** | IAM 最小权限顾问 | Access Analyzer + service-last-accessed → policy diff 收缩建议 |

## P1 = 当前目标

范围锁定见路线图 P1 行。**关键定档：P1 的可达性精度包含 NACL**（`describe_network_acls` + 有序 allow/deny + 临时端口求值）—— 因为 NACL 是消除"SG 开放但被 NACL 拦截"这类误报的关键一环，缺了它"精确"就打折。ENI 与 ELB 前门顺延 P1.5。

详细组件设计、数据模型字段、文件锚点、测试计划见：
`docs/superpowers/specs/2026-08-29-cloud-security-review-p1-design.md`

## 新增数据模型（概览，细节见 spec）

| 表 | 用途 |
|----|------|
| `SecuritySnapshot` | 态势快照时间序列：总分 + 各类别分 + 关键指标 + Top-N 暴露链 JSON（评分趋势数据点） |
| `SecurityRecommendation` | LLM 优化建议 + 引用证据(`resource_id`列表) + critic 结论 + 状态 |
| — 发现不新造表 | 事件类与态势类的可执行发现统一走 `signal_gate → HealthIssue(auto_rca=False)`，复用既有 issue 列表 / 去重 / Dashboard |

## 新增配置（概览，放 `config/settings.yaml`，`config.py` 只定义 schema）

```yaml
security_review_enabled: true            # 方向总开关
security_poll_interval_minutes: 10       # 快频增量采集
security_posture_interval_minutes: 60    # 慢频态势采样
security_reachability_nacl_enabled: true # P1 含 NACL 求值
security_advisor_enabled: true           # LLM 优化建议（唯一 LLM 环节）
security_advisor_critic_enabled: true    # 建议 critic 门
security_snapshot_retention_days: 90     # 快照保留
# security_model_id: ""                  # 建议用模型（空=cheap tier）
```

## 明确不做（守住"最精确"，避免污染）

- ❌ **不引入任何云厂商托管服务/事件总线**（EventBridge 等）来实现准实时 —— 平台内建轮询引擎即可，用户零部署。
- ❌ **不让 LLM 重判官方 findings 的客观属性**（严重度/CVE 等级）—— 违反原则 1。
- ❌ **不让 LLM 边/推断驱动可达性结论或执行** —— 违反原则 3，重蹈 galaxy 之前的坑。
- ❌ **P1 不做自动修复安全项** —— 高危自动执行需另立安全门，不在体检+洞察范围（既有自动管线另议）。
- ❌ **不依赖 lossy 的 boto3 inventory 做关联** —— EC2 metadata 丢了 SG IDs；关联走 live `analyze_vpc_topology + collect_vpc_compute` 路径。

## 验收纲要（P1，细则见 spec）

| # | 标准 |
|---|------|
| 1 | 可达性对抗测试：SG 开放但(无公网IP / 私有子网 / 路由 blackhole / NACL 拦截)→ 判**不可达**，不误报 critical |
| 2 | 采集 fail-soft：单源失败不影响其他源，cursor 不回退丢数据 |
| 3 | CIS 评分可复现：同一快照两次算分结果一致 |
| 4 | 建议证据接地：证据不 grounded 或 critic refuted → 丢弃，不入库 |
| 5 | 发现经 signal_gate 去重：同一暴露跨多轮轮询折叠为一个 open issue |
| 6 | 全程走目标账户凭证，多账户不串号 |
| 7 | 真实环境 E2E + 主人确认后才 push |

## P1 交付状态（Stages 0–7 ✅）

| Stage | 交付 | 状态 |
|-------|------|------|
| 0 | 数据模型（`SecuritySnapshot`/`SecurityRecommendation`/`SecurityPollCursor`）+ 双频 scheduler system job（config field + dispatch 分支 + startup seed） | ✅ |
| 1 | 确定性采集层 `collectors.py`（IAM/S3/logging/VPC-EC2/EBS，账户寻址走 provider 层，零 LLM） | ✅ |
| 2 | 可复现 CIS 评分 `scoring.py`（纯函数，无 random/time/LLM）+ ingress 可达性算法（SG + 公网IP + 子网/IGW 路由 + 运行态） | ✅ |
| 3 | **含 NACL 的三态可达性**（`NETWORK_ACL` 节点 + 有序 allow/deny 求值；缺数据→`undetermined`）+ 账户级 `annotate` | ✅ |
| 4 | 快频增量 poll（guardduty/securityhub/cloudtrail，cursor + fail-soft）+ 慢频 exposure_paths 接线 + 可执行发现 → `signal_gate` | ✅ |
| 5 | 证据接地建议器 `advisor.py`（parse → ground-to-inventory → critic → fail-closed，唯一 LLM 环节） | ✅ |
| 6 | `services/security_service.py` + `/api/security/*`（5 端点）+ `security-review` 报告 + 前端 `/app/security` + Dashboard 高亮卡 | ✅ |
| 7 | 全量回归（3859 passed）+ 真实账户只读 E2E（2 账户，含中国区）+ 文档 | ✅ |

**验收纲要对照（全部通过，证据见 E2E 报告）：**

| # | 标准 | E2E 验证 |
|---|------|----------|
| 1 | 可达性保守偏报，不误报 | 真实数据三态齐现：Global 9 reachable / 22 undetermined / 2 not_reachable；缺路由/NACL 数据 → `undetermined`，未降级为 `not_reachable` |
| 2 | 采集 fail-soft，cursor 不回退 | 中国区 IAM/S3/CloudTrail 令牌失效 → 跳过 + WARNING，快照照常产出；cursor 仅成功时前移 |
| 3 | CIS 评分可复现 | `scoring.py` 经确认为纯函数（无 random/time/LLM）；由 `test_security_scoring` 锁定 |
| 4 | 建议证据接地 | 8 条建议全部 critic-`supported` 入库；未 grounded / refuted / 异常 → 丢弃（0 行） |
| 5 | signal_gate 去重 | 真实运行 1110 条安全信号 → 865 merged（78% 去重），仅 245 条 promoted |
| 6 | 多账户不串号 | 采集全程经 provider 层目标账户凭证，无 ambient 回退 |
| 7 | E2E + 主人确认后才 push | 只读 E2E 完成 + 证据报告归档 + 主人确认（2026-08-31）→ `MVP-2.5.0` 已 push |

## Future

1. 等保 2.0 / PCI-DSS 等多框架合规映射（中国区账户驱动）。
2. 攻击路径可视化叠加到 galaxy 星图（暴露链高亮成路径）。
3. 安全项自动修复剧本（接既有审批管线，需专属安全门设计）。
4. 变更安全审查（CloudTrail 高危变更 diff + 责任人）。
