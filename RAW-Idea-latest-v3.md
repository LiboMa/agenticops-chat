
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
        * 接收 CLI 指令。
        * 读取 Metadata 了解当前系统状态。
        * 派发任务给其他 Agent。
    Compute_use: local command line, aws cli, OS cli

2. 子 Scan Agent
    Desciption: 用于主动抓取特账号上的选定的资源,
    Tool_use: 动态的确定需要涵盖的范围（可以调用与之相关的MCP/Skills/Tool）
    Output: 更新 Metadata 中的 Inventory 字段。
3. 子 Detect Agent 
    Description: 对于已经获取的资源列表，并已确认激活接管的资源，Detect会使用工具、Skills、可是SDK直接进行健康检查，也包括 Log、Metrics、Trace 从Cloudwatch里来。被动优先，主动为辅： Detect Agent 首先应该检查 CloudWatch Alarms (报警状态)，只有在报警触发或主 Agent 明确要求“深查”某个资源时，才去拉取详细的 Logs 和 Metrics。不要做“全量实时轮询”。进行问题检测，汇聚成一定的Pattern, 保存到Knowledge Base中去
    Tool_use: 动态的确定需要涵盖的范围（可以调用与之相关的MCP/Skills/Tool）
    Action:
        Input: 读取 Metadata Inventory。
        Action: 检查 CloudWatch Alarms -> (若异常) -> Pull Metrics。
        Output: 更新 Metadata Health_Issues 列表。

3. 子 RCA Agent 
    Usage: 用于根因分析，根据业界主流方法论，扫描到的问题进行分类、定位、定级、以级鼓掌修复建议。定位问题后，落进Knowledge Base中的Paterrn，形成排查手册，通过通用的排查手册+模型本身的能力不断的进行精准定位。落进Knowledge base时，Markdown KB 必须包含具体的 SOP (标准作业程序)，例如“RDS CPU 100% 排查步骤”。
    Tool_use: 动态的确定需要涵盖的范围（可以调用与之相关的MCP/Skills/Tool）
    Action:
        Input: 读取 Metadata Health_Issues + 读取 Markdown KB (SOP)。
        Action: 分析根因。
        Output: 生成 Root_Cause_Report 和 Fix_Plan。
4. 安全相关的Agent（后续任务）
    Usage: {LLM}可针对安全事件、CVE、Runtime、CloudUpgrade 的总结
5. SRE-agent(完成设计，第二期做) 
    Description: 故障修复，前期只生成流程化的修复建议和报告,后期自动修复
    Tool_use: AWS CLI, AWS Docs terraform, cloudformation, code-development. 可以调用与之相关的MCP/Skills/Tool）
    Input: 读取 Fix_Plan。
    Action: Wait for User Approval via CLI -> Execute Remediation
6.  Reporter Agent
    Usage: 用于将RCA与Dtect Agent的实时内容，总结，定期给出Daily/hourly 的更新,先存在本地，定期进行的任务 - 为了日后完成数据飞轮进行，同时将报告构成，Structured Case Study (结构化案例)，并自动将其**向量化（Embedding）**存入 Knowledge Base。
    故障结束后，Reporter Agent 启动。它的任务不是“记流水账”，而是扮演**“资深复盘专家”。它使用 LLM 对上述 Raw Context 进行重写，提取出通用的模式 (Pattern)**。

去噪： 去掉具体的 Instance ID (如 i-12345)，替换为抽象资源类型 (如 EC2_Instance).

总结： 将复杂的命令交互总结为标准步骤。
    Tool_use: web-search、Grounding、research，
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

### 学术支持
AIOpsLab

### Reference
**Conversation Memory** :https://gemini.google.com/app/77634e03aaa26f05 

AIOPS *L1-L5* Definion 分级模型来描述：

| 级别 | 描述 | 你的设计 |
|------|------|----------|
| L1 | 告警转发（原样推送） | ❌ 不是这个 |
| L2 | 智能摘要（降噪+聚合+优先级） | ✅ Detect Agent |
| L3 | 根因定位 + 修复建议 | ✅ RCA Agent |
| L4 | 人工确认后自动执行修复 | ✅ SRE Agent（你的设计） |
| L5 | 完全自主修复 | ❌ 你明确不做这个 |


L3-L4 之间就是你的甜蜜点。 这也是目前企业客户最能接受的边界——"你告诉我问题在哪、怎么修，我来按按钮"。


### 最终理想的效果是：
AgenticAgent可以自主接管服务，像Ops界的自动驾驶
当遇到问题时，我会收到报警，之后并告知：故障已解决！
这种感觉岂不是很舒爽？

内容示例： “检测到 RDS CPU 异常（Z=4.5）。关联服务：支付网关。推测原因：慢 SQL 激增。建议操作：查杀 Session ID 1042。”


### F&Q 

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
