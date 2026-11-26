/* new-UI-face — D4 sample data: things that no longer wait (to be found again by search), conversations, and the
   notices of the last hours. Everything here is invented. Sample text is zh; its English comes in D7.
   `past` items keep their own status (the queue only lists what waits); `chats` are conversations already had. */
(function(){
"use strict";
const S = window.NF.seed;
/* Things that are done with — or not yet anyone's to decide. A search finds them; their «经过» page opens.
   Written out whole (not copied from a waiting item), so each record agrees with its own title. */
S.past = [
  { id: "I9", ref: "I#9", entity: "issue", kind: "confirm", situation: "needsReview", reason: "review_required", status: "closed",
    severity: "low", tone: "info", waitMin: 0, account: "data", region: "cn-northwest-1", signals: 1,
    title: "数据账户里有 2 个没有绑定的弹性 IP", myReason: "测试账户里的地址，保留到月底。", closedH: 29.4,
    found: {h: 30, by: "scan", t: "扫描发现 2 个弹性 IP 没有绑定任何实例。"}, at: {rca: 29.8},
    cause: {text: "这两个地址 10 月起就没有绑定过实例，都在测试用的 VPC 里，每月各收一点费用。", ev: [], self: 0.9, critic: "supported", location: "verified"} },
  { id: "I5", ref: "I#5", entity: "issue", kind: "resolve", situation: "passed", reason: "verification_required", status: "fixed", endState: "resolved",
    severity: "medium", tone: "warn", waitMin: 0, account: "prod", region: "ap-southeast-1", signals: 2,
    title: "web-1 的 /tmp 使用率 95%",
    found: {h: 9, by: "alarm", t: "告警：web-1 的 /tmp 使用率 95%。"}, at: {rca: 8.9, plan: 8.8, approve: 8.7, run: 8.6},
    cause: {text: "一个打包任务每次运行都把 2 GB 的中间文件留在 /tmp，没有清理。", ev: [], self: 0.86, critic: "supported", location: "verified"},
    ran: {run: 41, steps: 2, duration: "21 秒", plan: "修复方案 v1", hash: "5d1e0c3a", matches: true} },
  { id: "C2", ref: "C#2", entity: "change", kind: "approve", situation: "awaitingApproval", reason: "approval_required", status: "closed",
    risk: "L1", tone: "info", waitMin: 0, account: "prod", region: "ap-southeast-1", requester: "bob",
    title: "给 web 集群加一个 Owner 标签", myReason: "和 C#3 重复。", closedH: 6.7,
    found: {h: 7, by: "bob", t: "bob 提了这张变更单。"}, at: {rca: 6.9},
    cause: {text: "bob 提的变更：给 web 集群的机器加 Owner 标签。审核时发现 C#3 已经在补同一批机器的标签。", ev: [], self: null, critic: "review_passed", location: "found_all"} },
  { id: "I37", ref: "I#37", entity: "issue", kind: "confirm", situation: "needsReview", reason: "review_required", status: "handed", agentState: "investigating",
    severity: "high", tone: "warn", waitMin: 0, account: "prod", region: "us-east-1", signals: 6,
    title: "lambda-pay 错误率升高", found: {h: 0.4, by: "alarm", t: "告警：lambda-pay 的错误率超过 5%。"} },
  { id: "I63", ref: "I#63", entity: "issue", kind: "confirm", situation: "needsReview", reason: "review_required", status: "handed", agentState: "fix_planned",
    severity: "medium", tone: "warn", waitMin: 0, account: "data", region: "cn-northwest-1", signals: 3,
    title: "report-job 的磁盘写满", found: {h: 0.6, by: "alarm", t: "告警：report-job 所在节点的磁盘写满。"}, at: {rca: 0.5},
    cause: {text: "report-job 的临时目录 /data/tmp 没有清理，节点的数据盘用满了。", ev: [], self: 0.81, critic: "supported", location: "verified"} },
];

/* Reports and plans the search can name (their pages are D5). */
S.reports = [
  {id: "R31", title: "每日运行报告 · 11 月 25 日", h: 23.3, status: "ready"},
  {id: "R30", title: "安全复盘 · 第 47 周", h: 70, status: "ready"},
];

/* A step of the work log: find = a fact the code fetched (◆), act = something the agent did (▸), neither = the
   model's own words (◇). `ms` = how long the step took. */
S.chats = [
  { id: "c1", pinned: true, h: 1.8, title: "sg_web 是谁改的", ctx: {ref: "I#12", account: "prod"}, model: "Opus 5.5", effort: "standard",
    turns: [{ q: "sg_web 的 22 端口是谁、什么时候打开的？", h: 1.8, secs: 41,
      work: [
        {t: "读 I#12 的诊断和证据", c: "get_health_issue(I#12)", act: true, ms: 900, r: "I#12 严重 · 根因已找到 · 证据 E1–E3 · 方案 v2 等批准"},
        {t: "03:52 UTC deploy-role 调了 AuthorizeSecurityGroupIngress", c: "cloudtrail lookup-events --event-name AuthorizeSecurityGroupIngress", find: true, ms: 11200,
         r: "1 条事件 · 03:52:07 UTC · 调用方 deploy-role · sg-0a41… · 0.0.0.0/0 tcp 22"},
        {t: "03:56 UTC 扫描发现 22 端口对 0.0.0.0/0 开放", c: "get_rca_result(I#12)", find: true, ms: 700},
        {t: "这条规则之后没有被收回", c: "ec2 describe-security-groups --group-ids sg-0a41…", find: true, ms: 2100, r: "IpPermissions: tcp 22 ← 0.0.0.0/0（还在）"},
        {t: "推断：流水线调试时加的规则，忘了收回", c: ""}],
      answer: { text: "是部署流水线用的角色 deploy-role 在今天 03:52 UTC 加的：一条 0.0.0.0/0 的 22 端口入站规则，之后没有收回。时间和调用方有两条直接的记录（E1、E2）；「为了调试」是我推断的，没有记录能证明。",
        table: {head: ["时间 (UTC)", "发生了什么", "证据"], rows: [["03:52", "deploy-role 加了规则", "E1"], ["03:56", "扫描发现 22 端口对公网开放", "E2"], ["04:04", "诊断完成，出了方案 v2", "—"]]},
        flow: {nodes: ["deploy-role", "sg_web", "web-1", "web-2", "web-3"], edges: [[0, 1, "改了规则"], [1, 2, ""], [1, 3, ""], [1, 4, ""]]} },
      suggest: ["把 E1 给我看", "打开 I#12", "这个角色还改过别的吗？"] }] },
  { id: "c2", h: 5.1, title: "过去 24 小时按级别", model: "Opus 5.5", effort: "standard",
    turns: [{ q: "过去 24 小时的问题按级别数一下", h: 5.1, secs: 9,
      work: [
        {t: "列出过去 24 小时的问题", c: "list_health_issues(status=, limit=200)", act: true, ms: 1300},
        {t: "按级别数：严重 2、高 5、中 6、低 3", c: "count by severity", find: true, ms: 200}],
      answer: { text: "过去 24 小时一共 16 件，其中 2 件严重。数字是代码数的，不是我数的。",
        chart: {kind: "bar", x: ["严重", "高", "中", "低"], series: [{name: "件数", data: [2, 5, 6, 3]}]},
        table: {head: ["级别", "件数", "还在等你"], rows: [["严重", "2", "2"], ["高", "5", "3"], ["中", "6", "1"], ["低", "3", "0"]]} },
      suggest: ["只看严重的", "和上周比呢？"] }] },
  { id: "c3", h: 22, title: "这张截图里是哪台机器", model: "Opus 5.5", effort: "standard",
    turns: [{ q: "这张截图里报警的是哪台机器？顺便看看附的日志。", h: 22, secs: 18,
      files: [
        {name: "grafana-0603.png", kind: "image", size: "412 KB", delivery: "native"},
        {name: "web-2-syslog.txt", kind: "text", size: "88 KB", delivery: "text"}],     // a refused file never leaves the composer (it is refused at upload)
      work: [
        {t: "读截图：web-2 的 /var 使用率曲线", c: "(图片，模型直接读)", ms: 3100},
        {t: "读日志：02:10 UTC 起 /var/log/app 每小时涨 1.4 GB", c: "web-2-syslog.txt", find: true, ms: 800},
        {t: "web-2 在资源表里是 i-0b7…，属于生产账户", c: "get_managed_resources(name=web-2)", find: true, ms: 600}],
      answer: { text: "截图里报警的是 web-2（生产账户，i-0b7…）。附的日志说明 /var/log/app 从 02:10 UTC 起每小时涨 1.4 GB——这就是 I#58 后来清理的那批日志。" },
      suggest: ["打开 I#58", "把这台机器在全景里给我看"] }] },
  { id: "c4", h: 30, title: "把所有账户的 IAM 都审一遍", model: "Fable 5.2", effort: "max",
    turns: [{ q: "把所有账户的 IAM 都审一遍，列出能删的角色", h: 30, error: "timeout",
      work: [{t: "列出两个账户的 IAM 角色", c: "list_managed_resources(type=IAMRole)", act: true, ms: 2400}] }] },
];

/* The notices of the last hours (hours before now). The history also keeps every notice the page shows from here on. */
S.notices = [
  {h: 0.3, key: "notice.agentDone", vars: {ref: "I#58"}, go: "I58"},
  {h: 1.1, key: "notice.approvedBy", vars: {ref: "I#934", who: "bob"}, go: "I934"},
  {h: 2.4, key: "notice.newCritical", vars: {ref: "I#12"}, go: "I12"},
  {h: 5.2, key: "notice.newChange", vars: {ref: "C#3", who: "alice"}, go: "C3"},
];
})();
