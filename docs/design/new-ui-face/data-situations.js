/* new-UI-face — sample data, part 2 (D2): the other attention situations, what an item becomes after an agent
   has worked on it (`next`, `acceptAfter`), and the facts the story page shows (`found`, `at`).
   With data.js the 16 items cover all 15 situations of services/attention.py (10 for issues, 5 for changes). */
(function(){
"use strict";
const NF = window.NF, S = NF.seed, item = id => S.items.find(i => i.id === id);
const W = "write", R = "read";

S.items.push(
  { id: "I31", ref: "I#31", entity: "issue", kind: "failed", situation: "needsNewPlan", reason: "execution_failed",
    severity: "high", tone: "warn", waitMin: 55, account: "prod", region: "us-east-1", node: "orders-api",
    title: "扩容 orders-api 的执行失败了，已经回滚",
    lastRun: { id: 41, plan: "修复方案 v1", hash: "7c1d44e0", duration: "11 分 08 秒", failedAt: 2,
      steps: [
        {say: "把期望任务数从 2 改成 4", cmd: "aws ecs update-service --cluster prod --service orders-api --desired-count 4", tier: W, status: "ok"},
        {say: "等 4 个任务都通过健康检查", cmd: "aws ecs wait services-stable --cluster prod --services orders-api", tier: R, status: "bad",
         error: "10 分钟内只有 2 个任务健康：新任务拉不到镜像（CannotPullContainerError）。"},
        {say: "确认错误率回落", cmd: "cloudwatch get-metric-data …", tier: R, status: "skip"}],
      rollback: "已把期望任务数改回 2。现在 2 个任务都健康。" },
    cause: { text: "流量高峰时 2 个任务的 CPU 持续在 90% 以上，agent 判断是容量不够。", ev: ["E8", "E9"], self: 0.83, critic: "supported", location: "verified" },
    next: { kind: "approve", situation: "awaitingApproval", reason: "approval_required", returned: "returned.newPlan",
      plan: { label: "修复方案", version: 2, hash: "e2a90b17", risk: "L2", effect: "approve_and_run",
        steps: [
          {say: "确认镜像 orders-api:2.14 在镜像仓库里存在", cmd: "aws ecr describe-images --repository-name orders-api --image-ids imageTag=2.14", tier: R},
          {say: "把期望任务数从 2 改成 4", cmd: "aws ecs update-service --cluster prod --service orders-api --desired-count 4", tier: W},
          {say: "等 4 个任务都通过健康检查", cmd: "aws ecs wait services-stable --cluster prod --services orders-api", tier: R}],
        rollback: "把期望任务数改回 2。" },
      diff: [{op: "add", t: "确认镜像 orders-api:2.14 在镜像仓库里存在"}, {op: "same", t: "把期望任务数从 2 改成 4"},
             {op: "same", t: "等 4 个任务都通过健康检查"}, {op: "del", t: "确认错误率回落（改成了检查项）"}],
      diffFrom: 1, diffWhy: "上一次执行在第 2 步失败：新任务拉不到镜像。",
      impact: { deps: ["orders-web", "checkout"], structural: 2, potential: 5, observed: 1 },
      checks: ["4 个任务都健康", "5 分钟错误率低于 1%"] } },

  { id: "I40", ref: "I#40", entity: "issue", kind: "replan", situation: "planRejected", reason: "review_required",
    severity: "medium", tone: "warn", waitMin: 95, account: "prod", region: "ap-southeast-1",
    title: "nginx 配置回滚的方案被退回了，在等一个新方案",
    rejection: { by: "alice", h: 1.6, text: "不要在工作时间重启。放到 18:00 UTC 以后，并且先在一台机器上试。" },
    cause: { text: "03:10 UTC 的一次配置发布把上游超时从 60 秒改成了 6 秒，之后 5xx 上升。", ev: ["E10"], self: 0.9, critic: "supported", location: "verified" },
    plan: { label: "修复方案", version: 1, hash: "51b7f0c3", risk: "L2", effect: "approve_and_run",
      steps: [
        {say: "把 nginx.conf 恢复到上一个版本", cmd: "ssm: cp /etc/nginx/nginx.conf.bak /etc/nginx/nginx.conf", tier: W},
        {say: "重启 3 台机器上的 nginx", cmd: "ssm: systemctl restart nginx", tier: W}],
      rollback: "把 6 秒超时的版本放回去。" },
    next: { kind: "approve", situation: "awaitingApproval", reason: "approval_required", returned: "returned.replanned",
      plan: { label: "修复方案", version: 2, hash: "0d93a6ee", risk: "L2", effect: "approve_and_run", window: "18:00 UTC",
        steps: [
          {say: "把 nginx.conf 恢复到上一个版本", cmd: "ssm: cp /etc/nginx/nginx.conf.bak /etc/nginx/nginx.conf", tier: W},
          {say: "先在 web-1 上重载（不是重启）", cmd: "ssm(web-1): nginx -t && systemctl reload nginx", tier: W},
          {say: "观察 web-1 的 5xx 5 分钟", cmd: "cloudwatch get-metric-data …", tier: R},
          {say: "再在 web-2、web-3 上重载", cmd: "ssm(web-2, web-3): nginx -t && systemctl reload nginx", tier: W}],
        rollback: "把 6 秒超时的版本放回去并重载。" },
      diff: [{op: "same", t: "把 nginx.conf 恢复到上一个版本"}, {op: "chg", t: "重启 3 台机器上的 nginx → 先在 web-1 上重载（不重启）"},
             {op: "add", t: "观察 web-1 的 5xx 5 分钟"}, {op: "add", t: "再在 web-2、web-3 上重载"}],
      diffFrom: 1, diffWhy: "alice 的意见：不要在工作时间重启，先在一台机器上试。",
      impact: { deps: ["web-1", "web-2", "web-3"], structural: 3, potential: 7, observed: 3 },
      checks: ["3 台机器的 nginx -t 都通过", "5xx 比例回到 0.5% 以下"] } },

  { id: "I44", ref: "I#44", entity: "issue", kind: "rerun", situation: "rcaRejected", reason: "review_required",
    severity: "medium", tone: "warn", waitMin: 150, account: "data", region: "cn-northwest-1",
    title: "你判断 report-job 超时的诊断不对，还没有重新诊断",
    verdict: { by: "you", h: 2.5, v: "no", text: "不是内存。看一下数据库连接池，max_connections 可能被打满了。" },
    cause: { text: "agent 认为 report-job 超时是因为容器内存不足，被反复回收。", ev: ["E11"], self: 0.71, critic: "weak", location: "verified" } },

  { id: "I47", ref: "I#47", entity: "issue", kind: "generate", situation: "toGenerate", reason: "review_required",
    severity: "high", tone: "warn", waitMin: 20, account: "prod", region: "us-east-1", node: "payments-queue",
    title: "payments 队列积压：诊断已经确认，还没有方案",
    verdict: { by: "bob", h: 0.33, v: "yes", text: "对。消费者的并发是在上周的发布里被改成 1 的。" },
    cause: { text: "payments-consumer 的并发数在 11 月 4 日的发布里从 8 改成了 1，队列从那以后只进不出。", ev: ["E12"], self: 0.81, critic: "supported", location: "verified" },
    next: { kind: "approve", situation: "awaitingApproval", reason: "approval_required", returned: "returned.newPlan",
      plan: { label: "修复方案", version: 1, hash: "aa41c9d0", risk: "L1", effect: "approve_and_run",
        steps: [
          {say: "把 payments-consumer 的并发改回 8", cmd: "aws lambda put-function-concurrency --function-name payments-consumer --reserved-concurrent-executions 8", tier: W},
          {say: "确认队列长度开始下降", cmd: "aws sqs get-queue-attributes --queue-url … --attribute-names ApproximateNumberOfMessages", tier: R}],
        rollback: "把并发改回 1。" },
      impact: { deps: ["payments-queue", "ledger"], structural: 2, potential: 4, observed: 1 },
      checks: ["并发 = 8", "10 分钟内队列长度下降一半"] } },

  { id: "I52", ref: "I#52", entity: "issue", kind: "not_started", situation: "notQueued", reason: "execution_not_started",
    severity: "critical", tone: "crit", waitMin: 45, account: "prod", region: "us-east-1", node: "api-cert",
    title: "证书续期的方案已经批准，但没有开始执行",
    why: "批准的时候执行器是关着的，所以这次执行没有排上队。执行器现在已经打开。旧证书 3 天后过期。",
    approved: { by: "you", h: 0.75 },
    plan: { label: "修复方案", version: 1, hash: "9be1f2a7", risk: "L1", effect: "approve_and_run",
      steps: [
        {say: "为 api.example.com 申请新证书", cmd: "aws acm request-certificate --domain-name api.example.com --validation-method DNS", tier: W},
        {say: "把负载均衡的监听器换到新证书", cmd: "aws elbv2 modify-listener --listener-arn … --certificates CertificateArn=…", tier: W}],
      rollback: "把监听器换回旧证书。" },
    checks: ["监听器用的是新证书", "新证书的有效期多于 300 天"] },

  { id: "I58", ref: "I#58", entity: "issue", kind: "resolve", situation: "passed", reason: "verification_required",
    severity: "low", tone: "info", waitMin: 200, account: "prod", region: "ap-southeast-1",
    title: "web-2 的磁盘清理做完了，检查全部通过",
    ran: { run: 44, steps: 2, duration: "38 秒", plan: "修复方案 v1", hash: "c07e5b12", matches: true },
    autoChecks: [ {pc: "pc-1", t: "/var 的使用率低于 70%（现在 41%）"}, {pc: "pc-2", t: "nginx 仍在运行"} ] },

  { id: "I19", ref: "I#19", entity: "issue", kind: "resolve", situation: "unverified", reason: "verification_required",
    severity: "low", tone: "info", waitMin: 4300, account: "data", region: "cn-northwest-1",
    title: "一次旧的执行没有留下结论：给 report-job 加重试",
    ran: { run: 9, steps: 2, duration: "1 分 12 秒", plan: "修复方案 v1", hash: null, matches: null }, autoChecks: [] },

  { id: "C5", ref: "C#5", entity: "change", kind: "start_review", situation: "draft", reason: "review_required",
    risk: "L1", tone: "info", waitMin: 15, account: "prod", region: "us-east-1", requester: "you",
    title: "变更草稿：把 staging 日志的保留期从 30 天改成 7 天",
    request: { text: "staging 的日志没有人看超过一周的。30 天的保留期每月多花约 40 美元。", targets: "/staging/ 下的 12 个日志组",
      steps: [{say: "把 12 个日志组的保留期改成 7 天", cmd: "aws logs put-retention-policy --log-group-name /staging/… --retention-in-days 7", tier: W}] },
    next: { kind: "approve", situation: "awaitingApproval", reason: "approval_required", returned: "returned.reviewed",
      cause: { text: "agent 审过了：12 个日志组都找到了，命令只改保留期。超过 7 天的旧日志会被删除，这一点不能恢复。", ev: [], self: null, critic: "review_passed", location: "found_all" },
      plan: { label: "实施方案", version: 1, hash: "4be7701c", risk: "L1", effect: "approve_and_run",
        steps: [
          {say: "把 12 个日志组的保留期改成 7 天", cmd: "aws logs put-retention-policy --log-group-name /staging/… --retention-in-days 7", tier: W},
          {say: "确认 12 个日志组的保留期都是 7", cmd: "aws logs describe-log-groups --log-group-name-prefix /staging/", tier: R}],
        rollback: "把保留期改回 30 天。已经删除的旧日志回不来。" },
      impact: { deps: ["/staging/ 日志组"], structural: 1, potential: 1, observed: 0 },
      checks: ["12 个日志组的保留期都是 7 天"] } },

  { id: "C6", ref: "C#6", entity: "change", kind: "clarify", situation: "needsClarification", reason: "clarification_required",
    risk: "L2", tone: "warn", waitMin: 70, account: "prod", region: "us-east-1", requester: "carol", node: "chaos-nodes",
    title: "给 EKS 节点组换 AMI：审核卡在两个问题上",
    request: { text: "把 chaos-lab 的节点换到带安全补丁的 AMI。", targets: "EKS chaos-lab" },
    stuck: "申请里没有写清楚范围。agent 不会替你猜。",
    questions: ["要换的是哪个节点组？chaos-lab 里有 ng-general 和 ng-spot 两个。", "可以接受节点逐台重启吗？大约需要 25 分钟。"] },

  { id: "C7", ref: "C#7", entity: "change", kind: "not_started", situation: "notQueued", reason: "execution_not_started",
    risk: "L1", tone: "info", waitMin: 30, account: "prod", region: "us-east-1", requester: "dave",
    title: "调低 DNS TTL 的变更已经批准，但没有排上执行",
    why: "排队的那一刻数据库被锁住了，这次执行没有记上。变更的状态仍是「已批准」。",
    approved: { by: "you", h: 0.5 },
    plan: { label: "实施方案", version: 1, hash: "61f0d3b8", risk: "L1", effect: "approve_and_run",
      steps: [{say: "把 api.example.com 的 TTL 从 3600 改成 300", cmd: "aws route53 change-resource-record-sets --hosted-zone-id … --change-batch file://ttl.json", tier: W}],
      rollback: "把 TTL 改回 3600。" },
    checks: ["记录的 TTL 是 300"] },

  { id: "C8", ref: "C#8", entity: "change", kind: "accept", situation: "awaitingAcceptance", reason: "verification_required",
    risk: "L2", tone: "warn", waitMin: 25, account: "prod", region: "us-east-1", requester: "erin",
    title: "给负载均衡加 WAF 规则的变更执行完了，有一项检查没有结果",
    ran: { run: 46, steps: 2, duration: "1 分 05 秒", plan: "实施方案 v1", hash: "2f6a9c44", matches: true },
    autoChecks: [ {pc: "pc-1", t: "WAF 规则组已经关联到负载均衡"} ],
    needChecks: [ {pc: "pc-2", t: "正常请求没有被误拦（要看 15 分钟的采样）", why: "no_result"} ],
    ev: ["E13"] },
);

/* what three of the first five become */
Object.assign(item("I12"), { next: { kind: "approve", situation: "awaitingApproval", reason: "approval_required", returned: "returned.replanned",
  plan: { label: "修复方案", version: 3, hash: "c5e81b90", risk: "L2", effect: "approve_and_run",
    steps: [
      {say: "确认最近 7 天没有人从公网连过 22 端口", cmd: "aws logs filter-log-events --log-group-name vpc-flow --filter-pattern \"dstport=22 action=ACCEPT\"", tier: R},
      {say: "收回 22 端口对公网的那条规则", cmd: "aws ec2 revoke-security-group-ingress --group-id sg-0a41… --protocol tcp --port 22 --cidr 0.0.0.0/0", tier: W},
      {say: "确认堡垒机网段的规则还在", cmd: "aws ec2 describe-security-groups --group-ids sg-0a41…", tier: R},
      {say: "从堡垒机连一次 web-1", cmd: "ssm: nc -zv web-1 22", tier: R}],
    rollback: "把原规则加回去。回滚不会中断现有连接。" },
  diff: [{op: "add", t: "确认最近 7 天没有人从公网连过 22 端口"}, {op: "same", t: "收回 22 端口对公网的那条规则"},
         {op: "same", t: "确认堡垒机网段的规则还在"}, {op: "same", t: "从堡垒机连一次 web-1"}],
  diffFrom: 2 } });
Object.assign(item("I8"), { afterRun: "acceptance", acceptAfter: { kind: "accept", situation: "awaitingAcceptance", reason: "verification_required", returned: "returned.needsAcceptance",
  ran: { run: 47, steps: 2, duration: "52 秒", plan: "修复方案 v1", hash: "b41f09aa", matches: true },
  autoChecks: [ {pc: "pc-1", t: "BackupRetentionPeriod = 7"} ],
  needChecks: [ {pc: "pc-2", t: "下一个备份窗口有快照：窗口还没到，现在核对不了", why: "no_result"} ], ev: ["E5"] } });
Object.assign(item("I21"), { next: { kind: "approve", situation: "awaitingApproval", reason: "approval_required", returned: "returned.newPlan",
  plan: { label: "修复方案", version: 1, hash: "6a2f7d15", risk: "L2", effect: "approve_and_run",
    steps: [
      {say: "新建任务定义：内存上限从 512 MB 提到 1024 MB", cmd: "aws ecs register-task-definition --cli-input-json file://orders-svc-58.json", tier: W},
      {say: "滚动更新 orders-svc", cmd: "aws ecs update-service --cluster prod --service orders-svc --task-definition orders-svc:58", tier: W},
      {say: "数 30 分钟内的重启次数", cmd: "aws ecs describe-services --cluster prod --services orders-svc", tier: R}],
    rollback: "回到任务定义 orders-svc:57。" },
  impact: { deps: ["orders-api"], structural: 1, potential: 3, observed: 1 },
  checks: ["30 分钟内没有因内存超限的重启"] } });

Object.assign(S.evidence, {
  E8: { title: "orders-api 的 CPU", code: true, src: "fetched", body: "orders-api  CPUUtilization (1 分钟平均)\n  05:00–05:20 UTC   91% 94% 96% 93% …\n  任务数：2（期望 2）" },
  E9: { title: "执行 #41 第 2 步的输出", code: true, src: "fetched", body: "service orders-api: 2 of 4 tasks RUNNING\n  task 7f3a…  STOPPED  CannotPullContainerError:\n    pull image manifest has been retried 5 time(s):\n    orders-api:2.14 not found" },
  E10: { title: "nginx 配置的两个版本", code: true, src: "fetched", body: "- proxy_read_timeout 60s;\n+ proxy_read_timeout 6s;\n（03:10 UTC 的发布，提交 a91c…）" },
  E11: { title: "report-job 最近 6 次超时", code: true, src: "fetched", body: "report-job  exit 124 (timeout)  ×6\n  容器内存峰值：410 MB / 512 MB\n  没有 OOM 记录" },
  E12: { title: "payments-consumer 的并发设置", code: true, src: "fetched", body: "PutFunctionConcurrency  payments-consumer\n  ReservedConcurrentExecutions: 8 → 1\n  by: deploy-role  at 2026-11-04 09:12 UTC" },
  E13: { title: "WAF 采样到的请求（前 5 分钟）", code: true, src: "fetched", body: "采样 500 条\n  ALLOW  497\n  BLOCK    3   （都是 /wp-login.php 的探测）\n采样窗口 15 分钟，还差 10 分钟" },
});

S.events.push(
  {h: 1.6, k: "decision", t: "alice 退回了 I#40 的方案"}, {h: 0.9, k: "signal", t: "扩容 orders-api 的执行失败，已回滚"},
  {h: 0.75, k: "decision", t: "I#52 的方案已批准"}, {h: 0.33, k: "decision", t: "bob 确认了 I#47 的诊断"});
S.hot.push(
  {name: "orders-api", cl: 0, from: 0.9, to: 0, tone: "amber", ref: "I31"}, {name: "payments-queue", cl: 0, from: 30, to: 0, tone: "amber", ref: "I47"},
  {name: "api-cert", cl: 4, from: 30, to: 0, tone: "red", ref: "I52"}, {name: "chaos-nodes", cl: 3, from: 1.2, to: 0, tone: "violet", ref: "C6"});

/* the story page: who first saw it and when each phase happened (hours before now) */
const STORY = {
  I12: {found: [2.4, "scan", "扫描发现 sg_web 的 22 端口对 0.0.0.0/0 开放。"], rca: 2.3, plan: 2.2, signals: 3},
  C3: {found: [5.2, "alice", "alice 提了这张变更单。"], rca: 5.1, plan: 5.0},
  I8: {found: [18.17, "scan", "扫描发现 database-demo 的备份保留期是 0。"], rca: 18.1, plan: 18.0, signals: 2},
  I934: {found: [30, "patrol", "巡检发现 4 个 Aurora 实例和 2 个负载均衡没有告警。"], rca: 29.5, plan: 29, approve: 1.1, run: 0.7},
  I21: {found: [4.8, "alarm", "告警：orders-svc 的任务在 30 分钟内重启了 14 次。"], rca: 3.0, signals: 14},
  I31: {found: [3.2, "alarm", "告警：orders-api 的 CPU 持续在 90% 以上。"], rca: 3.0, plan: 2.6, approve: 1.2, run: 0.9, signals: 5},
  I40: {found: [3.1, "alarm", "告警：web 的 5xx 比例超过 2%。"], rca: 2.9, plan: 2.2, signals: 8},
  I44: {found: [4.1, "alarm", "告警：report-job 连续超时。"], rca: 3.4, signals: 6},
  I47: {found: [1.5, "alarm", "告警：payments 队列长度超过 50,000。"], rca: 1.0, signals: 2},
  I52: {found: [26, "scan", "扫描发现 api.example.com 的证书 4 天后过期。"], rca: 25.8, plan: 25.5, approve: 0.75},
  I58: {found: [4.0, "alarm", "告警：web-2 的 /var 使用率 92%。"], rca: 3.9, plan: 3.8, approve: 3.5, run: 3.4},
  I19: {found: [1700, "alarm", "告警：report-job 偶发失败。"], rca: 1699, plan: 1698, approve: 1697, run: 1696},
  C5: {found: [0.25, "you", "你写了这张变更单，还没有送审。"]},
  C6: {found: [1.4, "carol", "carol 提了这张变更单。"], rca: 1.2},
  C7: {found: [2.0, "dave", "dave 提了这张变更单。"], rca: 1.8, plan: 1.5, approve: 0.5},
  C8: {found: [3.0, "erin", "erin 提了这张变更单。"], rca: 2.8, plan: 2.5, approve: 0.6, run: 0.45},
};
S.items.forEach(i => { const s = STORY[i.id]; if (!s) return; i.found = {h: s.found[0], by: s.found[1], t: s.found[2]}; i.at = {rca: s.rca, plan: s.plan, approve: s.approve, run: s.run}; i.signals = s.signals || 1; });
})();
