/* new-UI-face — sample data. Everything here is invented for the prototype.
   Times: the prototype's "now" is 06:20 UTC (14:20 in Beijing); `h` = hours before now, `waitMin` = minutes waited.
   Text fields are plain strings (zh) or {zh, en}; NF.tx() picks the language. English sample text comes in D7. */
(function(){
"use strict";
const NF = window.NF = window.NF || {};

NF.seed = {
  nowMin: 6 * 60 + 20,                       // 06:20 UTC
  user: {name: "malibo", initials: "MA"},
  accounts: [
    {id: "prod", name: {zh: "生产账户", en: "Production"}},
    {id: "data", name: {zh: "数据账户", en: "Data"}},
  ],

  /* One row per thing that waits on a person. `kind` picks the brief (NF.briefs); `reason` is the attention
     reason the backend already returns (services/attention.py); `situation` is its finer case. */
  items: [
    { id: "I12", ref: "I#12", entity: "issue", kind: "approve", situation: "awaitingApproval", reason: "approval_required",
      severity: "critical", tone: "crit", waitMin: 128, account: "prod", region: "us-east-1", node: "sg_web",
      title: "安全组 sg_web 把 SSH（22 端口）开给了整个公网",
      cause: { text: "今天 03:52 UTC，部署流水线用的角色给 sg_web 加了一条 0.0.0.0/0 的入站规则，之后没有收回。",
               ev: ["E1", "E2", "E3", "E4"], self: 0.92, critic: "supported", location: "verified" },
      plan: { label: "修复方案", version: 2, hash: "3fa9c1d2", risk: "L2", effect: "approve_and_run",
              steps: [
                {say: "收回 22 端口对公网的那条规则", cmd: "aws ec2 revoke-security-group-ingress --group-id sg-0a41… --protocol tcp --port 22 --cidr 0.0.0.0/0", tier: "write"},
                {say: "确认堡垒机网段的规则还在", cmd: "aws ec2 describe-security-groups --group-ids sg-0a41…", tier: "read"},
                {say: "从堡垒机连一次 web-1", cmd: "ssm: nc -zv web-1 22", tier: "read"}],
              rollback: "把原规则加回去。回滚不会中断现有连接。" },
      impact: { deps: ["web-1", "web-2", "web-3", "bastion"], structural: 4, potential: 9, observed: 0 },
      checks: ["22 端口不再对公网开放", "堡垒机仍能连上 web-1", "30 分钟内没有新的告警"] },

    { id: "C3", ref: "C#3", entity: "change", kind: "approve", situation: "awaitingApproval", reason: "approval_required",
      risk: "L1", tone: "info", waitMin: 300, account: "prod", region: "ap-southeast-1", node: "web-asg",
      requester: "alice",
      title: "给 web 集群的 6 台机器补上 Project 标签",
      cause: { text: "alice 提的变更。agent 审过了：只加标签，不改任何运行中的配置。", ev: ["E3"],
               self: null, critic: "review_passed", location: "found_all" },
      plan: { label: "实施方案", version: 1, hash: "8c20be71", risk: "L1", effect: "approve_and_run",
              steps: [
                {say: "给 6 台实例加 Project=storefront", cmd: "aws ec2 create-tags --resources i-0f07… (6) --tags Key=Project,Value=storefront", tier: "write"},
                {say: "确认标签都在", cmd: "aws ec2 describe-tags --filters Name=key,Values=Project", tier: "read"}],
              rollback: "删掉这个标签。" },
      impact: { deps: ["web-asg"], structural: 1, potential: 1, observed: 0 },
      checks: ["6 台实例都有 Project 标签"] },

    { id: "I8", ref: "I#8", entity: "issue", kind: "approve", situation: "awaitingApproval", reason: "approval_required",
      severity: "high", tone: "warn", waitMin: 1090, account: "data", region: "cn-northwest-1", node: "database-demo",
      title: "database-demo 的自动备份被关掉了",
      cause: { text: "昨天 12:10 UTC，john 把备份保留期从 7 天改成了 0。没有对应的变更单。", ev: ["E5"],
               self: 0.88, critic: "supported", location: "verified" },
      plan: { label: "修复方案", version: 1, hash: "b41f09aa", risk: "L1", effect: "approve_and_run",
              steps: [
                {say: "把备份保留期改回 7 天", cmd: "aws rds modify-db-instance --db-instance-identifier database-demo --backup-retention-period 7 --apply-immediately", tier: "write"},
                {say: "确认已生效", cmd: "aws rds describe-db-instances --db-instance-identifier database-demo", tier: "read"}],
              rollback: "改回 0（不建议）。" },
      impact: { deps: ["orders-api", "report-job"], structural: 2, potential: 3, observed: 0 },
      checks: ["BackupRetentionPeriod = 7", "下一个备份窗口有快照"] },

    { id: "I934", ref: "I#934", entity: "issue", kind: "accept", situation: "awaitingAcceptance", reason: "verification_required",
      severity: "medium", tone: "warn", waitMin: 40, account: "data", region: "cn-northwest-1", node: "aurora-main",
      title: "Aurora 和 ALB 的告警已经建好，有两项检查要你看一眼",
      ran: { run: 37, steps: 3, duration: "2 分 41 秒", plan: "修复方案 v1", hash: "d48806a4", matches: true },
      autoChecks: [ {pc: "pc-1", t: "4 个 Aurora 实例各有 CPU 和连接数告警"}, {pc: "pc-2", t: "2 个 ALB 各有 5xx 告警"} ],
      needChecks: [ {pc: "pc-5", t: "端到端通知测试：收到了，但延迟 94 秒", why: "warning"},
                    {pc: "pc-6", t: "把问题状态改为已解决", why: "no_result"} ],
      ev: ["E6"] },

    { id: "I21", ref: "I#21", entity: "issue", kind: "confirm", situation: "needsReview", reason: "review_required",
      severity: "medium", tone: "warn", waitMin: 180, account: "prod", region: "us-east-1", node: "ecs-orders",
      title: "orders-svc 频繁重启：agent 认为是内存上限太小，但把握不够",
      cause: { text: "14 次停止里有 9 次是内存超限。agent 推断内存上限（512 MB）在流量高峰时不够用，但没有找到流量上升的直接证据。",
               ev: ["E7"], self: 0.58, critic: "weak", location: "verified" },
      gate: 0.6 },
  ],

  evidence: {
    E1: { title: "CloudTrail：谁改了规则", code: true, src: "fetched",
          body: '{\n  "eventTime": "2026-11-10T03:52:11Z",\n  "eventName": "AuthorizeSecurityGroupIngress",\n  "userIdentity": { "arn": "arn:aws:sts::…:assumed-role/deploy-role/ci-4412" },\n  "requestParameters": {\n    "groupId": "sg-0a41…",\n    "ipPermissions": [{ "fromPort": 22, "toPort": 22, "cidrIp": "0.0.0.0/0" }]\n  }\n}' },
    E2: { title: "安全组当前的入站规则", code: true, src: "fetched",
          body: "sg-0a41… (sg_web)\n  tcp 443   0.0.0.0/0        ← 原有\n  tcp 22    10.20.0.0/24     ← 原有（堡垒机）\n  tcp 22    0.0.0.0/0        ← 03:52 UTC 新增" },
    E3: { title: "哪些资源挂着这个安全组", code: true, src: "graph_rule",
          body: "sg_web ──attached_to──▶ web-1, web-2, web-3, bastion\n依赖这 4 台机器的还有 5 个资源（ALB 目标组、2 个定时任务…）" },
    E4: { title: "诊断的推理过程", code: false, src: "model",
          body: "部署流水线在 03:52 UTC 发布 web 服务时，脚本为了调试临时打开了 22 端口，\n发布结束后没有执行收回的那一步。——这是模型根据 E1 的时间和 ci-4412 的日志推断的，\n没有直接的记录证明「为了调试」。" },
    E5: { title: "RDS 参数变更记录", code: true, src: "fetched",
          body: "ModifyDBInstance  database-demo\n  BackupRetentionPeriod: 7 → 0\n  by: user/john   at 2026-11-09 12:10 UTC" },
    E6: { title: "执行 #37 的检查结果", code: true, src: "checked",
          body: "pc-1  4 个 Aurora 实例各有 CPU / 连接数告警     通过\npc-2  2 个 ALB 各有 5xx 告警                    通过\npc-5  端到端通知测试                              警告：收到了，但延迟 94 秒\npc-6  把问题状态改为已解决                         没有结果（这一步不该由执行器做）" },
    E7: { title: "ECS 任务停止原因", code: true, src: "fetched",
          body: "orders-svc 最近 14 次停止：\n  OutOfMemoryError: Container killed due to memory usage   ×9\n  Essential container exited (exit 137)                     ×5" },
  },

  /* What agents are doing right now (the «现场» lens). `act` = an action the agent took, `find` = a fact the code
     fetched; neither = the model's own inference. */
  runs: [
    { id: "r1", title: "诊断 I#37　lambda-pay 错误率升高", state: "run", stateKey: "live.investigating", steer: true, steps: [
        {t: "取这个函数周围的关系和最近的变更", c: "get_topology_evidence(I#37)", act: true},
        {t: "05:55 UTC 起错误率从 0.2% 升到 7.4%", c: "cloudwatch get-metric-data", find: true},
        {t: "05:52 UTC 有一次发布：pay-fn 版本 41 → 42", c: "cloudtrail lookup-events", find: true},
        {t: "在看版本 42 改了什么……", c: "lambda get-function --qualifier 42", act: true}],
      more: [
        {t: "版本 42 把超时从 30 秒改成了 3 秒", c: "diff 41..42", find: true},
        {t: "下游 orders-api 的 p95 是 4.1 秒，超过新的超时", c: "cloudwatch get-metric-data", find: true},
        {t: "推断：超时改成 3 秒后，调下游的请求全部超时。把握 86%", c: "save_rca_result"}] },
    { id: "r2", title: "扫描 us-east-1 的资源", state: "run", stateText: "62%", steps: [
        {t: "已列完 EC2、RDS、ELB；正在列 EKS", c: "scan", act: true}] },
    { id: "r3", title: "I#40 的修复方案草稿", state: "wait", stateKey: "live.inPolicy", steps: [
        {t: "3 步里有 1 步分类不了，不会自动批准，会来问你", c: "unclassified_command", find: true}] },
    { id: "r4", title: "执行 I#31", state: "done", stateKey: "live.doneAgo", agoMin: 12, steps: [
        {t: "3 项检查由代码逐项核对，全部通过", c: "verification: passed", find: true}] },
  ],

  /* The last 24 hours (the pulse strip and the «全景» list). k: signal | agent | decision | change */
  events: [
    {h: 18.17, k: "signal", t: "database-demo 的自动备份被关闭"},
    {h: 17.0, k: "agent", t: "扫描完成：1,623 个资源"},
    {h: 10.3, k: "agent", t: "每日巡检完成"},
    {h: 4.8, k: "signal", t: "orders-svc 任务重启 14 次"},
    {h: 2.47, k: "change", t: "deploy-role 改了 sg_web 的入站规则", cause: true},
    {h: 2.4, k: "signal", t: "sg_web 的 22 端口对公网开放"},
    {h: 2.3, k: "agent", t: "I#12 诊断完成"},
    {h: 2.2, k: "decision", t: "I#12 的方案在等你批准"},
    {h: 0.7, k: "agent", t: "I#934 执行完成"},
    {h: 0.65, k: "decision", t: "I#934 在等你验收"},
    {h: 0.42, k: "signal", t: "lambda-pay 错误率升高"},
    {h: 0.4, k: "agent", t: "开始诊断 I#37"},
  ],

  /* The starfield: clusters of resources and the named ones that have something open.
     from / to = the hours-ago interval in which the resource is not normal. */
  clusters: [
    {name: "生产　us-east-1", cx: -.52, cy: -.22, n: 132, sp: .2},
    {name: "生产　ap-southeast-1", cx: .5, cy: -.34, n: 96, sp: .17},
    {name: "数据　cn-northwest-1", cx: .42, cy: .42, n: 84, sp: .16},
    {name: "EKS chaos-lab", cx: -.44, cy: .48, n: 72, sp: .15},
    {name: "公共与边缘", cx: 0, cy: .04, n: 40, sp: .12},
  ],
  hot: [
    {name: "sg_web", cl: 0, from: 2.4, to: 0, tone: "red", ref: "I12"},
    {name: "database-demo", cl: 2, from: 18.17, to: 0, tone: "amber", ref: "I8"},
    {name: "aurora-main", cl: 2, from: 30, to: 0.7, tone: "amber", ref: "I934"},
    {name: "ecs-orders", cl: 0, from: 4.8, to: 0, tone: "amber", ref: "I21"},
    {name: "lambda-pay", cl: 1, from: 0.42, to: 0, tone: "mint", ref: "I37"},
    {name: "web-asg", cl: 1, from: 5, to: 0, tone: "violet", ref: "C3"},
  ],
  watch: { resources: 1623, lastScanMin: 12 },
};
})();
