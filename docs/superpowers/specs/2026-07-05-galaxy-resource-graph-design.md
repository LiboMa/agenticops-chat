# Galaxy — 全景资源关系图（LLM 混合构图）Design

**Date:** 2026-07-05
**Status:** Approved for PoC（brainstorm 完成；可行性已用真实 Bedrock 探针验证）
**Scope decision:** 先做全景关系图 PoC；「一键托管」自主运营模式是独立的下一个子项目，另行 brainstorm。本图同时是未来托管模式的世界模型（world model）基础。

---

## 0. 核心理念与信任模型（Trust & Provenance）

运维和产线一样容不得纰漏，因此本设计的前提是**不信任 LLM 的输出**：

1. **图的事实骨架不由 LLM 生成。** 包含关系与 ID 引用边全部由代码从 raw_data 确定性推导（L1 层），零幻觉可能。
2. **LLM 输出只是提案，入图前必须过机器质检（fail-closed）：**
   - 端点校验：边两端 ID 必须存在于 cloud_resources 库存，否则丢弃并计数——LLM 无法"发明"资源；
   - 证据回验：每条 LLM 边必须携带 evidence 串，代码回查该资源 raw_data/tags，证据指认不出来 = 拒收；
   - 丢弃率监控：拒收率超阈值（默认 5%）记录告警——prompt/模型漂移的烟雾探测器。
3. **错误代价分级：**

   | 边类型 | 来源 | 错误后果 | 允许用途 |
   |---|---|---|---|
   | 事实边（包含/引用） | 代码规则（provenance=rule） | 不会错 | 展示 + 未来自主托管的行动依据 |
   | 语义边（归组/推断） | LLM+证据回验（provenance=llm） | 导航不便，改分组而已 | 仅辅助理解；前端虚线+置信度渲染；**永不作为执行依据** |

4. **未来托管模式硬约束（现在写死，将来照办）：** 任何变更动作只能基于 provenance=rule 的边；LLM 边只用于缩小排查范围，执行前必须现场 API 复核。与凭证安全铁律同一哲学：解析失败显式报错，绝不静默放行。
5. **演进假设：** LLM 能力持续增强 → L2/L3 语义分析质量随之提升，而验证关卡不变。模型可整体换代（记录 model_id + prompt_version，换模型先影子构建 diff 再切换），架构不动。

### 可行性实证（2026-07-05 真实探针，非估算）

- 72 个真实资源（busy VPC + EKS + 未打标 IAM/S3）→ Bedrock Haiku 4.5，输入 62,446 tok，延迟 84s/批。
- temp=0 跑两次：边集合 **100% 一致**（jaccard 1.00）——同输入输出可复现。
- 抽样 30 条边逐条对库验证：**ID 类边 100% 正确，零幻觉**；对无 Project 标签的资源，LLM 诚实标注推断依据（"tags.Project not present but Purpose=… and Project_env=…"）。
- 输出在 16384 max_tokens 被打满截断 → 批次上限定为 ~40 资源。
- 成本否决纯 LLM 每小时全量重建（~$1.5-2/次 → $1,100+/月，且库中 5 周仅 5 天真的扫描过）→ 采用哈希增量（下述），稳态 ~$1-3/月。

---

## 1. 目标 / 非目标

**目标**：路由 `/galaxy` 的可拖拽、可点击、可下钻全景图：

- 归属层级：账号 → 分组（项目/系统/集群/栈，由构图管线产出）→ 资源
- 资源间引用关系边 + 语义归组边（区分 provenance 渲染）
- 健康状态叠加（open HealthIssue 着色，最差状态向上汇聚）
- 后台构建 + 持久化，前端秒开；默认每小时自动检查更新，可手动重建；UI 优雅展示构建状态

**非目标（本轮不做）**：

- 一键托管/自主运营（独立子项目；本 spec 只保证图带够 provenance/freshness 供其未来消费）
- 深度网络拓扑（现有 `graph/` 引擎已覆盖 SPOF/可达性；不碰、不合并——PoC 阶段 Galaxy 是独立、可抛弃的实验层；两图收敛留待 PoC 验证后决策）
- TraceID/日志/指标证据源（EvidenceRecord 接口形状预留，采集器不建）
- 手动纠错/固定分组的 override 存储（PoC 后按需加）
- 多云 provider 数据（builder prompt 保持云中立，关系概念为主、AWS 名仅作 example，符合项目云中立规则）

---

## 2. 构图管线（三层混合）

```
cloud_resources (raw_data, tags)         ← 唯一数据源（多账号）
        │
        ▼
[每小时任务 / 手动触发]
  ① 内容哈希 diff（canonical JSON, sort_keys, 剥离易变字段）—— 亚秒级
  │    无变化 → 退出（$0，不写 build 行，仅更新 last_verified_at）
  │    有变化 ↓（首次构建/手动重建 = 全量）
  ② L1 代码规则层（免费、瞬时、确定性；provenance=rule）
  │    - 账号→VPC→子网→实例 等包含边（CONTAINS）
  │    - 精确 ID 引用边（vpc_id/subnet_id/SG/ARN 字符串匹配；REFERENCES）
  │    - 标签相等归组（~24% 已打标资源；MEMBER_OF）
  │    - IAMRole/KMS/S3/ECR 等关系稀薄的叶子类型到此为止，不进 LLM
  ③ L2 LLM 全局索引（Haiku，~$0.16，仅脏数据时）
  │    - 代码为每资源生成 ~40 tok 摘要（id/type/name/关键引用/分组线索），全量一次性给 LLM
  │    - 产出：跨批次归组候选 + 未打标资源的 project/system 推断
  ④ L3 LLM 语义增强（仅脏批次；批 ≤40 资源，按 account→vpc 局部性分批）
  │    - 每批附 L2 全局索引为只读上下文（解决跨批盲区）
  │    - 结构化输出，关系类型封闭枚举；temperature=0
  ⑤ 机器质检（fail-closed）：端点校验 + 证据回验 + 丢弃计数
  ⑥ 合并与稳定化（代码）：
  │    - 节点 ID 永远代码分配：res:{cloud_resources.id}；LLM 禁止造资源节点
  │    - 分组注册表：LLM 只能「归入已有分组或提议新 slug」，slug 由代码
  │      归一化去重（create-or-match）；分组 ID 跨构建稳定
  │    - 边身份键 (source, target, relation_type)；冲突取高 confidence
  ▼
galaxy_builds 持久化（rule 层与 llm 层分开存，读时合并）
        │
        ▼
GET /api/galaxy/*  ← 前端只读切片，秒开
```

### 关系类型（封闭枚举，PoC 起步集）

`contains` / `references` / `member_of`（归组）/ `attached_to` / `secured_by` / `routes_to` / `inferred_group`（LLM 语义归组专用）。自由文本只允许出现在 evidence 字段。

### 每条边的完整属性

`{source, target, relation_type, provenance: rule|llm, evidence, confidence, model_id?, prompt_version?, build_id, observed_at}`

### 触发方式

- **每小时定时**（复用现有 Scheduler，新 pipeline_name=GalaxyBuild）：哈希 diff → 增量
- **手动「重建」按钮**：强制全量（POST /rebuild?full=true）
- **扫描完成后钩子**：scan 落库后触发一次增量检查

### 成本与模型

- Builder 固定用 `bedrock_model_id_cheap`（Haiku 4.5）；settings.yaml 可覆盖（`galaxy_model_id`）
- 每次 build 的 token 用量经现有 `cost.py compute_cost()` 记入 build 行（Cost 页可见 Galaxy 花销）
- 换模型/prompt 升级：先影子构建，diff 边集合后再切换为当前 build

---

## 3. 后端（新模块 `src/agenticops/galaxy/`）

| 文件 | 职责 |
|---|---|
| `hashing.py` | canonical 序列化 + 易变字段剥离 + 内容哈希；哈希状态存 `galaxy_resource_state` 表 |
| `rules.py` | L1 确定性边推导（纯函数：rows → nodes+edges） |
| `builder.py` | 管线编排：diff → L1 → L2 → L3 → 质检 → 合并稳定化 → 入库；后台线程运行，进度可查 |
| `api.py` | APIRouter `/api/galaxy`，在 web/app.py include |

**LLM 调用走 `get_bedrock_session()`（Bedrock 控制面，凭证铁律的合法例外）。**

### 新表

- `galaxy_builds`：id, status(running/completed/failed), trigger(auto/manual/scan), full(bool), started_at, finished_at, model_id, prompt_version, input_tokens, output_tokens, cost_usd, node_count, edge_count, dropped_edge_count, rule_graph JSON, llm_graph JSON, error
- `galaxy_resource_state`：resource_pk, content_hash, last_analyzed_build_id
- `galaxy_groups`（分组注册表）：slug, display_name, kind(project/system/cluster/stack/untagged), created_by_build, member_count

### 端点

| 端点 | 说明 |
|---|---|
| `POST /api/galaxy/rebuild?full=` | 触发后台构建，202 + build_id；已在构建中则 409 |
| `GET /api/galaxy/status` | 当前/最近 build：状态、进度（批次 x/y）、耗时、成本、丢弃计数、下次自动检查时间 |
| `GET /api/galaxy/overview` | 顶层图：账号 + 分组节点（资源计数、类型分布、健康、open issue 数），不含资源节点 |
| `GET /api/galaxy/expand?group=&types=&health=` | 展开分组：组内资源节点 + 组内/跨组边（rule+llm 合并，带 provenance）；截断上限 200 节点（按 issue 数优先），返回 truncated 标志 |

节点详情复用现有 `GET /api/resources/{id}` + `/issues`，不新增。

### 配置（settings.yaml，config.py 只定 schema）

`galaxy_enabled`(true) / `galaxy_build_interval_minutes`(60) / `galaxy_model_id`("") / `galaxy_batch_size`(40) / `galaxy_confidence_min`(0.5) / `galaxy_drop_rate_alert`(0.05) / `galaxy_expand_node_cap`(200) / `galaxy_llm_exclude_types`(["IAMRole","KMS","S3","ECR_Repository"])

---

## 4. 前端（`pages/Galaxy.tsx`，路由 `/galaxy`，侧边栏新入口）

- 重新引入 `@xyflow/react` + `@dagrejs/dagre`（旧拓扑 UI commit b984743 有参考实现）
- **默认 overview 层**：账号 + 分组节点，dagre 自动布局，可拖拽；**双击分组下钻**（expand 就地展开/收起）
- **单击节点** → 右侧详情面板（house rule：`animate-[slideInRight_0.2s_ease-out]` + ESC 关闭）：分组节点显示计数/类型分布/issue 汇总；资源节点显示标签、状态、evidence 列表、跳转 `/resources/:id`
- **Provenance 可视化**：rule 边实线；llm 边虚线 + hover 显示 evidence 与 confidence
- **健康着色**：healthy 默认 / warning 橙 / critical 红；分组带 issue 计数徽章
- **构建状态条（优雅、易用）**：页面顶部常驻轻量状态区——「构建于 xx 分钟前 · 下次检查 xx」+ 手动重建按钮；构建中变为进度态（批次进度 + 可取消关注）；构建失败显示原因 + 重试。构建完成后 toast 提示「图已更新」+ 一键刷新视图（不强制打断用户当前布局）
- **工具条**：账号/类型/健康过滤 + 搜索；默认隐藏噪声类型（IAMRole/KMS/ECR），可勾选恢复
- Hooks：`useGalaxyOverview` / `useGalaxyExpand` / `useGalaxyStatus`（构建中 5s 轮询，空闲 60s）

---

## 5. 错误处理与性能

- DB 无资源 → 空态页引导先扫描；无任何 build → 引导点击首次构建
- L3 单批失败重试 1 次，再失败 → 该批回退 L1 纯规则边（图不残缺，只是语义层缺失，status 中标注）
- Bedrock 不可达 → build 标记 failed，rule 层仍每次重算可用（LLM 层用上一次成功结果）
- builder 全程批量查询无 N+1；哈希 diff 亚秒；overview/expand 纯 DB 读毫秒级
- 标签/raw_data 脏数据（非 dict、空串）按无标签处理，不抛错
- 跨账号同名分组不合并（slug 含 account 维度）

---

## 6. 测试

- **pytest**（`tests/test_galaxy_hashing.py` / `test_galaxy_rules.py` / `test_galaxy_builder.py` / `test_galaxy_api.py`）：
  - 哈希：canonical 序列化稳定性、易变字段剥离、diff 正确性
  - L1 规则：包含边、ID 引用边、标签归组、叶子类型排除
  - 质检：端点不在库存 → 丢弃；evidence 回验失败 → 拒收；丢弃率计数
  - 稳定化：分组 create-or-match、节点 ID 不变性、边冲突合并
  - builder：LLM mock 注入（不真调 Bedrock），全流程 + 失败回退路径
  - API：rebuild 409 互斥、status 形状、overview/expand 契约与截断
- **前端**：`npx tsc --noEmit` + `npm run build`
- **E2E**（Playwright 本地起服务）：首次构建 → overview 渲染 → 下钻 → 点节点面板 → ESC → provenance 虚实线可辨 → 手动重建状态流转。**按项目规矩：E2E 通过 + 主人确认后才 push。**

---

## 决策记录

| 决策点 | 选择 | 依据 |
|---|---|---|
| 范围 | 先图后托管 | 图是托管的世界模型基础 |
| 关系推导主体 | **混合三层**：机械关系=代码，语义关系=LLM | 探针+成本+对抗批判三方收敛；纯 LLM 重derive机械边只增错误模式 |
| 幻觉防线 | fail-closed 机器质检 + provenance 分级 + LLM 边永不驱动执行 | 用户明确要求产线级可靠性（2026-07-05） |
| 数据源 | CloudResource DB（多账号） | 不现拉 AWS；不碰现有 graph 引擎 |
| 更新策略 | 每小时哈希 diff 增量 + 手动全量 | 纯 LLM 每小时全量 $1,100+/月且 99% 无信息增益；增量稳态 ~$1-3/月 |
| 模型 | Haiku 4.5（cheap tier），可配置 | 抽取型任务；LLM 换代→影子构建 diff→切换，架构不变 |
| 默认视图 | 逐层下钻 + 噪声类型默认隐藏 | 1287 资源全铺不可读（IAMRole 即 474） |
| 健康状态 | 本轮叠加 | 图 = 服务状态全貌 |
| 命名 | **Galaxy** | 用户指定 |
