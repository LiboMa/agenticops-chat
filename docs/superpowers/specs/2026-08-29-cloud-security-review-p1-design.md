# P1 设计 — 云安全审查：双频引擎 + 精确可达性关联

> Date: 2026-08-29 · 版本: MVP-2.5.0 P1 · 上位基线: `docs/MVP-2.5.0-RELEASE.md`
>
> 本文是 P1 的可实施设计（writing-plans 的输入）。四条精确度原则见基线文档，本文不复述、只落地。

## 1. 目标与非目标

**目标**：交付一个准实时、可复现、消除误报的安全态势，含 5 件事：
1. 双频采集（快频官方 findings 增量 + 慢频态势快照），全确定性。
2. **含 NACL 的精确可达性关联** —— 对危险配置判定"互联网是否真能打进来"的三态结果。
3. CIS 客观基线评分（分类分 + 总分，时间序列）。
4. 证据接地的 LLM 优化建议（套用 rca_quality 门）。
5. Dashboard 安全高亮卡 + Security 页 + `security-review` 报告类型。

**非目标（P1 明确不做）**：ENI/ELB 前门关联（P1.5）、攻击路径权限维度（P2）、IAM 最小权限顾问（P3）、安全项自动修复。

## 2. 架构与数据流

```
慢频 SecurityPostureSnapshot job (60min)
  └─ security/collectors.collect_posture(account)         [确定性] IAM报告/SG开放面/S3公开/加密/CloudTrail
       └─ security/reachability.annotate(findings)        [确定性] 调 graph 扩展，标可达性三态
            └─ security/scoring.score(posture)             [确定性] CIS pass/fail → 分类分+总分
                 └─ 落 SecuritySnapshot
                      ├─ 可执行发现 → signal_gate.process_signal(auto_rca=False) → HealthIssue
                      └─ security/advisor.recommend(low_categories)  [LLM+critic] → SecurityRecommendation

快频 SecurityIncrementalPoll job (10min)
  └─ security/incremental_poll.poll(account)              [确定性] 按 cursor 增量拉 GuardDuty/SecurityHub/Config/CloudTrail高危变更
       └─ reachability.annotate(finding)                  [确定性] 富化可达性
            └─ signal_gate.process_signal(auto_rca=按类型) → HealthIssue → Dashboard 高亮
```

## 3. 组件详细设计

新模块目录 `src/agenticops/security/`（纯 Python，仅 advisor 触碰 LLM）。graph 扩展落在既有 `graph/`。

### 3.1 调度接入（复刻 GalaxyBuild system job）

三处编辑，每个 job 一份，与 galaxy-auto-build 逐处对应：

| 编辑点 | 文件锚点 | 内容 |
|--------|----------|------|
| config schema | `config.py:474` 附近（galaxy 块旁） | `security_poll_interval_minutes=10`、`security_posture_interval_minutes=60` 等（见 §5） |
| dispatch 分支 | `scheduler.py:367`（GalaxyBuild 分支后） | `if pipeline_name == "SecurityPostureSnapshot":` / `"SecurityIncrementalPoll":` → 调纯 Python 函数 + 写 `ScheduleExecution`（复制 `scheduler.py:350-367`，换函数） |
| startup seed | `web/app.py:149-172`（galaxy seed 旁） | 若 `security_review_enabled` 且 schedule 不存在 → 用 `<60→*/N`、`>=60→0 */(N//60)` 转 cron，`add_schedule(name=..., pipeline_name="SecurityPostureSnapshot"/"SecurityIncrementalPoll")` |
| （可选 UI） | `web/app.py:3535` | 把两个名字加入 Schedules 页下拉 |

`add_schedule`(`scheduler.py:632`) 不校验 pipeline_name 白名单，早返回分支不经 `pipeline_factories`，与 GalaxyBuild/AgentChain 同构。

### 3.2 慢频态势采样器 `security/posture_snapshot.py` + `collectors.py`

入口 `run_posture_snapshot() -> int`（返回 snapshot_id，被 scheduler 分支调用）。逐账户（`resolve` 启用账户）：
- `collectors.collect_posture(account)` 确定性采集（全部走 provider 层目标账户凭证 + read-only）：
  - IAM 凭证报告（`generate/get-credential-report`）：无 MFA、stale key(>90d)、root access key
  - SG 开放面（`describe-security-groups` 全量 `IpPermissions`）：0.0.0.0/0 on 敏感端口
  - S3 公开访问（`get-public-access-block` / `get-bucket-policy` / `get-bucket-acl` / account-level）
  - 加密覆盖（未加密 EBS / RDS / S3 默认加密缺失）
  - CloudTrail 完整性（多区域 trail / IsLogging / LogFileValidation）
- 每类返回结构化 `PostureFinding`（dataclass：category, resource_id, resource_type, raw_check, severity_hint）。

**数据源纪律**：SG/subnet/instance 拓扑走 live `network_tools.analyze_vpc_topology` + `collectors.collect_vpc_compute`（graph 引擎已用的路径），**不读 lossy 的 boto3 inventory**（其 EC2 metadata 丢了 security_group_ids）。

### 3.3 关联引擎（graph 扩展 —— P1 精确度核心）

现状：`algorithms.can_reach_internet`(`algorithms.py:175`) 是 **undirected、topology-only、subnet↔IGW**，回答"子网能否到 IGW"，不回答"互联网能否到实例:端口"。四处扩展：

| # | 扩展 | 文件锚点 | 是否新采集 |
|---|------|----------|-----------|
| 1 | SG `IpPermissions` 挂到图节点（当前只挂了依赖 map） | `network_tools.py:1026-1031`（topology step 9）加 `_format_sg_rules`；`engine.py:234` SG 节点 raw 带规则 | 否，数据已在 `describe-security-groups` |
| 2 | subnet `MapPublicIpOnLaunch` 进拓扑 dict | `network_tools.py:963-972` | 否 |
| 3 | **NACL 采集 + 建模** | 新 `describe_network_acls`；`types.py:11` 加 `NETWORK_ACL` NodeType；subnet↔NACL 关联边；`engine.py` NACL 节点携带有序 entries | **是**（P1 唯一新采集） |
| 4 | 新算法 `internet_ingress_reachability()` | 新增于 `algorithms.py`（与 `can_reach_internet` 并列） | 否 |

**新算法逻辑**（确定性、有向、保守）：引入 `INTERNET` 伪源节点，对每个候选实例判定 ingress 可达当且仅当：
```
(实例有公网IP) ∧ (所在子网有 IGW 默认路由且非 blackhole)
  ∧ (某 SG 入站规则允许 源0.0.0.0/0 命中端口)
  ∧ (子网 NACL 允许 入站该端口 且 出站临时端口范围)
  ∧ (实例 running)
```
输出每个候选的**可达性三态**：`reachable` / `not_reachable` / `undetermined`（任一输入数据缺失 → `undetermined`，绝不降为 `not_reachable`；见原则 3 保守偏报），并回传命中的暴露链路径（internet→subnet→instance:port）供攻击路径展示。

`security/reachability.annotate(findings)` 是安全侧薄封装：构图一次（缓存），对每个网络类 finding 调新算法，把三态 + 路径写回 finding。图算法本身不含安全语义，只做可达性判定。

### 3.4 CIS 评分器 `security/scoring.py`

`score(posture, reachability) -> ScoreResult`。确定性、可复现（无随机、无时间依赖、无 LLM）：
- 每个 CIS 控制映射到一个 pass/fail 判定函数（P1 覆盖 security-engineer skill 已列控制：Root MFA 1.4、Console MFA 1.10、stale key 1.3、CloudTrail 2.1、SG 开放 4.1-4.3、加密、S3 公开）。
- 分类分 = 该类通过控制数 / 总控制数 × 100；总分 = 分类分加权（权重是**控制数占比**，非拍脑袋常数 —— 保证客观可复现）。
- **可达性影响定级不影响评分客观性**：评分只看 CIS pass/fail；可达性用于**排序展示与建议优先级**（可达的 fail 排前），不篡改分数。

### 3.5 证据接地建议器 `security/advisor.py`（唯一 LLM 环节）

复用 `services/rca_quality.py` 的门范式与 `signal_gate._call_bedrock`：
- 输入：低分类别 + 其 grounded 证据（resource_id + 具体检查结果）。
- LLM（默认 cheap tier，`security_model_id` 可调）生成建议，**强制引用输入证据里的 resource_id**。
- 证据接地检查：建议引用的 resource_id 必须存在于本轮采集结果（`_ref_in_trace` 同款子串/token 校验）；不 grounded → 丢弃。
- critic（`security_advisor_critic_enabled`）：cheap 模型对抗审，`refuted` → 丢弃。
- 存活建议落 `SecurityRecommendation`。全程 fail-closed：任何异常 → 不产出建议（不猜）。

### 3.6 Signal Gate 接入

发现统一经 `signal_gate.process_signal(SignalInput(...))`(`signal_gate.py:429`)，不新造发现表：
```python
SignalInput(source="security_poll"|"security_posture", title=..., description=...,
  severity=..., resource_id=<arn>, issue_type="security", upstream_key=<finding_id>,
  kind="detection", detected_by="security_poll", auto_rca=<快频事件类True/态势结构类False>)
```
指纹 `account|provider|resource_id|issue_type|upstream_key|title` 自动折叠跨轮重复。可达性三态写入 `metric_data`，随 HealthIssue 展示。

### 3.7 Web

| 件 | 落点（镜像） |
|----|--------------|
| API | 新 `web/routers/security.py`（镜像 `routers/cost.py`，`prefix="/api/security"`）：`GET /summary`、`/trend`、`/findings`、`/recommendations`、`/attack-paths`；`app.py:292` 后 include |
| Security 页 | 新 `pages/Security.tsx`（镜像 `AgentMetrics.tsx` recharts + `Card`）：评分趋势曲线 + 类别雷达 + 发现/建议/暴露链列表（复用 `GalaxyNodePanel` 的严重度边框行样式） |
| 路由/导航 | `App.tsx:22,165` 加 lazy import + route；`NavItems.tsx:18` 加 nav 项 + `ICON_PATHS.shield`；`locales/en.json`+`zh.json` 加 `nav.security` |
| 数据层 | 新 `hooks/useSecurity.ts`（镜像 `useGalaxy.ts`）；`api/types.ts` 加 `SecuritySummary/SecurityTrendPoint/SecurityFinding/SecurityRecommendation/AttackPath` |
| Dashboard 高亮卡 | `pages/Dashboard.tsx:50` kpis 数组加安全分格（复用 `hot` 标记 + `SEV_DOT`），或 `:87` 前插高亮块 |

### 3.8 报告类型 `security-review`

6 处编辑（report_type 是 free-string，无需迁移）：`report/generator.py:369` 加 `generate_security_review_report`（镜像 network health）；`app.py:3197` 加 elif；`schemas.py:172` 正则加类型；`report_tools.py:41` valid_types 加；`reporter_agent.py:37,114` 提示词加一条；可选 `pages/Reports.tsx:10` 加色。

## 4. 数据模型（`models.py`）

```python
class SecuritySnapshot(Base):          # 态势快照时间序列
    id; account_id; provider; created_at
    overall_score: float               # 0-100
    category_scores: JSON              # {iam:.., network:.., data:.., logging:..}
    metrics: JSON                      # {no_mfa:3, stale_keys:5, open_sg:2, unencrypted_ebs:10, ...}
    exposure_paths: JSON               # Top-N 暴露链 [{resource_id, port, path:[...], reachability}]
    cis_results: JSON                  # {control_id: pass|fail}（可复现审计）

class SecurityRecommendation(Base):    # 证据接地建议
    id; snapshot_id(FK,nullable); account_id; created_at
    category; title; detail
    evidence_refs: JSON                # [resource_id,...] grounded 证据
    severity; critic_verdict: str      # supported|weak|refuted
    confidence: float; status: str     # open|acknowledged|dismissed|applied
```
发现不建表 → `HealthIssue`（issue_type="security"）。快照保留 `security_snapshot_retention_days` 天，清理复用现有 retention 模式。

## 5. 配置（`config/settings.yaml`，`config.py` 只定义 schema）

```yaml
security_review_enabled: true
security_poll_interval_minutes: 10
security_posture_interval_minutes: 60
security_reachability_nacl_enabled: true
security_advisor_enabled: true
security_advisor_critic_enabled: true
security_snapshot_retention_days: 90
security_model_id: ""                  # 空=bedrock_model_id_cheap
```

## 6. 错误处理 / 失败模式

| 场景 | 处理 |
|------|------|
| 单个采集源失败 | fail-soft：记 WARNING，跳过该源，其他源照常；cursor 不前移（下轮重试，不丢数据） |
| 可达性输入数据缺失 | 保守标 `undetermined`，绝不标 `not_reachable`（原则 3） |
| 建议不 grounded / critic refuted | fail-closed 丢弃，不入库 |
| 账户凭证解析失败 | 显式报错跳过该账户，不回退 ambient（凭证铁律） |
| LLM/critic 异常 | 跳过建议生成，态势快照与评分照常落库（评分不依赖 LLM） |
| scheduler 分支异常 | 写 `ScheduleExecution` status=failed（复制 galaxy 失败块），不影响其他 schedule |

## 7. 测试计划（对抗性优先）

| 文件 | 覆盖 |
|------|------|
| `test_security_reachability.py` | ★ 三态判定：SG 开放但(无公网IP/私有子网/blackhole/NACL入站拦截/NACL出站临时端口拦截/实例stopped)→ `not_reachable`；数据缺失→ `undetermined`；全通→ `reachable` + 正确暴露链 |
| `test_security_scoring.py` | CIS pass/fail 判定；同快照两次算分一致（可复现）；可达性不篡改分数 |
| `test_security_poll.py` | cursor 增量（只拉新）；单源失败 fail-soft；SignalInput 构造正确；跨轮去重折叠 |
| `test_security_advisor.py` | 证据不 grounded → 丢弃；critic refuted → 丢弃；LLM 异常 → 不产出 |
| `test_security_snapshot.py` | 快照落库；retention 清理；多账户各一份 |
| `test_security_api.py` | `/api/security/*` 各端点返回契约 |

## 8. 验收标准（对应基线 §验收纲要）

1. 可达性对抗测试全绿（§7 第一行全部用例）。
2. 采集 fail-soft + cursor 不丢数据。
3. CIS 评分可复现。
4. 建议证据接地 + critic 门生效。
5. 发现经 signal_gate 去重。
6. 多账户不串号（走 provider 层）。
7. `npx tsc --noEmit` + `npm run build` 通过；`py_compile` 通过。
8. 真实环境 E2E + 主人确认后才 push。

## 9. 实施顺序（每阶段可独立验证，先跑通"能出分"）

| 阶段 | 内容 | 可验证产出 |
|------|------|-----------|
| 0 | 数据模型 + config + 调度骨架（空 job seed 能跑） | schedule 出现在库、按周期触发空函数 |
| 1 | 慢频态势采集 + CIS 评分 + SecuritySnapshot | 能出一份评分快照（无关联/无建议） |
| 2 | 关联引擎扩展 1+2+4（SG规则上节点+subnet flag+有向评估，**暂不含NACL**） | 可达性三态（不计 NACL），对抗测试第一批绿 |
| 3 | NACL 采集 + 有序求值（补齐 P1 精度） | NACL 拦截用例绿，可达性精度达标 |
| 4 | 快频增量采集 + signal_gate 接入 + Dashboard 高亮 | 新 finding 分钟级进 issue 列表 + Dashboard 高亮 |
| 5 | 证据接地建议器 + critic | 建议入 SecurityRecommendation |
| 6 | Security 页 + API + `security-review` 报告 | 前端可视 + 报告可生成 |
| 7 | E2E（真实账户）+ 文档更新（WORKFLOW/CLAUDE/本 release） | E2E 证据报告 |

阶段 2 先不含 NACL 能让可达性主体逻辑早验证，阶段 3 再补 NACL 达到 P1 精度定档 —— 符合"从最简单方案入手、逐步加深"。

## 10. 风险与开放问题

- **CIS 控制子集**：P1 覆盖 security-engineer skill 已列控制，非完整 CIS benchmark；完整覆盖排 P2。
- **大账户图构建成本**：慢频 60min 可吸收；若单账户资源过多需分区域增量构图（P1 观察，必要时优化）。
- **建议模型 tier**：默认 cheap；若发现建议质量不足，`security_model_id` 可上调 mid（精确度优先允许）。
- **NACL 求值复杂度**：有序 allow/deny + 临时端口是易错点，必须由 §7 对抗测试锁死。
