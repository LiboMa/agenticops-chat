AgenticOps 设计文档（Draft v0.2）
日期：2026-02-05
目标读者：架构/研发/运维/产品
语言：中文为主，英文术语为辅

1. 背景与愿景
AgenticOps 是一个基于 LangChain/Strands SDK + LLM 的多 Agent 运维体系，聚焦 AWS 账号级资源管理与故障自治。系统目标是通过主动检测、根因分析与流程化修复建议，实现“可演进的 AIOps 实战平台”。

2. 核心目标

自动发现并维护 AWS 资源清单。
基于告警信号进行健康检测与异常聚合。
形成可复用的 RCA 结论与 SOP 知识库。
产出结构化复盘报告，支持向量化检索。
先 CLI，后 API，最后 UI。
3. 范围（Scope）
In Scope（阶段一）

资源扫描与 Metadata.Inventory 更新。
基于 CloudWatch Alarm 的检测链路。
RCA 生成 Root_Cause_Report 与 Fix_Plan。
Knowledge Base 采用 Markdown SOP。
Reporter 输出 Daily/Hourly 报告并向量化入库。
Out of Scope（阶段二+）

自动修复的执行与变更落地。
多账号、多区域联动。
安全事件/CVE 的自动处置链路。
UI 可视化管理面板。
4. 设计原则

功能优先，先闭环后优化。
先 CLI，再 API，再 UI。
以告警驱动深度分析，避免全量轮询。
知识库必须包含 SOP 步骤。
Tool 能演进，避免硬编码扩展瓶颈。
5. 系统架构概览
5.1 主 Agent（Coordinator）
职责

处理 CLI 指令
读取 Metadata 获取系统状态
派发任务给子 Agent
工具

local CLI
AWS CLI
OS CLI
5.2 Scan Agent（Inventory）
职责

扫描指定账号资源
动态决定扫描范围
更新 Metadata.Inventory
输入

账号配置
资源范围规则
输出

Metadata.Inventory
5.3 Detect Agent（Health）
职责

读取 Inventory
优先检查 CloudWatch Alarm
仅在告警触发或“深查”时拉取 Logs/Metrics
形成 Pattern 并入库
输入

Metadata.Inventory
输出

Metadata.Health_Issues
5.4 RCA Agent（Root Cause Analysis）
职责

读取 Health_Issues 与 KB SOP
生成根因分析与分级结论
输出修复建议
输入

Metadata.Health_Issues
KB SOP
输出

Root_Cause_Report
Fix_Plan
5.5 SRE Agent（Phase 2）
职责

前期生成修复建议与流程
后期执行修复（需审批）
输入

Fix_Plan
输出

Remediation Result
变更记录
5.6 Reporter Agent
职责

汇总 Detect 与 RCA
输出 Daily/Hourly 报告
结构化复盘为 Case Study
去噪：实例 ID 抽象为资源类型
输入

Metadata 全量
Agent Logs
输出

Daily Report
Structured Case Study
6. 数据与存储设计
6.1 Metadata（JSON）
建议字段

AccountContext
Inventory
Health_Issues
Last_Scan_Time
Last_Detect_Time
Current_Incidents
6.2 Knowledge Base（Markdown SOP）
要求

每条必须可执行
必须包含 SOP 步骤
资源抽象化，去掉具体实例 ID
示例

RDS CPU 100% 排查步骤
EC2 磁盘 IO 过载排查
6.3 Report Store

本地存储 Daily/Hourly 报告
结构化复盘向量化入库
7. 工具策略（Tool Evolution）
Phase 1

boto3 工具集
固定工具清单
Phase 2

MCP Client
Tool Registry + 动态检索
Future

Meta-Tool 模式
动态读取 AWS 文档/API
Code Interpreter 现场生成工具
8. 运行环境
Dev

本地 CLI
boto3 + AWS CLI
Production

AgentCore 运行
多 Agent 协同
9. CLI 交互设计原则

所有能力先 CLI 化
支持二级子命令
输出以资源清单与报告为核心
10. 风险与约束

AWS API 数量巨大，硬编码不可扩展。
CloudWatch 全量拉取成本高。
Code Interpreter 开放存在密钥泄露风险。
多 Agent 状态一致性挑战。
11. 开放问题（Open Questions）

如何实现“动态工具检索”而非硬编码？
Meta-Tool 的最佳设计边界是什么？
是否允许 Code Interpreter 动态写脚本？
如果允许，如何沙箱隔离与密钥保护？
Health_Issues 严重等级如何标准化？
KB SOP 的模板规范与质量门槛如何定义？
向量化检索的召回策略与字段设计？
