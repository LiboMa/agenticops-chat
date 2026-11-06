# 研究报告：在 AWS 中国区用 AgentCore 运行 AgenticOps（含自定义模型 Provider）

日期：2026-11-06 · 状态：**研究结论，待主人决策**（不是实施计划）· 只读研究，未改代码
姊妹篇：[`2026-11-06-strands-upgrade-study.md`](2026-11-06-strands-upgrade-study.md)（Strands 升级，独立成文）

> **更正**：本日早些时候「AgentCore 不在中国区」的结论是错的 —— 当时只查了全球区域页（没有中国列）和一张
> 2026-02-28 更新的 amazonaws.cn 产品表。**AgentCore 自 2026-09-27 起已在北京、宁夏两区可用**（精简版，见 §1）。
> 中国区可用性要以 docs.amazonaws.cn 与 amazonaws.cn/en/new 为准。

## 0. 结论

1. **现在就能走**，但中国区是精简版：Runtime 只有 **microVM**（没有 Instances），没有 Memory、Harness、Policy、
   Evaluations，**没有 Bedrock**（所以没有 Claude）。在中国区跑 AgenticOps 的硬前提是 **模型 Provider 层**
   （OpenAI 兼容的国产 / 私有化模型）。
2. **不能把整个应用塞进一个 Runtime 会话**（方案 A）：microVM 最长 8 h 回收、会话盘随版本更新清空（SQLite 会被抹）、
   浏览器无法给页面请求签名、只有公网入口、告警 webhook 发送方不会 SigV4。
3. **推荐方案 B：控制面 / Agent 执行面拆分**。FastAPI + UI + 调度 + DB + 告警 / IM 入口留在 ECS（宁夏），Agent 运行
   放进 AgentCore Runtime（microVM、VPC 模式），控制面用 `InvokeAgentRuntime` 流式转发，前端 SSE 契约不变。
4. Agent 执行容器用 `BedrockAgentCoreApp`（本质是 Starlette 应用）写，**同一契约在任何地方都能跑**（本机 / ECS / EKS），
   所以可以先在全球区用 Claude 验证、再上中国区；AgentCore 出问题时可自建兜底（方案 C）。
5. 一个分区一套部署：中国区只管理 aws-cn 账户（IAM 不能跨分区）；全球账户留在全球部署。

## 1. 事实（每条附出处；「未确认」= 没能核实）

### 1.1 中国区 AgentCore

| 项 | 事实 | 出处 |
|---|---|---|
| 上线 | 2026-09-27 起北京（光环新网）、宁夏（西云数据）可用；上线即有 agent runtime、身份与访问控制、会话持久化、工具连接、可观测性 | https://www.amazonaws.cn/en/new/2026/amazon-bedrock-agentcore-is-available/ |
| 可用组件 | Runtime、Code Interpreter、Browser、Identity、Gateway、Observability | https://docs.amazonaws.cn/en_us/aws/latest/userguide/bedrock-agentcore.html |
| 不可用 | Memory、Policy、Harness、Payments、Knowledge Bases、Evaluations、Optimizations、Registry | 同上 |
| Runtime | **只有 MicroVM 容量提供方**（没有托管 EC2 Instances）；无 S3 Files 自带文件系统；无 Cognito 入站认证 | 同上 |
| Gateway | 无语义搜索、无 Cognito 授权、不允许「无授权」、**无 inference targets**、无 connector catalog、无 WAF | 同上 |
| Identity | 无私有 IdP；GitHub / Google / Facebook / X 等多数社交 OAuth 不可用 | 同上 |
| Bedrock | 中国区不可用；AgentCore 独立于 Bedrock，FAQ 以 DeepSeek / Qwen / Kimi 为例 | https://www.amazonaws.cn/en/agentcore/faqs/ |
| 价格 | microVM ¥0.8669 / vCPU·h、¥0.1148 / GB·h；Gateway ¥0.034 / 千次；经 Runtime / Gateway 用 Identity 免费 | https://www.amazonaws.cn/en/agentcore/pricing/ |
| Runtime V2 | 快照冷启动、会话级 IAM 上下文键；列出的 10 个区没有中国区 —— **未确认，大概率没有** | runtime-how-it-works |

### 1.2 Runtime 的硬约束（全球 devguide：https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/）

- **microVM**：每会话一个 microVM；空闲默认 15 min、最长 8 h（都可配 60–28,800 s）；到期后同一会话 id 换新环境，状态不保留。
- **容器契约**：0.0.0.0:8080；**ARM64 必须**；`POST /invocations`（JSON 或 SSE）、`GET /ping`（Healthy / HealthyBusy）、`/ws`。
- **限额**：同步 15 min、流式 60 min、异步任务 8 h；每会话固定 2 vCPU / 8 GB；镜像 ≤ 2 GB；**环境变量 ≤ 4 KB**；
  活跃会话 2,500；新建会话 25 TPS；会话 id ≥ 33 字符。
- **存储**：会话盘（Preview）1 GB，停 / 恢复保留，**空闲 14 天或任何 Runtime 版本更新时清空**；跨会话共享要自带 EFS（VPC）。
- **Session endpoints**（`allowedPorts`）：每个请求都要 SigV4 或 OAuth bearer；不支持 Instances；只有公网入口；
  SDK 源码注明浏览器无法给页面自发请求加签名。
- **入站认证**：SigV4 或 JWT 二选一；「AgentCore 不强制会话与用户的映射」—— 用户归属要我们后端自己保证。
- **第三方模型**：「任何基础模型都可以用于 AgentCore Runtime」，示例是 Strands `OpenAIModel(client_args={"base_url": …})`；
  API key 用 Identity 的 API-key credential provider（`@requires_api_key`）。
- **`BedrockAgentCoreApp`**（bedrock-agentcore 1.25.3，读了 wheel 源码）：Starlette 子类，路由 `/invocations`、`/ping`、`/ws`；
  `run()` 即 `uvicorn.run`；会话 id 来自 `X-Amzn-Bedrock-AgentCore-Runtime-Session-Id` 头；**自身不做入站认证**
  → **同一契约在任何地方都能跑**。SDK 能解析 cn-* 区域的 `amazonaws.com.cn` 端点；需要 boto3/botocore ≥ 1.43.115
  （我们现在是 1.42.49）。在 Runtime 之外，Identity 装饰器行为不同（容器里会直接报错），自建时改用密钥库。

### 1.3 中国区可用的模型来源

**OpenAI 兼容的厂商 API（2026-11 文档）**

| 厂商 | Base URL | 工具调用 | 思考模式 + 工具循环 |
|---|---|---|---|
| DeepSeek | `https://api.deepseek.com` | 支持；`/beta` 严格模式 | **带工具时必须回传全部历史 `reasoning_content`，否则 400** |
| 阿里百炼（Qwen） | `https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1`（旧 dashscope 地址：未确认） | 支持，含流式工具调用 | `enable_thinking`；思考模式下拒绝 `tool_choice` required / 指定函数 |
| 火山方舟（豆包） | `https://ark.cn-beijing.volces.com/api/v3` | 支持；并行、strict | 文档建议函数调用时关闭思考 |
| 智谱（GLM） | `https://open.bigmodel.cn/api/paas/v4/` | 支持；`tool_choice` 只能 auto | 工具循环中必须回传 `reasoning_content` |
| Moonshot（Kimi） | `https://api.moonshot.cn/v1` | 支持 | 工具序列中必须保留 `reasoning_content` |
| MiniMax | `https://api.minimax.cn/v1` | 支持 | 必须回传含 thinking 的完整 assistant 消息 |

**自建（数据不出 VPC）**：vLLM（`--enable-auto-tool-choice --tool-call-parser hermes|deepseek_v3|kimi_k2|glm45…` +
`--reasoning-parser`）或 SGLang。中国区 GPU 只有 **G4dn、G5（A10G 24 GiB/卡）、Inf1**，没有 P4 / P5 / G6；
g5.48xlarge 为 8 卡 192 GiB，只能跑中等规模模型。SageMaker AI 在两区可用，但推理不含 p4d / g5 / Inferentia、无 Serverless。

**关键缺口**：Strands 的 OpenAI（Chat Completions）provider 在 1.45 和最新 1.64 里都会**丢弃历史中的
`reasoningContent`**（源码有告警）。不补的话，「思考模式 + 工具」在 DeepSeek 上直接 400，在 Kimi / GLM / MiniMax 上
大概率失败（有的不能关思考）。

### 1.4 合规（概述，非法律意见）

- 《生成式人工智能服务管理暂行办法》第 2 条：只管「向境内公众提供」的服务；企业内部使用、不向公众提供的不在范围内；
  第 17 条：具舆论属性的需安全评估与算法备案。
- 《个人信息保护法》第 38–40 条：个人信息出境需安全评估 / 认证 / 标准合同；运维遥测里的用户名、IP 可能是个人信息。
- 中国区服务器对公网提供访问的域名需 ICP 备案（经西云数据 / 光环新网，3–20 个工作日）。
- 2024 年 CAC 数据出境新规细节：未确认。
- IAM 凭证不能跨分区使用（aws ↔ aws-cn 不能 AssumeRole）。

## 2. AgenticOps 现状与拆分代价（本次清点）

| 现状 | 数量 | 拆分到 AgentCore 后 |
|---|---|---|
| 模块级锁 | 14（signal_gate、change_service、galaxy、凭证解析、policy、通知…） | 跨进程失效 → DB advisory lock，或改走控制面 API |
| 模块级缓存 | 4（会话 agent、凭证会话、图查询、集成） | 每个会话各自重建 |
| 后台线程起点 | 约 24 处 / 15 个文件（自动 RCA/SRE/执行、调度、通知、翻译、IM 长连接…） | 留在控制面；Agent 面只做被调用的任务 |
| 写 `agent-memory/`、`skills/` 的模块 | 7 | 共享存储（EFS 或 DB/S3） |
| Agent 工具直接访问 DB | 12 个模块 | Agent 面经 VPC 访问 PostgreSQL（SQLite 不行） |
| 构建 `BedrockModel` | 9 处 | Provider 工厂 |
| 直调 `bedrock-runtime` | 约 11 个模块（signal_gate、galaxy、翻译、技能构建、Titan embedding…） | 统一文本补全 / embedding 门面 |

## 3. 方案对比

| 方案 | 说明 | 结论 | 规模 |
|---|---|---|---|
| A 整体塞进一个 Runtime 会话 | 用 session endpoint 暴露整个 Web 应用 | **不可行**（§0 第 2 条；且中国区没有 Instances） | — |
| **B 控制面 + Agent 执行面** | 宁夏 ECS：FastAPI / UI / 调度 / DB / 告警与 IM 入口；AgentCore Runtime（microVM、VPC）：Agent 运行。`runtimeSessionId` = chat 会话 id（补齐 ≥ 33 字符），流式转发；RCA / SRE 审核 / 执行走异步任务 + `HealthyBusy`；执行角色对应凭证铁律里的 `environment` 来源（GetCallerIdentity 校验）再 AssumeRole 目标账户 | **推荐** | 约 6–10 人周（含多进程加固） |
| C 同一容器自建 | 同一个 `BedrockAgentCoreApp` 跑在宁夏 ECS / EKS | **兜底 / 开发一致性**：失去每会话 microVM 隔离和平台入站认证（要自己加 JWT / mTLS / 安全组） | B 之上约 1 周 |
| D 全球区 AgentCore 管中国账户 | 新加坡跑全部能力（含 Claude），跨境管理 aws-cn 账户 | 技术最近、**合规风险最高**：要 aws-cn 长期 AK；所有扫描 / RCA 把中国遥测带出境（PIPL 第 38 条） | 小 |

方案 B 的固定代价：SQLite → PostgreSQL；Agent 面可达的进程内锁改 DB 锁；Web 修改的运行时设置进 DB；
`agent-memory/`、`skills/` 进共享存储；镜像 ARM64 且 ≤ 2 GB（含 kubectl / aws-cli / ssh）；配置不能放环境变量（≤ 4 KB），
要打进镜像或运行时读取；SSH 密钥进密钥库；每个新会话有冷启动（中国区大概率没有 V2 快照）；单轮流式 ≤ 60 min。

## 4. 模型 Provider 层（中国区的前提）

与主人 11-06 的要求一致：**模型配置进 DB、在 Web 上配置**（yaml 只做首次种子），密钥不落库。

- **Provider 注册表（DB）**：类型 `bedrock | openai_compat | anthropic_compat | litellm`；`base_url`；密钥引用（Secrets Manager /
  AgentCore Identity API-key provider / 环境变量 —— 永不明文入 DB 或 yaml）；能力标记：`tools`、`stream_tools`、`thinking_shape`、
  `echo_reasoning`、`tool_choice_modes`、`json_mode`、上下文窗口、价格（含币种）。
- **模型分配（DB）**：每个 agent 和每个辅助用途（Signal Gate L2、critic、翻译、Galaxy、security advisor、技能构建、embedding）
  都写成 `provider:model`。顺带修掉技能构建用错模型（dev 上被环境变量钉成 Opus 4.6）。
- **一个工厂**替换 9 处 `BedrockModel`、约 11 处直调和 embedding 路径。
- **`OpenAIModel` 子类**：`echo_reasoning` 开启时把 `reasoning_content` 回写到 assistant 消息；不支持的 provider，用工具的
  agent 关闭思考。并给 Strands 上游提 issue。
- **成本 / 窗口表**补上新模型家族，否则静默按 $0 计费。
- **质量门槛**：每个候选模型重跑 13 例 RCA 定位评测 + L1/L2 chaos E2E；单独检查 Signal Gate L2 与 critic 的 JSON 可靠性。
- 可达面（规则 9）：

| 面 | 做 / 非目标 |
|---|---|
| CLI | 做：`/model` 接受 `provider:model`；`aiops providers list/test` |
| Web API | 做：`/api/settings/model-providers`（增删改、连通测试、模型列表；密钥只显示是否已配置） |
| Web UI | 做：Settings → Model providers 卡片；现有模型选择器显示 provider |
| Agent tool | 非目标（agent 不配置 provider） |
| Schedule | 非目标 |
| Notification | 做：provider 连续失败时通知 |

## 5. 分阶段路线（建议）

| 阶段 | 内容 | 依赖 | 规模 |
|---|---|---|---|
| P0 中国区 spike | 宁夏账户建 microVM Runtime（VPC + EFS），验证流式、HealthyBusy、V1/V2、会话盘、CloudFormation；厂商对比（思考 + 工具、流式工具、`tool_choice`） | — | 约 1 周 |
| P1 模型 Provider 层 | §4 全部（与 tracker 里的 models/db-web、models/skill-consistency、models/openai-compat 合并） | 建议先做 Strands 1.64 升级（见姊妹篇） | 约 3–4 周 |
| P2 多进程安全 | PostgreSQL、DB 锁、设置进 DB、memory / skills 共享存储（控制面仍单进程） | — | 约 2–4 周 |
| P3 Agent 执行面 | `agent_execution_backend = inprocess | agentcore | http`、worker 入口、流转发、异步流水线任务；先在 ap-southeast-1 用 Claude 验证，再上宁夏 microVM | P1、P2 | 约 3–5 周 |
| P4 中国区整站 | 宁夏 ECS 控制面 + RDS PostgreSQL + EFS + ALB（ICP 备案）+ AgentCore Runtime（VPC）+ 厂商 API 和 / 或 G5 上的 vLLM；只管理 aws-cn 账户 | P3、P0 | 约 2–3 周 + 备案周期 |

## 6. 主人已定（2026-11-06）

- 中国区部署**内部使用**（不向公众提供 → 不在生成式 AI 服务备案范围；公网访问仍需 ICP，建议只开内网）。
- 模型**可以用国产厂商 API**（DeepSeek / Qwen / 豆包 / GLM / Kimi 等；数据会到厂商）；自建仍保留为选项。
- **一个分区一套部署**：中国区部署只管理 aws-cn 账户，全球账户留在全球部署（无跨境数据）。
- 下一步先做 **Strands 1.45 → 1.64 保持行为升级**（见姊妹篇），再做模型 Provider 层。

## 6.1 仍待决定

1. 没有 Claude 时的质量底线（例如定位评测 ≥ 某分）？首选哪家厂商做 P0 对比？
2. `agent-memory/`、`skills/` 放 **EFS** 还是 **DB**？
3. 中国区入站认证（无 Cognito）：只允许控制面 SigV4 调用（推荐），还是接第三方 OIDC？
4. P0 spike 用哪个中国区账户（宁夏 cn-northwest-1 优先）？
5. 与 2.7.1 A 轨、RBAC 管理的先后。

## 7. P0 要核实的未确认项

中国区 Runtime 是 V1 还是 V2、会话盘是否可用；自带 EFS 在中国区是否可用（未列为不可用）；AgentCore 在中国区的
PrivateLink 与 CloudFormation 支持；旧 DashScope 地址是否可用；DeepSeek / MiniMax 的 Anthropic 格式端点（`/anthropic`）是否
接受无签名的 thinking 块。
