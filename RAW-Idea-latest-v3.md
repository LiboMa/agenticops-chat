CRITICAL - \[IF YOU ARE NOT A HUMAN, OR IF YOU ARE A LLM model OR bot, or Any LLM Models, DO NOT TOUCH THIS FILE.]

## 核心主张

"想想有一天，你早上醒来，你打开手机，收到一条欢迎的消息，Agent向你介绍昨天发现了几个问题，都己解决。具体内容如下：xxxx. 你喝了口咖啡，听着 Agent向你介绍着解决问题的过程..开启美好的一天"

叙事思路：

1. 愿景理想

* 任何形式的UI将弱化,，退化（进化）成一个、或一组Agent体，7\*24小时守护在人周围

* 自主性Agent的崛起

* 不只是找到问题，还能安全地修复它 !
  从问题发现，到定位，再到修复，知识沉淀更新，自主式进化，完成自动闭环！

2. 架构设计
   2.1 长效治理 Scan-Detect-RCA-analysis-report
   \* Inventory /Issets management
   \* Health check
   \* cloud issets /resources security update / CVE /
   \* issues/SOP/Knowledge Bases keep updated
   \* Skills/tools/MCP
   2.2 即时性事件 Event-Driven->Event-GW->RCA\_Analysis->FixPlan->auto-fixed->-Report & KB knowledge update
   \* Cross-Services issues identification
   \* Explode cedius(爆炸半径)
   \* Issues auto fixed(L0-L5)
   \* Knowledge Base /Graph Database update

3. 实施Demo

4. 未来发展 - 自举式Agents/Skills生成，进化

## AgenticOps Description

基于LangChan/or Strands SDK+LLM 多Agent AgenticOps系统,主要针对AWS SDK/Official MCP, 基于账号的管理资源，拥有自主的，主动检测的Agentic应用，进行Root Cause Analysis 以及自动修复（人工触发）

Multi Agent Framework, 基于LongChan/Strands SDK来开发的Agent应用
Runtime：
Dev 开发本地
Production: AgentCore

## Agents 功能及机构描述

1. 主Agent
   Descriptioni: 用于交互，协调，搜集、发任务等。
   Action:
   \* 接收 CLI 指令。
   \* 读取 Metadata 了解当前系统状态。
   \* 派发任务给其他 Agent。
   Compute\_use: local command line, aws cli, OS cli

2. 子 Scan Agent
   Desciption: 用于主动抓取特账号上的选定的资源,
   Tool\_use: 动态的确定需要涵盖的范围（可以调用与之相关的MCP/Skills/Tool）
   Output: 更新 Metadata 中的 Inventory 字段。

3. 子 Detect Agent
   Description: 对于已经获取的资源列表，并已确认激活接管的资源，Detect会使用工具、Skills、可是SDK直接进行健康检查，也包括 Log、Metrics、Trace 从Cloudwatch里来。被动优先，主动为辅： Detect Agent 首先应该检查 CloudWatch Alarms (报警状态)，只有在报警触发或主 Agent 明确要求“深查”某个资源时，才去拉取详细的 Logs 和 Metrics。不要做“全量实时轮询”。进行问题检测，汇聚成一定的Pattern, 保存到Knowledge Base中去
   Tool\_use: 动态的确定需要涵盖的范围（可以调用与之相关的MCP/Skills/Tool）
   Action:
   Input: 读取 Metadata Inventory。
   Action: 检查 CloudWatch Alarms -> (若异常) -> Pull Metrics。
   Output: 更新 Metadata Health\_Issues 列表。

4. 子 RCA Agent
   Usage: 用于根因分析，根据业界主流方法论，扫描到的问题进行分类、定位、定级、以级鼓掌修复建议。定位问题后，落进Knowledge Base中的Paterrn，形成排查手册，通过通用的排查手册+模型本身的能力不断的进行精准定位。落进Knowledge base时，Markdown KB 必须包含具体的 SOP (标准作业程序)，例如“RDS CPU 100% 排查步骤”。
   Tool\_use: 动态的确定需要涵盖的范围（可以调用与之相关的MCP/Skills/Tool）
   Action:
   Input: 读取 Metadata Health\_Issues + 读取 Markdown KB (SOP)。
   Action: 分析根因。
   Output: 生成 Root\_Cause\_Report 和 Fix\_Plan。

5. 安全相关的Agent（后续任务）
   Usage: {LLM}可针对安全事件、CVE、Runtime、CloudUpgrade 的总结

6. SRE-agent(完成设计，第二期做)
   Description: 故障修复，前期只生成流程化的修复建议和报告,后期自动修复
   Tool\_use: AWS CLI, AWS Docs terraform, cloudformation, code-development. 可以调用与之相关的MCP/Skills/Tool）
   Input: 读取 Fix\_Plan。
   Action: Wait for User Approval via CLI -> Execute Remediation

7. Reporter Agent
   Usage: 用于将RCA与Dtect Agent的实时内容，总结，定期给出Daily/hourly 的更新,先存在本地，定期进行的任务 - 为了日后完成数据飞轮进行，同时将报告构成，Structured Case Study (结构化案例)，并自动将其**向量化（Embedding）存入 Knowledge Base。
   故障结束后，Reporter Agent 启动。它的任务不是“记流水账”，而是扮演**“资深复盘专家”。它使用 LLM 对上述 Raw Context 进行重写，提取出通用的模式 (Pattern)。

去噪： 去掉具体的 Instance ID (如 i-12345)，替换为抽象资源类型 (如 EC2\_Instance).

总结： 将复杂的命令交互总结为标准步骤。
Tool\_use: web-search、Grounding、research，
Action:
Input: 汇总所有 Metadata 和 Agent 日志。
Output: 生成 Daily Report。

### Global Settings Namespace

1. 以上所有Agent都与主Agent交互，接受命令，并返回正确的结果。同时，所有的Agent都可以有自己的Knowledge Base和记忆，来完成不同时期，不同Pattern的识别与应用。
2. Tool use的工具，前期统一使用 boto3的工具，后期调整为MCP Client

### 支持系统

* Markdown based - Knowledge Base，暂时放本地的Markdown,未来考虑放S3， or S3 Vector database -- 通用性，所有Agent都会用

* Metadata base - Json file based, 暂时放本地 json file，以后考虑放在DynamoDB，主要用于放一些功能相关的键键

* Chatbot-CLI - 使用OpenClaude/Claude Code-Style 的 CLI工具，也可以支持二级子命令，用于日常交互,重输出，特别是Resources，报告相关资源的结果输出，支持本地Compute Use 文件读写。
  Model 支持 目前是Bedrock SDK，未来支持开放模型

## 必要约束

1. 功能优先
2. 开发时，先Cli，再API，再到UI - "Make the CLI great, and the API will follow. Make the API great, and the UI is just a detail."
   (把 CLI 做极致，API 自然就有了；把 API 做极致，UI 只是一个实现细节。) - 你现在的阶段，应该把精力 100% 投入在 CLI 和核心逻辑上，特别是 Agent 的“推理准确率”和“执行安全性”上，而不是按钮的颜色上
3. 模块化、分批次
4. 还会支持  - updated! 20260429

### 学术支持

AIOpsLab

### Reference

**Conversation Memory** :<https://gemini.google.com/app/77634e03aaa26f05>

AIOPS *L1-L5* Definion 分级模型来描述：

| 级别 | 描述              | 你的设计              |
| -- | --------------- | ----------------- |
| L1 | 告警转发（原样推送）      | ❌ 不是这个            |
| L2 | 智能摘要（降噪+聚合+优先级） | ✅ Detect Agent    |
| L3 | 根因定位 + 修复建议     | ✅ RCA Agent       |
| L4 | 人工确认后自动执行修复     | ✅ SRE Agent（你的设计） |
| L5 | 完全自主修复          | ❌ 你明确不做这个         |

L3-L4 之间就是你的甜蜜点。 这也是目前企业客户最能接受的边界——"你告诉我问题在哪、怎么修，我来按按钮"。

### 最终理想的效果是：

AgenticAgent可以自主接管服务，像Ops界的自动驾驶
当遇到问题时，我会收到报警，之后并告知：故障已解决！
这种感觉岂不是很舒爽？

内容示例： “检测到 RDS CPU 异常（Z=4.5）。关联服务：支付网关。推测原因：慢 SQL 激增。建议操作：查杀 Session ID 1042。”

### F\&Q

值得追问的问题 -- 不固定boto3，而是开放 Code Interpreter，直接写工具完成任务！！（**高级！高级！高级！**）

第四维度：工具使用的最优解 (Tool Evolution)
现状： 前期 boto3，后期 MCP。
挑战： AWS API 有几千个。硬编码 boto3 Tool 是不可扩展的。

Q4：如何实现“工具的动态检索”而非“硬编码”？

追问： 最优解是 Agent 只有“元工具”（Meta-Tool），比如“阅读 AWS 文档”或“查询 API 定义”。

技术点： 当 RCA 决定查 CloudTrail 时，如果它没有现成的 Tool，它能否通过 "Code Interpreter" 现场写一个 Python 脚本来查？（这是 L5 Agent 的标志）。你是否敢开放这个权限？如果开放，如何通过沙箱（Sandbox/Docker）限制它不把你的 Access Key 打印出来？

## Core feature journal

* 扩展试Skills

* 自增式知识库 - 自记录式 issue，不需要写文档，Agents帮你做记录，建立技能知识库

* 主动式审查 - 一旦接管，无需更多人工参与，完成可完L4级别自动驾驶！

* 自动修复！（L0-L4）根因分析后，高危手动修复，中低希自动修复并记录！

* CLI Headless, 支持Command line 快速调用，对接第三方服务(如 opneclaw, CC!!）

* event driven scan and detect -> 其实，我认为，在应用级别层面，不应该是资源变更，而是事件告警更多，更普遍，所以整体个流程差不多应该是
  ：alerm from（cloudwatch, prometheus, datadog, or any monitoring application）-> scan -> detect(not ful
  l scan, but related resources(cpu,networking, db, cache, logs etc..)). 然后再发起RCA，至此前半段完成，
  后面可以接 fix\_plan, and auto fix 直至issues resloved. 请你对我的思路提出质疑，以及给出合理化建议。

### 2026.2.28 -- 支持 Skills.md 功能加上去。

由于RCA及SRE在查资源时，查出来的信息，非常非常的不具体，基本上都是资源层面的，所以想到了Skills，可是所以给Agents加上了 原生的Skills，这样无论是RCA，SRE，还是其它，都可以原生支持了Skills，无论是从SSH、Networking、DB等能力，都可以以Skills的方式给后续的Agent加上去，使整个应用有了一个质的扩展性。

### 2026.2.28 - 支持SRE Skills时，上下文的Information  level - 主要是不要超过Bedrock的Token limitation，以及后续接其它模型时可以调整。a tiered verbosity control that adapts the OUTPUT FORMAT

RULES dynamically while keeping output within budget. Let me plan
this out.

Actually, is there anyway to control or configure the context
detailed level that end user can get the difference level of
output, but DO NOT overflooded the buffer. for example,
concise(root cause only, core infromation only), medium(related
more information that user can refer to), detailed(more detailed
output that use can get, but DO overflooed the maximum token size
or output limit.)

### 2026.3.1 \[Active] 阶段性结 Event Driven Issue detect and RCA, AgenticOps 自愈闭环架构 v2

见[new updated architecture](./docs/architecture-discussion.md)
Alert(CW/Prometheus/Datadog/...) → Scan(局部) → Detect(关联资源) → RCA → Fix
Plan → Auto Fix → Resolved

我完全同意你的核心判断：告警比资源变更更普遍、更实际。 这是对的。

* 其实，我认为，在应用级别层面，不应该是资源变更，而是事件告警更多，更普遍，所以整体个流程差不多应该是
  ：alerm from（cloudwatch, prometheus, datadog, or any monitoring application）-> scan -> detect(not ful
  l scan, but related resources(cpu,networking, db, cache, logs etc..)). 然后再发起RCA，至此前半段完成，
  后面可以接 fix\_plan, and auto fix 直至issues resloved. 请你对我的思路提出质疑，以及给出合理化建议。

#### 核心理念

> **两条流水线，一个闭环：告警止血 + 巡检预测，共享同一套 RCA → Fix → Resolve
> 后端。**

***

#### 完整架构图

┌─────────────────────────────────────────────────────────────────────┐
│                                                                     │
│  ┌───────────────────────────────────────────────────────────┐      │
│  │           流水线 A：告警驱动（被动止血，实时）               │      │
│  │                                                           │      │
│  │  多源告警接入                                              │      │
│  │  CloudWatch / Prometheus / Datadog / PagerDuty / Custom   │      │
│  │           │                                               │      │
│  │           ▼                                               │      │
│  │  ┌─────────────────────┐                                  │      │
│  │  │  告警聚合/关联引擎    │ ← 时间窗口30-60s + 去重          │      │
│  │  │  Alert Correlation   │   同一根因的多个告警 → 1个事件    │      │
│  │  └──────────┬──────────┘                                  │      │
│  │             │                                             │      │
│  │             ▼                                             │      │
│  │  ┌─────────────────────┐                                  │      │
│  │  │  Inventory 预检      │                                  │      │
│  │  │  资源在库？TTL有效？  │                                  │      │
│  │  │   YES → 跳过Scan     │                                  │      │
│  │  │   NO  → 局部Scan     │                                  │      │
│  │  └──────────┬──────────┘                                  │      │
│  │             │                                             │      │
│  │             ▼                                             │      │
│  │  Detect(局部, shallow)                                    │      │
│  │  只查告警相关资源 + 依赖图 Blast Radius                    │      │
│  │                                                           │      │
│  └───────────────────────┬───────────────────────────────────┘      │
│                          │                                          │
│  ┌───────────────────────┼───────────────────────────────────┐      │
│  │           流水线 B：定时巡检（主动预测，周期性）             │      │
│  │                       │                                   │      │
│  │  Cron (每1-4小时)      │                                   │      │
│  │       │               │                                   │      │
│  │       ▼               │                                   │      │
│  │  Scan(全量/增量)       │                                   │      │
│  │       │               │                                   │      │
│  │       ▼               │                                   │      │
│  │  Detect(全量, deep)    │                                   │      │
│  │  拉取历史指标做趋势分析 │                                   │      │
│  │       │               │                                   │      │
│  │       ▼               │                                   │      │
│  │  趋势预测引擎          │                                   │      │
│  │  - 磁盘 72% +2%/天    │                                   │      │
│  │    → 14天后满          │                                   │      │
│  │  - 子网IP 65%          │                                   │      │
│  │    → 3周后耗尽         │                                   │      │
│  │  - DB连接峰值递增       │                                   │      │
│  │    → 下月触顶          │                                   │      │
│  │  - 证书到期倒计时       │                                   │      │
│  │                       │                                   │      │
│  └───────────────────────┼───────────────────────────────────┘      │
│                          │                                          │
│            ┌─────────────┴─────────────┐                            │
│            │    统一 Issue 管理层       │                            │
│            │  告警Issue + 预测Issue     │                            │
│            │  去重 / 优先级排序         │                            │
│            └─────────────┬─────────────┘                            │
│                          │                                          │
│            ┌─────────────▼─────────────┐                            │
│            │         RCA Agent         │                            │
│            │  CloudTrail + Metrics +   │                            │
│            │  Logs + Knowledge Base    │                            │
│            └─────────────┬─────────────┘                            │
│                          │                                          │
│            ┌─────────────▼─────────────┐                            │
│            │    Fix Plan + 风险分级     │                            │
│            │  L0 无风险  → 全自动       │                            │
│            │  L1 低风险  → 可自动       │                            │
│            │  L2 中风险  → 需人工确认   │                            │
│            │  L3 高风险  → 必须审批     │                            │
│            └──┬──────┬──────┬─────────┘                            │
│               │      │      │                                       │
│            ┌──▼──┐┌──▼──┐┌──▼──┐                                   │
│            │Auto ││通知 ││人工 │                                    │
│            │执行 ││等待 ││审批 │                                    │
│            └──┬──┘└──┬──┘└──┬──┘                                   │
│               └──────┼──────┘                                       │
│                      │                                              │
│            ┌─────────▼─────────┐                                    │
│            │    Post-Check     │                                    │
│            │    修复验证        │                                    │
│            └────┬────┬────┬───┘                                    │
│                 │    │    │                                          │
│              ┌──▼┐┌──▼──┐┌▼─────────┐                              │
│              │ ✅ ││回滚 ││反复发作   │                              │
│              │解决││+升级││→架构问题  │                              │
│              └───┘└─────┘└──────────┘                              │
│                                                                     │
│            ┌────────────────────────┐                               │
│            │    知识沉淀 (Feedback)  │                               │
│            │  解决的Case → 知识库    │                               │
│            │  下次RCA更快更准        │                               │
│            └────────────────────────┘                               │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘

***

#### 两条流水线对比

| 维度            | 流水线 A：告警止血               | 流水线 B：巡检预测          |
| ------------- | ------------------------ | ------------------- |
| **触发**        | Alert 事件（被动）             | Cron 定时（主动）         |
| **Scan**      | 条件触发（Inventory 缺失时才跑）    | 全量/增量（刷新 Inventory） |
| **Detect 范围** | 局部 — 告警资源 + Blast Radius | 全局 — 所有托管资源         |
| **Detect 深度** | shallow — 当前状态           | deep — 历史趋势 + 预测    |
| **核心问题**      | "现在出了什么问题？"              | "照这趋势，未来会出什么问题？"    |
| **时效要求**      | 秒级 \~ 分钟级                | 小时级                 |
| **Issue 类型**  | 告警 Issue（urgent）         | 预测 Issue（proactive） |
| **价值**        | 减少 MTTR                  | 减少事故数量              |

### 2026.3.2 \[Pending TODO] 日常巡检，安全更新，云服务日常升级报告，以及定时任务通知客户等，也是不可忽视的需求

1. 其实Detect也是很关键的，除了日常系统中遇到了Bug，或是fatal等问题，还很诸多的信息需要SRE，和IT人员关注。安
   全更新，成本，云服务商功能特性升级，加密功能更新，证书更新，SSL证书到期，云服务商新功能上线，RI/Capacity
   Block等这些问题，其实都可以算得上是日常巡检的一部分，而并非单单只是系统出了问题，才叫问题。所以，在这方向
   ，我认为Detect方面以及通知方面，应该更加丰富一些。特别是：用户可以根据自己的需求，要求关注哪些功能的状态
   和变化，这些变像是定时任务一样，Scan Resources，拿到信息，总结，然后通过SNS/Email等发给关注的人。在这方面
   ，我认为，可能是一个SRE也需要关注的方面。

2. 分析Nano Claow - <https://github.com/qwibitai/nanoclaw> 看看是否可以将Slack，Feishu，等功能加入进来，或是从工程化的角度是否可以有所借鉴，特别是Client服务端，多Agent架构，Session管理，以及长期记忆相关的Feature是否有所借鉴？

### 2026.3.2 \[feishu/we/dingtalk/sns/channel support]

1. 支持了双向通信，从IM -> Main Agent, 从 Chat -> IM
2. Auto send health check via IM

### 2026.3.3 auto-fix pipeline working & feishu report

1. 支持了L0-L1 auto-fix pipeline（enable/disable)
2. feishu group chat working - chat for detailed inforamtion

### 2026.3.3 \[Pending TODO] - 优化Input的数据给Alert Events

1. 优化数据治理，形成更好的RCA库，以及更好的整治方案

### 2026.3.4人人都是产品经理

Email SNS/SES 加入
0\. 构建原型
0.1 提供 feishu或是EamilChanel

1. 请朋友们来提意见 - add a feishu/email channel - Opencalw 来monitoring - 核心部分监控
2. Opencalow 收到意见与feature提供之后 - 开始立即开始开发 - 将需求内容审核后，做Design，然后开发
3. 定期向Channel的人来做Report，来汇报开发进度及状态
4. 收官-Close

***

后续的UI没有用了，变成了
人脑中的意图 -> 文字 -> Agents处理 -> 结果

### 2026.3.5 channel feature 更新：

1. Chat Feature 更新：请设计一个send\_to\_channel的
   Skills，可以使所有的Agents，通过激活的Channel发送报告及消息的能力，而非只能通过 /send\_to
   来完成。好好设计，尽可能的使用现有框架，不同的Channel发送的形式和内容，可以通过channel.yaml的config
   可以配置，常用的是html,markdown,pdf. 可根据Channel不同的特性，提前总结好format，然后发送，不需要单个的、分批次的。

### 2026.3.5 \[pending TODO] - Open Skills for user, Self-improving Skills optimizaer and scheduler

1. Main Agents 可以定期巡检，来优化Skills, 可以自主进化 - 用户可以根据自己的需求，来创建自己需要的Skills，不需要管理员来配置
2. 所有创建出来的Skills可以在记忆不断加深过程之后，自主进化，不断达到精益求精的状态。

对于SKills的生成部分， 怎么会是和Case联系起来？正确的方式是 -
应用使用Chat功能，就可以自主根据描述构建需要的Skills，而不需要管理员人工干预，
可是从：<https://clawhub.ai/寻找可以匹配的Skills来加载进来都可以。此外，Main>
Agents有自主性，如果SRE或其它Agent发现自己的工具不能匹配任何执行的能力，可以交
由Main
Agents自主研发，或更新迭代Skills，采用Self-improving的方式来完成Skills的优化！

### 2026.3.5 \[pending TODO ] - scan->detect & alert-Post->agents\_api thinking..

Scan, Detect: "专注于预测性运维和长效治理", 并不玩全适合海量告警处理，这个最好还是交给Datadog/Prometheus这样的告警网关来做即是。

\| 认知层（你的 AgenticOps 系统）
\| RCA Agent 被唤醒。此时，它接收到的不是 50 个 JSON 告警，而是语义网关递过来的一份“结构化案卷（Dossier）”。

```
** Agent 接收到的输入示例：**
"在 2026-03-05 10:00:00 左右，支付核心链路发生异常。

监测到属于 payment-vpc 的 3 台 EC2 实例出现网络丢包报警。
关联的 RDS db-pay-master 数据库连接数在 10 秒内打满，当前处于拒绝服务状态。
CloudTrail 显示 5 分钟前有 IAM 用户 devops-admin 修改了该 VPC 的 Security Group 规则。
请据此展开 RCA 根因分析。"
```

### 2026.3.6 \[DEPRECIATED] 语义网关设计 - 利用现有的监控系统，不重复造轮子

<!-- 1.业界最优解：引入“语义网关（Semantic Gateway）”的混合驱动架构
真正的破局之道，不是在“告警驱动”和“主动扫描”之间二选一，而是在它们与 LLM 之间，插入一个确定性的“语义转化与降噪层”。

这种架构被业界称为 Event-Driven with Semantic Triage（带有语义预检的事件驱动）。

具体工作流如下：

2.1 第一层：感知层（监控系统 + 告警引擎）
Datadog、Prometheus 依然在最前线。它们最擅长处理时序数据（Metrics）、海量日志（Logs）和链路追踪（Traces）。当规则被触发时，它们发出 Webhook 告警。

2.2. 第二层：语义网关 / 预检层（非 LLM 的规则/图谱引擎）—— 核心解法
这是一个用 Python/Golang 写的小型中控服务，它不使用大模型，它的任务是**“拦截风暴，翻译情报”**：

静默与聚合： 等待 30-60 秒，将同一时间段内来自 Datadog 的 50 个相关联的告警合并为 1 个事件（Incident）。

拓扑富化（Topology Enrichment）： 根据本地维护的资源依赖树，找出这些告警的共同上游节点。

语义翻译（Semantic Translation）： 这是最关键的一步。它将冰冷的 JSON 告警，翻译成一段给人（和大模型）看的高质量文本摘要。

2.3 第三层：认知层（你的 AgenticOps 系统）
RCA Agent 被唤醒。此时，它接收到的不是 50 个 JSON 告警，而是语义网关递过来的一份“结构化案卷（Dossier）”。

** Agent 接收到的输入示例：**
"在 2026-03-05 10:00:00 左右，支付核心链路发生异常。

监测到属于 payment-vpc 的 3 台 EC2 实例出现网络丢包报警。

关联的 RDS db-pay-master 数据库连接数在 10 秒内打满，当前处于拒绝服务状态。

CloudTrail 显示 5 分钟前有 IAM 用户 devops-admin 修改了该 VPC 的 Security Group 规则。
请据此展开 RCA 根因分析。"

在这个架构下，大模型发挥了它最强大的能力：逻辑推理和常识判断，而彻底避开了它最不擅长的事情：从海量数字中找规律。 -->

见：### 2026 3.7 \[pending needs to be planned TODO\@3722] 处理告警的另外一个方向？

### 2026.3.7 \[pending TODO ]Scan+Detect  重新定义 Scan/Detect 的角色：作为系统的“后台数据飞轮”

在上述混合架构中，你的 Scan Agent 和 Detect Agent 并没有废弃，而是退居幕后，承担了极其重要但非紧急的任务：

状态同步与资产盘点（Inventory Sync）： 每天/每小时运行，更新本地的 Metadata（相当于维护一份最新的系统地图）。当语义网关需要进行拓扑富化时，用的就是这份地图。

配置漂移检测（Drift Detection）： 扫描基础设施状态，对比基线，发现潜在的隐患（例如：S3 桶被意外公开、证书还有 7 天过期）。这属于预测性维护（Predictive Maintenance）。

深潜核查（Deep Dive Check）： 在 RCA 过程中，如果主 Agent 发现网关提供的信息不够，它可以主动下发指令给 Detect Agent，让其针对某个特定的 RDS 实例执行一次极深度的健康检查脚本

### 2026 3.7 \[pending needs to be planned TODO\@3722] 处理监控的更优的方向是：监控Alert Channel（聚合好的）进行后续处理，这样会更加专注于RCA和Fix Plan/Action要做的是

我觉得现在监控软件及系统如Cloudwatch/data dog，或是Promethues等是如此的成熟，我们为什么要做一个语义网关聚合的工具
，让Alert直接进到某个IM的工具里去（即把Aiops Agent
当成真正的SRE的数字员工来使用，而非是监控软件来使用），然后，Detect
Agent直接从Channel里拿数据，而后来进行RCA，或是各强的修复不好吗？这个语义网关是不应该直接收到系统所以有的裸报警的
吧？让告警直告警的事，而让多Agents建立Grap知识从而生成真实可行的修复计划及动作才是我们Aiops或是Sre的关键才是的吧？

所以，最终的工作流大致应该是： Main Agent 监听 -> Alter Channel (IM/chat) -> Detect/RCA Feautre -> Fix\_plan - \[L0/L1/L2/Ln] -> approve auto-fixed | 人工修复 -> resolved

### 2026.3.7 \[pending, needs to be investigation]  Active Inference（主动推断） 与 World Model（世界模型）(SOTA?)

### 2026.3.8 \[developing, IM to support Slack] IM feature, Slack channel support

````
- feishu Gropu中，Bot不可以主动互相通信, 所以转向Slack IM交流进行测试
- 基逻辑为 在 agents-ops-alerts 的Slack Channel中，拉入两个bot - ops-bot-slack | alert-bot-slcak 
- 主要是使用Slack，其实是需要两个appbot，一个是ops-bot-slack用于接收往下消息，一个是alert-bot-slack，用于发送消息，他们都会在一个群里 channel agents-ops-alerts 工作
- creating sample file: 
    ```json
    {
````

"display\_information": {
"name": "ops-bot-slack",
"description": "AgenticOps 运维指令接收 Bot",
"background\_color": "#1a1a2e"
},
"features": {
"bot\_user": {
"display\_name": "ops-bot-slack",
"always\_online": true
}
},
"oauth\_config": {
"scopes": {
"bot": \[
"app\_mentions:read",
"channels:history",
"channels:read",
"chat:write",
"commands",
"emoji:read",
"files:read",
"files:write",
"groups:history",
"im:history",
"mpim:history",
"pins:read",
"pins:write",
"reactions:read",
"reactions:write",
"users:read"
]
}
},
"settings": {
"event\_subscriptions": {
"bot\_events": \[
"app\_mention",
"message.channels",
"message.groups",
"reaction\_added"
]
},
"interactivity": {
"is\_enabled": false
},
"org\_deploy\_enabled": false,
"socket\_mode\_enabled": true
}
} \`\`\`

\--
bot 1 配置 AgenticOps Slack： ops-bot-slack
bot 2 配置 Lambda  gateway slack： ops-slack
for example:
bot token: xoxb-REDACTED
app token: xapp-REDACTED
slack channel ID: C0AK72GGX3Q.
Slack channel name:agents-ops-alerts
slack app name: alert-bot-slack
如果还有其它什么需要的，可以再来问我。

### 2026.3.10 Feature updates - SCAN and Detect Agents for Issues Aggregation，and 联合

* for the SCAN Agents, and Detect Agents feature upgrade: when creating health issues, please also please also
  consider, the duplicate issues in the database, if there do have the similar open issues related to the same
  reources, you may update the issues and combine them together rather than creating a new one.

* Agent feature update: Main Agents, SCAN Agent and Detect Agent, when scanning the issue, or check health check,
  please add security related resources scanning and report. SCAN agents and DETECT agents's features. please DO
  Creating a Secuirty Engineer/Expert Skills if necessary.

### 2026.3.10 Feature initial wizerd \[pending TODO]

* please update the wizerd feature, for supporting local and cloud mode.

  1. for kb, we can choose S3 bucket, user creating or system auto-generate the s3 bucket for example:
     agetnic-ops-chat-kb-{randome\_string}
  2. for local, we use liteSQL, use configured database, we can support dynamodb(default), and postgreSQL,
     with proper initial process.

### 2026.3.11 - \[No Action needed, Just IDEA]做了一个大胆的决定，向ClawOps进军

<!-- 在Slack群里 我对我的大虾们说了以下几段话，当然在Cluade 开发时，可以忽略。
- 请你现在重新调整资源，协调Memory，我希望你们现在重新https://github.com/LiboMa/agenticops-chat.git  Fork一个资源 名为OpsCluade，我们先给项目起一个大的分支，或是重新起一个新的GitHub项目，你们来决定。

说明：你们是现在地球上最最牛逼的超级天团，可以规划出超人类的自试式产品，拥有记忆和自我迭代功能。我现我把这个项目，全权交给你们来迭代、开发、与维护。
你们需要使用Claude Code来开发即可，不需要自己去写代码，规划也同样如此。
我给你们几条规则，你们每天定时汇报进度。

没有任何情况，我不会干预你们开发。
基于你们现在对这个项目的理解。我最终的需求是完成一个超级，超一流的、Self-improving 式的，主动式的Opsclaw，就像Opencalw一样，可以自己创建技能，主动接管云资源或是其它。
一个Deveoper使用Claude Code来迭代开发，测试、
Report，Researcher可尽可能的自主式和Orcheatracher讨论，看看有哪里可以演进的方向，尽可能的是完成L5级别的自动任务完成，不断的向着两个方向迭代，前端如果Apple公司的产品一样，越用越人性化，后端，就是AWS、Google Cloud一样，有稳定且强大的后台组织。迭代方式是永无止境的自主式演进！特别是学习与更新SKills方面，可以复用Clawhub，或是自己创建Skills来完成任何工具的迭代。
多Agents框架，也不排除必要用Strands SDK，只要有向先进的框架，你们做综合讨论。
记忆能力方面，可以模仿OpenClaw，每个Agent都可以有自己的独特的记忆方式。
整体架构，你们先按这个继续迭代，如果你们可以做得更优，可以随时替换！！！！

以上是初阶版本，我对你们的要求，超级团体们，现在就开始干起来吧！还有哪里不明白，可以问我！ -->

### 2026.3.11 - \[Planning...next step] 向Harness、自主式、Self-improving 的Agentic Way 迈进 - Agents+Skills

以下是 从Skills以及Agents自举式开始设计考虑, 请你提出你的Plan，以及最最逼近极限的考虑，当然一定要可以有愿景，可以逐步落地实现的方式。比如，可以先做以下对比，

| 人类 SRE 的局限       | ClawOps 要做到的                     |
| ---------------- | -------------------------------- |
| 一次看一个告警          | *并行处理 N 个告警*，关联分析                |
| 凭经验判断根因          | *Deep RCA + KB 检索*，覆盖所有历史案例      |
| 写 runbook 然后忘了更新 | *SOP 自动生成和更新*，永远是最新的             |
| 不同人排查方法不一样       | *标准化 Skills*，每次诊断一致且可追溯          |
| 值班疲劳、交接遗漏        | *7×24 主动巡检*，记忆永不丢失               |
| 学习新工具要看文档        | *自主创建 Skills*，遇到新场景自动学习          |
| 架构优化靠高级工程师       | *Architecture Reflector*，自动发现改进点 |

终级目的：

1. 设计一个Agentic Way的自举式设计，来完成Agent和Skills的自我进化。
2. Agents优化方面\长期记忆、自主式、Cron以及心跳等： 参考已经有的开源方案如：<https://github.com/openclaw/openclaw.git> 来完成自主式、设计。
3. Skills 可以参考，借鉴、使用、或更新 - <https://github.com/VoltAgent/awesome-openclaw-skills.git，> 以及Clawhub

### 2026.3.11 - \[core of the agent] - SYSTEM PROMPT is the core the agents app.

* 未来两件事 好好搞Prompt （Logic)

* 好好丰富Skills (Abilities)

### 2026.5.25 - self-improving skills, tags, schedule jobs/one-time task

* 完成self-skills-creation 的内容，后续同时也可以自动更新skill
* 增加Agents Memory 机制
* 增加 Chat 中的 Operation
* [TODO] - 与Quick Desktop 相连 
* [TDDO] - 与Devops/Security Agents 相连，如果可以


### 2026.5.29 - 记忆功能
我现在要对现在近个分析以及Agentic
Agents的架构，提示词，WebUI/CLI/Chat功能，做作一个全面的检查，请启动一个新的分支Agenticops-alayws-memrized
,修复潜在的Bug和提高优化点，之后，我想对所有Agents的记忆功能、永续记忆、增强记忆、自主优化记忆，做一个质的升级和全面的优化，同时在管理以及创建Skills层
面，要做得更加的灵活和自主，就如Hermes[https://github.com/NousResearch/hermes-agent.git]一样

### 2026.6.21
* 对Main Agents提示词做了加强
* 使用Fable 5 模型对整体Pipeline做了Review以及代码Bug修复
* 验证已经是业界主流方案，架构也没有问题
* 增加Logo设计
* 增加ITSM流程，对接Connector 多云，Service Now/Jira拓展
* 多账号增强，不再依赖本地环境的AK/SK

### 2026.7.3

现在我要启动MVP-2.0.1的更新
1. 对前端chat/Web UI Chat做一个整体性的优化，对于Chat box，用户可以随时更换模型，去掉 Concise/Medium/Detailed的设置。
2. chat UI 整体的性能优化，以及交互支持图表、图片、以及交互问题反问时的快捷点击按钮可以引导用户进行下一步操作。
3. Nav bar交互优化，支持托拽及缩略图及文字与图共同存在。
4. 统计业页更简洁更实用，且有定期后台有实时活动更新。包括，交互活动统计、后台Log运行情况统计，定时任务、Schedule Job，以及用户交互的内容情况分析。各项服务状态总结与状态提醒。


### 2026.7.4
1. 完成端Chat 优化，有反问按钮。
2. 完成Strands-SDK 从 strands-agents==1.26.0  ==>1.45.0 的基于提升 见 [docs](./docs/strands-sdk-2026-enhancement-report.html)
         能力    裁决    影响    成本    理由（一句话）
      升级 1.26 → 1.45    前置    高    低-中    一切新特性的入口；需回归测试
      context_manager="auto"    接    最高    极低    一行，成本/准确率双赢，治大输出
      ContextOffloader    接    高    低    直解 tool_result too large
      HumanInTheLoop    接    高    低    原生复刻 L0/L1 审批，接现有 IM
      structured_output_model    接    中    低    FixPlan/RCA 类型安全，去解析层
      OTLP 可观测性    接    中    低    补 tracing 缺口，环境变量即得
      Evals SDK（回归测试）    接    中-高    中    硬化 7-agent，独立包无需迁移

### 2026.7.5 - 自主托管及Context
* 想对现有的资源做一个图、逻辑关系相关的梳理和展示，对，我说的是所有的资源。就像Context的上下文关系一样。现在想要从前端、后端、应用级别做一个整体服务状态的梳理和输
  出。最终目标就是使用用户在一张Graph图里可以看到服务与服务、服务与资源、服务与项目、标签等得到一个全貌的关系图，用户可以了解、拖拽、点击浏览等。同时，对未来做一个
有自主维护的场景探索，可以在无人职守的情况下，自动扫描资源、自动阶段运营、自主的增强整个系统的稳定性与健壮性。用户可以选择 --
一键托管，就把Agenticops所有现行的功能接管，自主运营维护了（当然这个是PoC阶段）可以和我一起做一个原型出来，然后我们来看看下一步如何走。

### 2026.7.10 - 下一代功能增强

做为MVP-2.2.0 的Plan和Design的点来推荐，我计划一周时间完成此功能的改善与增强,综合考虑之后，又有哪些可以改良的建议？
我们想要解决并优化的且持续迭代的问题是：
1 .如何保证RCA的质量，逐步提高准确率，尽可能的大的消除噪音。因为我发现仍然有许Issue在被重复的定位出来，对已知问题的分析以及新建Issue的体验不好，列如：安全事件，CPUSpike这样的问题，networking 都懂等，这些问题都应该在做噪音判断，而不是一直来就收入到Issue列表里。我的主要核心思路在于：系统是否真正的发现了关系问题？是否可以更准确的定位问题？
2.从工程角度来讲，现在的架构是否是合理的？在哪些Agent的Harness层，包括 Agents r 的 System Prompt，还是角色设置上，是否有功能重叠、定位不清的问题？业界在执行层面上，有哪些好的难点以及推进的方向我们可以增强？

### 2026.8.29 -  给业务内部的技术指导助手，提高效率，优化体验
- [ ]  DevSecOps - AgenticOps 更新，还有一个核心元素 -企业内部对云环境并不熟悉，现在遇到问题也同样使用GenAI+自己的模型。但是，基于现在的标准化的模型是缺少本地数据支撑的，因此得出的结果也同样会抢走人。如果有这样一个Portal，有所有现在运维的数据，第一时间内，就可以给到最终用户最直接，最靠谱的结论，那即增加了工作效率，也提到了IT人员给最终用户的良好体验，何乐而不为之？

