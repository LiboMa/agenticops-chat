/* new-UI-face — D3 sample data: what agents are doing right now (the «现场» lens).
   Everything here is invented. A step is one of three kinds:
     act  = something the agent did            find = a fact the code fetched            neither = the model's own inference
   `more` = the steps still to come while the lens is open; `then` = what the run becomes when they are used up.
   `steer` = a person may say a word or pause it (diagnosis, planning, review — never an execution, never a scan). */
(function(){
"use strict";
const S = window.NF.seed;

S.runs = [
  { id: "r1", agent: "rca", ref: "I#37", title: "诊断 I#37　lambda-pay 错误率升高", state: "run", stateKey: "live.investigating", startedMin: 4, steer: true,
    steps: [
      {t: "取这个函数周围的关系和最近的变更", c: "get_topology_evidence(I#37)", act: true},
      {t: "05:55 UTC 起错误率从 0.2% 升到 7.4%", c: "cloudwatch get-metric-data", find: true},
      {t: "05:52 UTC 有一次发布：pay-fn 版本 41 → 42", c: "cloudtrail lookup-events", find: true},
      {t: "在看版本 42 改了什么……", c: "lambda get-function --qualifier 42", act: true}],
    more: [
      {t: "版本 42 把超时从 30 秒改成了 3 秒", c: "diff 41..42", find: true},
      {t: "下游 orders-api 的 p95 是 4.1 秒，超过新的超时", c: "cloudwatch get-metric-data", find: true},
      {t: "推断：超时改成 3 秒后，调下游的请求全部超时。把握 86%", c: "save_rca_result"}],
    then: {state: "wait", stateKey: "live.planning"},
    ack: "收到。先核对这一点，再继续原来的顺序。" },
  { id: "r2", agent: "scan", title: "扫描 us-east-1 的资源", state: "run", progress: 62, startedMin: 3,
    steps: [
      {t: "已列完 EC2、RDS、ELB", c: "scan us-east-1", find: true},
      {t: "正在列 EKS", c: "scan us-east-1 --type EKS", act: true}],
    done: {t: "扫描完成：us-east-1 共 781 个资源，3 个不见了", c: "scan us-east-1", find: true} },
  { id: "r3", agent: "sre", ref: "I#63", title: "I#63 的修复方案草稿", state: "wait", stateKey: "live.inPolicy", startedMin: 2,
    steps: [
      {t: "方案写好了：3 步，回滚 1 步", c: "save_fix_plan", act: true},
      {t: "3 步里有 1 步代码分不了类，不会自动批准，会来问你", c: "policy: unclassified_command", find: true}] },
  { id: "r5", agent: "reporter", title: "每日运行报告", state: "wait", stateKey: "live.scheduled", stateVars: {t: "07:00"}, startedMin: null,
    steps: [{t: "到点后开始：汇总过去 24 小时的问题、变更和执行", c: "schedule: daily-report", find: true}] },
  { id: "r4", agent: "executor", ref: "I#58", title: "执行 I#58　清理 web-2 的磁盘", state: "done", stateKey: "live.doneAgo", agoMin: 12, startedMin: 14,
    steps: [
      {t: "清理 /var/log 下 14 天前的日志", c: "ssm: find /var/log -mtime +14 -delete", act: true, tier: "write"},
      {t: "确认 /var 的使用率低于 70%", c: "ssm: df -h /var", find: true, tier: "read"},
      {t: "2 项检查由代码逐项核对，全部通过", c: "verification: passed", find: true}] },
];
})();
