# AgenticOps

**Agent-first 云运维平台。** 一支专职 AI 智能体团队,扫描你的 AWS 基础设施、发现问题、定位根因、规划修复,并针对低风险问题**自主修复**。它们还会**学习**:每一次运维都在打磨一套自优化的记忆与技能库。

**适合谁:** 想要一个"从 *告警 → 根因 → 修复* 全闭环"的 on-call 副驾,而不只是又一个看板的 SRE / 平台 / 云运维团队。把它指向你的 AWS 账号,它会巡检、说清什么坏了以及为什么坏,并(在你设定的审批策略下)自主修复低风险问题,而任何有风险的操作都留人在环。

> **语言:** [English](README.md) · **中文(当前)**
>
> **版本**:2.5.0 · **最新发布**:[云安全审查 + 技能广域加载(URL / git / zip)、脚本沙箱与 Skills 页导入器](docs/MVP-2.5.0-RELEASE.md) · **完整历史**见下文 · **文档地图**:[`docs/README.md`](docs/README.md)。
>
> **成熟度:** 智能体流水线 + CLI/Web/API 是经验证的核心(10/10 闭环实验室,见 [验证](#验证))。云安全审查已在两个真实账号(其一在中国区)只读跑通 —— 见 [E2E 报告](docs/MVP-2.5.0-E2E-REPORT.md)。一键 `deploy-sg` 沙箱已端到端跑通;`ec2`/`ecs`/`eks` 的 Terraform 栈仍是脚手架(各方式成熟度见 [部署](#部署))。Galaxy 是实验性 PoC。

三种入口 —— 都驱动同一批智能体:

```
   CLI  (aiops chat)  ┐
   Web Dashboard      ├──►  Main Agent (router)  ──►  6 个专家智能体  ──►  AWS
   IM Bots            ┘
   (飞书/Slack/…)
```

📖 **完整的"请求 → 修复"流程(含 Mermaid 图)见 [`docs/WORKFLOW.md`](docs/WORKFLOW.md)。**

---

## 设计原则

整个系统遵循几条刻意为之的规则 —— 它们解释了下文大部分设计决策:

1. **智能体即工具。** Main 智能体是*纯路由*;每个专家(Scan、Detect、RCA、SRE、Executor、Reporter)都以可调用工具的形式暴露。专家之间不直接对话。
2. **读 / 规划 / 执行相互隔离。** SRE 只*规划*修复,永不触碰基础设施;只有 Executor 执行,且必须先过审批门。风险分级:L0/L1 自动批准,L2/L3 需人工。
3. **分层模型控成本。** 最需要判断力的地方用 Claude 5 家族(Main 用 Opus 5 路由,SRE 用 Fable 5.1 规划),最重的调查与执行(RCA、Executor)用 Opus 4.6,高吞吐工作(Scan、Detect、Reporter)用 Sonnet 4.6,Haiku 4.5 作为经济档。Bedrock 上的 OpenAI 模型(gpt-oss、GPT-5.x)同样是一等公民;Anthropic 专属特性按模型族门控。可按智能体覆盖;扩展思考的 effort 会对高严重级别或重跑的 RCA 自动升档,也可按对话会话固定。Token 与成本按每次调用追踪,配实时看板(Web + `aiops cost` CLI)。
4. **智能体安全地学习。** 记忆与技能在硬性安全边界内自优化 —— 智能体的写入先落为草稿;发布经安全门禁;人类撰写的知识被固定,永不被自动改动。
5. **配置单一真源。** `config/settings.yaml` 定义一切;环境变量覆盖它。代码从不硬编码配置值。
6. **默认从简。** 本地用 SQLite + 文件记忆;仅在你选择 cloud profile 时才用 Postgres + S3。没有当下需求就不引入任何依赖。

---

## 功能一览

| 能力 | 说明 |
|------|------|
| **扫描 (Scan)** | 20+ 种 AWS 服务类型(EC2、Lambda、RDS、S3、ECS、EKS、DynamoDB、SQS/SNS、VPC/子网/安全组、NAT/TGW、负载均衡器) |
| **监控与检测 (Monitor & Detect)** | CloudWatch 告警/指标、Z-score 异常检测、Prometheus/CloudWatch/Datadog webhook 接入 |
| **信号门 (Signal Gate)** | 所有建问题的路径(webhook、智能体、REST)都过同一道门:确定性去重(fingerprint-v2、抖动、冷却、资源+类型合并)+ 一个只允许*合并*、绝不丢弃的廉价 LLM 灰区裁判。每个事件一条可审计的 Signal 记录,可人工提升为问题 |
| **根因分析 (RCA)** | LLM 驱动的 RCA,结合 CloudTrail 关联、基础设施图、知识库检索;RCA 后的质量门(证据检查 → 对抗式 critic → 置信度阈值)把薄弱或被驳回的结论送进 `needs_review`,而不是自动修复 |
| **自动修复流水线** | HealthIssue → RCA → SRE → 审批(L0/L1) → 执行 → 解决 —— 低风险问题自主完成 |
| **云安全审查** | 双频姿态引擎:每小时一次确定性快照(IAM、S3、日志、VPC/EC2、EBS),由**纯函数、可复现**的评分器按 CIS 打分;含 NACL 的**三态**入口可达性(`reachable` / `not_reachable` / `undetermined` —— 绝不给假的"安全");每 10 分钟增量拉取 GuardDuty / Security Hub / CloudTrail;证据接地的 LLM 建议器 **fail-closed**(未接地或被驳回 → 丢弃)。`/app/security`、`/api/security/*`、`security-review` 报告 |
| **自优化记忆** | 基于文件的智能体记忆,每次运维中学习;智能体自策展、永不删除的归档、prompt-cache 安全的注入 |
| **自主技能** | 16 个领域技能,智能体可创建/改进/合并 —— 仅经安全门禁、人类可审计的流程发布。**广域加载**:从 URL、Git 仓库或 zip/tar.gz 导入技能包 —— 经 CLI、API,或 Skills 页的「URL / Git 仓库」导入器(逐包结果清单 + *已导入* 徽标)。一切先落为草稿;发布前扫描**整包**(含 `.sh`/`.py`);包内脚本只在受限**沙箱**里运行(无凭证、无网络;默认关闭) |
| **并发对话** | 多会话同时流式输出;通过游标分页 + 虚拟化历史实现秒开 |
| **对话附件** | Web 编辑器支持粘贴图片(Cmd+V)、拖拽、多文件上传(最多 5 个);按类型校验大小 |
| **知识库** | 向量 + 关键词混合检索;把已解决案例蒸馏为可复用 SOP |
| **报告与定时任务** | 日报/周报/事件/清单报告;cron 流水线(FullScan、Monitoring、HealthPatrol 等) |
| **消息 (Messaging)** | 统一的 Settings → Messaging 页:机器人应用(飞书/Slack/钉钉/企微 凭据)、通道(Slack/Email/SES/SNS/飞书/钉钉/企微/Webhook)、投递日志 —— schema 驱动、密钥脱敏,经 `/api/messaging/*` |
| **MCP 服务器** | 兼容 Claude Desktop 的 MCP 集成 —— 经 Chat/CLI/Web 管理,热重载 |
| **图引擎 (Graph Engine)** | NetworkX 基础设施图:SPOF 检测、容量风险、依赖链、变更模拟(智能体工具) |
| **Galaxy** *(实验性)* | `/galaxy` 全清单关系图 —— 每个资源作为 Canvas 星云中的星点,按健康态着色、异常脉冲。机械关系边由代码推导(`provenance=rule`);语义边由 LLM 提议但经**fail-closed 校验**(端点必须存在 + 证据能在 `raw_data` 中回验),幻觉绝不作为事实入图。内容哈希增量构建(无变化时 $0) |

---

## 架构

```
CLI (aiops chat)  ──┐
                    ├──► Main Agent (路由) ──► Scan Agent    ──► AWS 服务 API
Web Dashboard ──────┤        │                  Detect Agent  ──► CloudWatch, Prometheus
  (React + SSE)     │        │                  RCA Agent     ──► CloudTrail, KB, Skills, Graph
IM Bots ────────────┘        │                  SRE Agent     ──► 修复方案生成(只读)
                             │                  Executor Agent──► AWS CLI, SSM/SSH, kubectl
                             │                  Reporter Agent──► 报告, KB 蒸馏
                             │
                             ├──► Agent Memory  (agent-memory/*.md —— 自优化)
                             ├──► Agent Skills  (skills/*/SKILL.md —— 自主, 安全门禁)
                             ├──► Security Engine (security/ —— 姿态快照、CIS 评分、可达性)
                             ├──► SQLite / PostgreSQL  (元数据)
                             └──► MCP Servers  (可选外部工具)
```

### 7 个智能体

模型按智能体在 `config/settings.yaml` 中覆盖(`agent_*_model_id`),优先于 `config.py` 里的分层默认值。已提交的默认配置:

| 智能体 | 模型 | 职责 |
|--------|------|------|
| **Main** | Opus 5 | **路由 / 编排。** 唯一与用户对话的智能体;对每个请求分类,并把它作为工具分派给正确的专家,再组合各专家的输出。自身不持有任何运维工具 —— 纯控制流,使路由保持廉价且可审计。 |
| **Scan** | Sonnet 4.6 | **清单发现。** 通过 provider CLI 跨账号/区域枚举资源(20+ 种 AWS 服务类型),归一化后 upsert 进元数据库。为所有下游智能体 + 图/Galaxy 构建器供数。高吞吐、只读。 |
| **Detect** | Sonnet 4.6 | **健康监控与异常检测。** 拉取 CloudWatch 告警/指标,运行 Z-score 异常检测,接入 Prometheus/CloudWatch/Datadog webhook,并开出去重后的 `HealthIssue`(SHA-256 指纹)。同时执行主动巡检(SPOF + 容量风险图检查)。只读。 |
| **RCA** | Opus 4.6 | **根因分析。** 针对一个未决问题,关联 CloudTrail 变更事件、基础设施图(邻居 + 爆炸半径)、知识库案例和领域技能,产出有据可循的根因 + 置信度。只读调查;写入 `RCAResult`,永不触碰基础设施。 |
| **SRE** | Fable 5.1 | **修复方案生成 —— 只规划,不动手。** 把 RCA 转化为具体的、按风险分级(L0–L3)的修复方案,含精确步骤 + 回滚。严格**只读**:它只提议;只有 Executor 能执行,且必须先过审批门。强制"一问题 → 一活跃方案"。 |
| **Executor** | Opus 4.6 | **唯一改动基础设施的智能体。** 执行*已审批*的修复方案,跨后端 —— AWS CLI、SSM(→SSH 兜底)、`kubectl` —— 采用账号寻址的凭证解析(fail-closed,绝不用 ambient)。审批后自动跑 L0/L1;L2/L3 需人工。推动 9 态问题生命周期直到 `resolved`。 |
| **Reporter** | Sonnet 4.6 | **报告与知识沉淀。** 生成日报/周报/事件/清单报告(Markdown/HTML/PDF,本地或 S3),并把已解决事件蒸馏为可复用的知识库 SOP,让后续 RCA 更快。对运维数据只读。 |

默认来自 `config/settings.yaml` —— Claude 5 家族负责路由与规划(Opus 5、Fable 5.1),Opus 4.6 负责最重的调查与执行(RCA、Executor),Sonnet 4.6 负责高吞吐工作。**安全主线**:只有 SRE 规划、只有 Executor 执行,且必过审批门 —— 见 [自动修复流水线](#自动修复流水线) 与 [端到端工作流指南](docs/WORKFLOW.md)。

模型从 Bedrock 动态获取 —— Anthropic Claude **与** OpenAI(gpt-oss / GPT-5.x)皆可;Anthropic 专属特性(prompt caching、扩展思考)按模型族自动门控。按智能体在 `config/settings.yaml` 或经 `AIOPS_AGENT_{NAME}_MODEL_ID` 覆盖。运行时可用 CLI `/model` 或 Web Settings 切换。

### 自动修复流水线

```
告警 ─► HealthIssue ─► RCA ─► SRE ─► 自动批准 (L0/L1) ─► Executor ─► 解决
                                       └► L2/L3: 人工审批
```

- **三道独立开关**:`auto_fix_enabled`(总开关)· `executor_auto_approve_l0_l1` · `executor_enabled`
- **一个问题 → 一个活跃修复方案**:草稿 = 原地更新,锁定 = 拒绝,终态 = 允许新建
- **9 态 HealthIssue 生命周期**,由状态机强制(非法转换 → 409):
  `open → investigating → acknowledged → root_cause_identified → fix_planned → fix_approved → fix_executing → fix_executed → resolved`

### 双告警入口

| 流水线 | 流向 | LLM 成本 |
|--------|------|----------|
| **Webhook** | Prometheus/CloudWatch/Datadog → `alert_processor` → HealthIssue → RCA 流水线 | 无 |
| **IM Agent** | IM 消息 → Main Agent(核实) → `create_health_issue` → 同一流水线 | 有 |

SHA-256 指纹在两条流水线间对问题去重。

### 自学习层

智能体在严格安全边界内随时间改进:

- **记忆** (`agent-memory/<agent>/*.md`) —— Hermes 风格的自优化 Markdown 记忆。智能体经 `memory_manage` 工具 `add/merge/search`;一个零 LLM 的 Curator 让未使用的记忆老化(`active→stale→archived`)且**永不删除**(可恢复)。人类撰写的记忆优先级高于智能体撰写的。构建时一次性注入(prompt-cache 安全)。
- **技能** (`skills/<name>/SKILL.md`) —— 智能体可经 `skill_manage` `add/improve/merge` 技能,但写入仅落为**草稿**。从 URL / Git 仓库 / zip 导入的技能包同样落为草稿,并盖上溯源戳(`created_by=imported`、来源、ref)。`promote_skill` 在发布前扫描**整包** —— SKILL.md 加上包内所有 `.sh`/`.py`;人类撰写的技能被**固定**,永不被自动修改。所有变更均有版本、可恢复。

完整的记忆 + 技能设计见 [`docs/MVP-1.1.0-RELEASE.md`](docs/MVP-1.1.0-RELEASE.md)。

---

## 快速开始

```bash
# 1. 安装
pip install -e .                 # 需 pgvector + Postgres 时加 ".[cloud]"

# 2. 初始化(任选其一)
aiops init                       # 交互式向导
aiops init --yes                 # 非交互本地默认
aiops init --config setup.json   # 从 JSON 零提示(模板:config/setup.json.example)
aiops quickstart --yes           # 一键:init + 启动 + 可选扫描

# 3. 启动
aiops web                        # 看板在 http://localhost:8000
#   或: aiops service start      # 后台守护进程

# 4. 对话
aiops chat                       # 交互式 REPL(30+ 斜杠命令)
aiops chat "check health of prod"            # 无头模式
aiops chat "analyze this log @/tmp/error.log"  # 带文件
aiops chat "deep dive on I#42 and check R#17"  # 带 问题/资源 引用
```

常用操作:

```bash
aiops run scan --services EC2,Lambda,RDS,S3
aiops run detect
aiops issues
aiops run analyze 1
aiops run report --type daily
```

---

## 接口

### CLI

| 命令 | 说明 |
|------|------|
| `aiops init / quickstart` | 初始化 / 一键拉起 |
| `aiops chat [QUERY] [-d LEVEL] [-f FOCUS]` | 交互或无头 AI 对话 |
| `aiops service start\|stop\|status\|logs` | 后台服务管理 |
| `aiops web [--host H] [--port P]` | 启动 Web 看板 |
| `aiops issues` / `aiops issue <id>` | 列出 / 查看健康问题 |
| `aiops get\|describe\|create\|update\|delete <entity>` | 对账号、资源、定时任务、通道的 CRUD |
| `aiops run scan\|detect\|analyze\|report\|schedule\|notify` | 运行某个流水线步骤 |

对话内斜杠命令(30+)覆盖 scan/detect/analyze/fix/approve/execute、`/model`、`/skill`、`/workflow`、`/channel`、`/send_to`、`/tokens` 等 —— 输入 `/help`。

### Web 看板

React 18 + TypeScript + Tailwind + TanStack Query,由 FastAPI 在 `http://localhost:8000` 提供。15 个页面(+ 登录):Dashboard、Chat、Issues & Plans、Issue Detail、Resource Detail、Schedules、Schedule Detail、Reports、Report Detail、Agent Metrics、Skills、Skill Detail、**Security** *(姿态评分、发现、暴露路径)*、Settings、**Galaxy** *(实验性关系图)*。

**Chat** 页支持多会话并发流式输出(后台流式、秒开)—— 见 [v1.1.1 说明](docs/MVP-1.1.1-RELEASE.md)。

### API

220+ 个 REST 端点(FastAPI 路由位于 `web/routers/`);完整 OpenAPI 在 `http://localhost:8000/docs`。主要分组:`/api/health-issues`、`/api/fix-plans`、`/api/signals`、`/api/chat/sessions`(SSE)、`/api/resources`、`/api/schedules`、`/api/skills`(+ `/api/skills/import-source`)、`/api/security`、`/api/graph`、`/api/galaxy`、`/api/messaging`、`/api/cost`、`/api/settings`、`/api/auth`。

---

## 配置

`config/settings.yaml` 是单一真源。**优先级**:`AIOPS_*` 环境变量 > `.env` > `settings.yaml` > 默认值。

| 变量 | 默认 | 说明 |
|------|------|------|
| `AIOPS_BEDROCK_MODEL_ID` | `global.anthropic.claude-sonnet-4-6` | 默认(中)档;按智能体在 `settings.yaml` 覆盖 |
| `AIOPS_BEDROCK_REGION` | `us-east-1` | Bedrock 区域 |
| `AIOPS_DATABASE_URL` | `sqlite:///…/data/agenticops.db` | 数据库 URL |
| `AIOPS_AUTO_FIX_ENABLED` | `true` | 自动修复流水线总开关 |
| `AIOPS_EXECUTOR_AUTO_APPROVE_L0_L1` | `true` | 自动批准低风险方案 |
| `AIOPS_MEMORY_AUTONOMOUS_WRITE` | `true` | 允许智能体自写记忆(草稿) |
| `AIOPS_SKILLS_AUTONOMOUS_WRITE` | `true` | 允许智能体自建技能(草稿) |
| `AIOPS_SKILLS_SECURITY_SCAN_ON_PROMOTE` | `true` | 发布前对技能做安全扫描(整包) |
| `AIOPS_SKILLS_IMPORT_ENABLED` | `true` | 允许从 URL / git / zip 导入技能包(CLI、API、Skills 页) |
| `AIOPS_SKILLS_SANDBOX_ENABLED` | `false` | 允许 executor 在无凭证、无网络的沙箱里运行已发布技能自带的脚本 |
| `AIOPS_SECURITY_REVIEW_ENABLED` | `true` | 云安全审查引擎(双频采集 + CIS 评分 + 可达性) |
| `AIOPS_DEPLOYMENT_PROFILE` | `local` | `local`(SQLite/文件)或 `cloud`(Postgres/S3) |

---

## 部署

按意图选择。每种方式运行的是*同一个*应用;区别在于基础设施 + 成熟度。

| 方式 | 意图 | 成熟度 | 后端 |
|------|------|--------|------|
| **本地 (pip)** | 开发 / 评估 | ✅ 稳定 | SQLite + 文件 |
| **Docker** | 开发 / 单容器自托管 | ✅ 稳定 | SQLite(挂卷)或 Postgres |
| **`iac/deploy-sg`**(一键) | **AWS 开发沙箱** | ✅ 已端到端跑通 | EC2 + CloudFront, ap-southeast-1 |
| **`iac/ec2` · `iac/ecs` · `iac/eks`**(Terraform) | **AWS 生产** | ⚠️ 脚手架 —— 最后验证 2026-05,未端到端测试;生产使用前请自行验证 | RDS Postgres + S3 |
| **`infra/cloud-deploy`**(CloudFormation) | 备选全栈供给 | ⚠️ 较旧(2026-03);建议优先 Terraform | RDS 或 SQLite-on-EFS |

> **开发 vs 生产:** `deploy-sg` 是**单机开发沙箱**(一台 EC2、宽权限 IAM、SQLite)—— **不要**在它上面跑生产。生产是 `ec2/ecs/eks` 的 Terraform 栈(RDS + S3、两层 IAM),但目前需你验证后再依赖。

下面每种方式都遵循同一形状:**前置条件 → 部署 → 访问 → 回滚**。

### 1. 本地 (pip) —— 开发 / 评估
```bash
# 前置条件:Python 3.12,具备 Bedrock 访问的 AWS 凭证
pip install -e .                      # 需 Postgres + pgvector 时加 ".[cloud]"
aiops quickstart --yes                # init + 启动;看板在 http://localhost:8000
# 回滚:直接停进程(aiops service stop)
```

### 2. Docker —— 开发 / 单容器自托管
```bash
# 前置条件:Docker、AWS 凭证(挂载或经环境变量)、Bedrock 访问
docker build -f docker/Dockerfile -t agenticops:latest .
docker run -d -p 8000:8000 \
  -v /data/agenticops:/app/data \
  -e AIOPS_ADMIN_PASSWORD=change-me \
  -e AIOPS_BEDROCK_REGION=us-east-1 \
  agenticops:latest
# 访问:http://localhost:8000  ·  回滚:docker stop <id>(数据保留在卷中)
```
细节 + 完整环境变量表:[`docker/README.md`](docker/README.md)。

### 3. AWS 开发沙箱 —— `iac/deploy-sg`(一键, ap-southeast-1)
CloudFront → ALB → 单台 EC2,一条命令完成供给 + 应用安装。这是已端到端跑通的路径。
```bash
# 前置条件:aws + terraform CLI,ap-southeast-1 的 AWS 凭证
cd iac/deploy-sg
./deploy.sh plan                      # 预览基础设施变更
./deploy.sh apply                     # 创建基础设施 + 安装应用(打印 cloudfront_url)
./deploy.sh redeploy [branch]         # 拉取分支 + 重建 + 重启(经 SSM);默认:main
./deploy.sh destroy                   # 拆除全部
```
- **访问:** 打印出的 `cloudfront_url`(如 `https://<id>.cloudfront.net`)始终可达。自定义 Route53 + ACM 域名可选。
- **运维提示:** 实例的公网 IP 会在 停止/启动 时变化 —— 通过**实例 ID / SSM** 运维,切勿硬编码 IP。
- **回滚:** `redeploy` 到之前的分支/tag,或 `destroy` + 重新 `apply`。

### 4. AWS 生产 —— `iac/ec2` / `iac/ecs` / `iac/eks`(Terraform) ⚠️
RDS Postgres + S3,两层 IAM(平台 + 目标账号)。**脚手架 —— 最后验证 2026-05,尚未端到端测试;生产前请在预发账号验证。**
```bash
# 前置条件:aws + terraform CLI、一个 ACM 证书、目标 VPC/子网
cd iac/ec2                            # (或 iac/ecs —— Fargate, iac/eks —— Kubernetes)
cp terraform.tfvars.example terraform.tfvars   # 编辑:region、admin_password、acm_cert_arn 等
terraform init
terraform apply -target=module.ecr -auto-approve   # 先推镜像
terraform apply -auto-approve
# 回滚:terraform destroy(或重新部署上一个镜像 tag)
```
各栈细节:[`iac/ec2/README.md`](iac/ec2/README.md) · [`iac/ecs/README.md`](iac/ecs/README.md) · [`iac/eks/README.md`](iac/eks/README.md)。

### 认证(所有 AWS 部署)
首次启动会用 **`AIOPS_ADMIN_PASSWORD`** 里的密码播种一个 `admin` 用户 —— 在暴露应用前**务必设置它**(不设时会回退到一个众所周知的默认值;任何可达部署都绝不要依赖它)。经 `POST /api/auth/login` 登录;24 小时会话令牌;长期访问用 API key;除 `/api/health` 与 `/api/auth/login` 外所有 `/api/*` 均受保护。

更多:[`docs/WORKFLOW.md#deployment`](docs/WORKFLOW.md)。

---

## 验证

在 EKS 实验室做的闭环验证(10 个故障场景 —— OOM、坏镜像、网络策略、磁盘压力、Pod pending、目标不健康、CoreDNS 宕机、PVC pending、HPA 打满、服务被删):

| 指标 | 目标 | 实测 |
|------|------|------|
| 自动修复率 | ≥ 7/10 | **10/10** |
| 检测时间 | ≤ 3 分钟 | **~2 分钟** |
| MTTR | ≤ 10 分钟 | **~6.3 分钟** |
| 每轮成本 | ≤ $3 | **~$2–3** |

---

## 项目结构

```
src/agenticops/
├── agents/       # 7 个 Strands 智能体 (main, scan, detect, rca, sre, executor, reporter)
├── tools/        # 智能体工具 (metadata, AWS CLI, web, notification, cloudwatch)
├── services/     # 流水线服务 (auto-fix, RCA + 质量门, Signal Gate, notifications, events, resolution)
├── memory/       # 自优化的文件式智能体记忆 + Curator
├── skills/       # 技能加载器, 整包安全扫描, 广域来源导入 (sources), 脚本沙箱, Curator, promote/rollback
├── security/     # 云安全审查: collectors, 纯函数 CIS 评分, 含 NACL 的可达性, fail-closed 建议器
├── graph/        # 基础设施图引擎 + SRE 算法
├── galaxy/       # Galaxy 关系图 (LLM 混合, fail-closed): rules + builder + api
├── kb/           # 知识库 (向量库: SQLite/pgvector/S3)
├── cli/          # CLI 入口 + chat + init 向导
├── web/          # FastAPI 应用 + routers/ (webhooks, schedules, skills, security, signals, …) + React SPA (frontend/)
├── chat/         # 消息预处理, 文件读取, /send_to, /channel
├── notify/  im/  # 多通道通知 + IM 机器人 (飞书/Slack)
├── integrations/ # 告警处理器, 源解析器
├── pipeline/ scheduler/ monitor/ scanner/ scan/   # 流水线, cron, 指标, 扫描
├── auth/ audit/  # JWT/API-key 认证, 审计轨迹
├── models.py     # SQLAlchemy ORM 模型
└── config.py     # Pydantic settings (AIOPS_ 环境变量前缀)

agent-memory/     # 按智能体 + 共享的 Markdown 记忆 (自优化)
skills/           # 16 个领域技能包 (+ draft/ 暂存) —— SKILL.md + references/ (+ 可选脚本)
config/           # settings.yaml, channels.yaml, im-apps.yaml, mcp-servers.json
iac/              # Terraform: ec2/, ecs/, eks/, deploy-sg/, modules/
docs/             # WORKFLOW.md, MVP 发布说明, 设计文档, use-cases
```

---

## 发布历史

最新在前。每项链接到详细说明。

| 版本 | 日期 | 亮点 |
|------|------|------|
| **[2.5.0](docs/MVP-2.5.0-RELEASE.md)** | 2026-08-31 | **云安全审查** —— 双频姿态引擎(每小时确定性快照 + 每 10 分钟 GuardDuty / Security Hub / CloudTrail 增量拉取)、**纯函数可复现的 CIS 评分**、含 NACL 的**三态可达性**、证据接地的 **fail-closed 建议器**、`/app/security` —— 在两个真实账号只读验证([E2E](docs/MVP-2.5.0-E2E-REPORT.md)) · *2026-09-08 追加:* **技能广域加载**(URL / git / zip → 草稿,整包安全扫描)、**脚本沙箱**(无凭证、无网络,默认关)、Skills 页**导入器**与溯源、`web/routers/` 拆分 |
| **[2.2.1](docs/MVP-2.2.1-RELEASE.md)** | 2026-07-27 | **Effort / thinking 策略** —— 后端对高严重级别与重跑的 RCA 自动升档扩展思考预算;按对话会话覆盖 effort(`off … max`,NULL = Auto) |
| **[2.2.0](docs/MVP-2.2.0-RELEASE.md)** | 2026-07-21 | **Signal Gate** 降噪 —— 所有建问题路径过同一道可审计的门(fingerprint-v2、抖动、冷却、合并;LLM 灰区裁判只合并不丢弃) · **RCA 质量五件套**(证据检查 → critic → 置信度门 → 事件记忆 → 看门狗) · 在 [L1](docs/MVP-2.2.0-CHAOS-E2E-REPORT.md) / [L2](docs/MVP-2.2.1-CHAOS-L2-E2E-REPORT.md) 混沌报告中实地验证 |
| **[2.0.1](docs/MVP-2.0.1-RELEASE.md)** | 2026-07-08 | 前端交互大改 —— Chat 编辑器**按会话切模型** · **富对话**(建议 chips + `I#` 原地定位) · **导航侧栏 2.0** · **看板 2.0** · **Strands 1.45**(`context_manager="auto"` + 可选 executor **HITL**) · **Galaxy** *(实验性)* —— LLM 混合的全清单关系图,含 fail-closed 校验 + Canvas 星云 UI |
| **[2.0.0](docs/MVP-2.0.0-RELEASE.md)** | 2026-06-19 | 受治理的自主(策略引擎) · ITSM 桥接 · 多云能力层(SSH/Prometheus/Kubernetes providers) · 自我改进指标 · 预防三件套(SPOF 巡检 + RCA 拓扑 + 模拟门) · **账号寻址凭证**(修掉 ContextVar 错号缺陷;显式账号解析、fail-closed、SSM→SSH 访问阶梯) · SES/SMTP 通知器 key 映射修复 |
| **[1.1.1](docs/MVP-1.1.1-RELEASE.md)** | 2026-06-02 | 并发对话会话 + 秒开;粘贴/拖拽多附件;open-webui 风格对话 UI 刷新;智能体窗口配置修复(Full Context + Web→YAML 持久化);统一 **Messaging** 设置(合并 Notifications + IM Bots) |
| **[1.1.0](docs/MVP-1.1.0-RELEASE.md)** | 2026-05-31 | 自主**智能体记忆**(自优化,Hermes 风格)+ 自主**技能**(智能体创建,安全门禁发布) |
| **[1.0.1](docs/MVP-1.0.1-RELEASE.md)** | 2026-05-27 | 加载器/交互加固;技能索引召回改进 |
| **[1.0.0](docs/MVP-1.0.0-RELEASE.md)** | 2026-03-10 | 首个 MVP —— 7 智能体架构、自动修复流水线、Web 看板、10/10 验证 |

面向用户、含 Mermaid 图的工作流指南:[`docs/WORKFLOW.md`](docs/WORKFLOW.md)。代码库健康审计 + 闭环工程路线图:[`docs/AUDIT-2026-06.md`](docs/AUDIT-2026-06.md)。完整文档地图 —— 持续维护的文档与带日期的历史快照之分,以及双语(README / README_CN)维护规则:[`docs/README.md`](docs/README.md)。

---

## 开发

```bash
pip install -e ".[dev]"

pytest tests/ -q                              # 全量:4,300+ 用例,约 2 分钟
python3 -m py_compile src/agenticops/web/app.py   # 后端语法检查
cd src/agenticops/web/frontend && npx tsc --noEmit && npm run build   # 前端
uvicorn agenticops.web.app:app --reload --port 8000   # 开发 API 服务器
```

## 许可证

MIT
