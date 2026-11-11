/* new-UI-face — the interface's own words, zh and en. Sample data (titles, causes, commands) lives in data.js.
   selftest.html fails when a key exists in one language only. */
(function(){
"use strict";
const NF = window.NF = window.NF || {};
const zh = {}, en = {};
const add = rows => { for (const k in rows){ zh[k] = rows[k][0]; en[k] = rows[k][1]; } };

add({ // shell
  "lens.decide": ["待决", "Decide"], "lens.live": ["现场", "Live"], "lens.world": ["全景", "World"],
  "pulse.label": ["过去 24 小时", "Last 24 hours"], "pulse.now": ["现在 {t} UTC", "Now {t} UTC"],
  "scope.all": ["全部账户", "All accounts"], "scope.only": ["原型里账户范围只有「全部」", "The prototype has one scope: all accounts"],
  "theme.night": ["夜", "Night"], "theme.day": ["昼", "Day"], "theme.toggle": ["切换昼夜", "Switch day / night"],
  "keys.open": ["快捷键", "Keyboard shortcuts"], "account": ["账户", "Account"],
  "time.yesterday": ["昨天", "Yesterday"], "utc": ["UTC", "UTC"],
  "unit.min": ["{n} 分钟", "{n} min"], "unit.hour": ["{n} 小时", "{n} h"], "unit.day": ["{n} 天", "{n} d"],
});
add({ // queue
  "queue.title": ["在等你决定", "Waiting on you"], "queue.label": ["待决队列", "Decision queue"],
  "filter.all": ["全部", "All"], "filter.approval": ["批准", "Approve"], "filter.acceptance": ["验收", "Accept"],
  "filter.confirm": ["确认", "Confirm"], "filter.failed": ["异常", "Trouble"],
  "need.approval_required": ["等你批准", "Needs your approval"], "need.verification_required": ["等你验收", "Needs your acceptance"],
  "need.review_required": ["等你确认", "Needs your call"], "need.execution_failed": ["执行失败", "Run failed"],
  "need.execution_not_started": ["没有开始", "Did not start"], "need.clarification_required": ["等你回答", "Needs your answer"],
  "waited": ["等了 {t}", "waited {t}"],
  "hint.move": ["换一件", "move"], "hint.evidence": ["证据", "evidence"], "hint.all": ["全部", "all keys"], "key.space": ["空格", "Space"],
  "sev.critical": ["严重", "Critical"], "sev.high": ["高", "High"], "sev.medium": ["中", "Medium"], "sev.low": ["低", "Low"],
  "sev.change": ["常规变更", "Routine change"],
});
add({ // briefs
  "ask.lead": ["需要你：", "You decide: "],
  "ask.approve": ["批准这份方案。批准后立即执行。", "approve this plan. It runs as soon as you approve."],
  "ask.accept": ["看过 {n} 项检查，然后验收。", "look at {n} checks, then accept."],
  "ask.confirm": ["判断这个诊断对不对。", "say whether this diagnosis is right."],
  "sec.why": ["为什么", "Why"], "sec.plan": ["打算怎么做", "What it will do"], "sec.impact": ["会碰到谁", "What it touches"],
  "sec.done": ["做完怎么算成", "How we know it worked"], "sec.ran": ["做了什么", "What ran"],
  "sec.auto": ["代码已经核对过的", "Checked by code"], "sec.need": ["要你看一眼的", "For you to look at"],
  "sec.judgement": ["agent 的判断", "The agent's diagnosis"], "sec.verdict": ["你怎么看", "Your call"],
  "trust.self": ["模型自己的把握", "The model's own confidence"], "trust.critic": ["另一个模型复核", "A second model's review"],
  "trust.location": ["出事的位置", "Where it happened"],
  "critic.supported": ["支持", "Supported"], "critic.weak": ["证据偏弱", "Weak evidence"], "critic.refuted": ["被否定", "Refuted"],
  "critic.review_passed": ["审核通过", "Review passed"],
  "location.verified": ["已核实", "Verified"], "location.found_all": ["都找到了", "All found"], "location.absent": ["没有给出", "Not given"],
  "tier.write": ["会改动", "changes things"], "tier.read": ["只读", "read-only"],
  "plan.version": ["{label} v{v}", "{label} v{v}"],
  "plan.note": ["每条命令的「会改动 / 只读」是代码分的类。出问题时：{rollback}", "Code, not the model, labels each command as changing or read-only. If it goes wrong: {rollback}"],
  "impact.structural": ["直接相连", "directly attached"], "impact.potential": ["可能受影响", "may be affected"],
  "impact.observed": ["已经出问题", "already in trouble"],
  "impact.note": ["{deps} 直接依赖它。关系来自规则，不是模型猜的。", "{deps} depend on it directly. The relations come from rules, not from a model's guess."],
  "checks.after": ["执行后由代码核对", "checked by code after the run"],
  "checks.note": ["少一项结果，就不算通过，会回到这里等你验收。", "One missing result and it does not pass: it comes back here for your acceptance."],
  "ran.line": ["执行 #{run}：{steps} 步都完成了，用时 {duration}。", "Run #{run}: all {steps} steps finished in {duration}."],
  "ran.bind": ["按 {plan}（哈希 {hash}）执行，和批准时的内容一致。", "Ran {plan} (hash {hash}), the same content that was approved."],
  "st.passed": ["通过", "passed"], "why.warning": ["警告", "warning"], "why.no_result": ["没有结果", "no result"],
  "accept.checked": ["已核对 {pc}", "Checked {pc}"],
  "accept.overall": ["我看过结果了，目标状态符合预期", "I looked at the result: it is in the state we wanted"],
  "accept.note": ["打完勾才能验收。你勾了哪几项会记进审计。", "Accept unlocks when every box is ticked. The boxes you tick go into the audit record."],
  "gate.note": ["把握低于 {gate} 的诊断不会自动出方案，需要你判断。", "A diagnosis below {gate} confidence gets no automatic plan: it waits for you."],
  "verdict.yes": ["对，照这个出方案", "Right: plan from it"], "verdict.partial": ["部分对，我补充一句", "Partly right: I'll add a note"],
  "verdict.no": ["不对", "Wrong"], "verdict.more": ["让它再查一次", "Look again"],
  "verdict.note": ["你的判断会成为它下次遇到同类问题时的依据。", "Your call becomes evidence the next time it meets this kind of problem."],
  "readonly": ["只读账户：可以看，不能做决定。", "Read-only account: you can look, not decide."],
});
add({ // actions and notices
  "act.approve": ["按住批准并执行", "Hold to approve & run"], "act.accept": ["验收", "Accept"],
  "act.reject": ["退回", "Send back"], "act.rejectAccept": ["不通过", "Not accepted"], "act.ask": ["问它", "Ask"],
  "act.snooze": ["稍后", "Later"], "act.tick": ["逐项打勾", "Tick next"], "act.cancel": ["取消", "Cancel"],
  "act.holdHint": ["要按住不放", "Keep holding"],
  "reject.placeholder": ["说一句为什么，agent 会照着重做", "Say why in a sentence; the agent redoes it accordingly"],
  "reject.label": ["退回的理由", "Reason for sending back"], "reject.required": ["要写一句理由", "A reason is required"],
  "toast.approved": ["已批准 {ref}，5 秒后开始执行", "{ref} approved — the run starts in 5 seconds"],
  "toast.accepted": ["已验收 {ref}", "{ref} accepted"], "toast.verdict": ["{ref}：记下了「{v}」", "{ref}: recorded “{v}”"],
  "toast.rejected": ["已退回 {ref}，agent 会按你的理由重做", "{ref} sent back — the agent redoes it with your reason"],
  "toast.notAccepted": ["{ref} 验收不通过，回到诊断", "{ref} not accepted — back to diagnosis"],
  "toast.snoozed": ["{ref} 放到最后，1 小时后再提醒你", "{ref} moved to the end; you'll be reminded in an hour"],
  "toast.undone": ["已撤回，什么都没有发生", "Undone. Nothing happened."],
  "toast.done": ["{ref} 做完了：{n} 项检查由代码核对，都通过", "{ref} is done: {n} checks verified by code, all passed"],
  "undo": ["撤回", "Undo"],
  "event.fixed": ["{ref} 已修复，检查全部通过", "{ref} fixed, every check passed"],
  "event.accepted": ["{ref} 已验收", "{ref} accepted"],
});
add({ // right rail, empty and failed states
  "feed.title": ["agent 现在在做", "Agents at work"], "feed.pending": ["5 秒后开始", "Starts in 5 s"], "feed.canUndo": ["还可以撤回", "You can still undo"],
  "feed.running": ["正在执行", "Running"], "feed.done": ["做完了", "Done"],
  "feed.checked": ["{n} 项检查由代码核对，都通过了", "{n} checks verified by code, all passed"],
  "agent.replanning": ["按你的理由重做方案", "Redoing the plan with your reason"], "agent.rediagnose": ["重新诊断", "Diagnosing again"],
  "clear.big": ["现在没有需要你决定的事", "Nothing needs your decision right now"],
  "clear.p": ["agent 还在看着。出现它拿不准的、或者需要人批准的事，会第一时间放到这里。", "The agents keep watching. Anything they are unsure of, or that needs a person's approval, lands here first."],
  "clear.resources": ["个资源在看", "resources watched"], "clear.scan": ["分钟前扫过一遍", "min since the last scan"],
  "clear.working": ["件事 agent 正在处理", "things agents are working on"],
  "clear.honest": ["没有未结问题不等于一切健康：agent 只能看到它被允许看的东西。", "No open issue is not the same as healthy: agents see only what they are allowed to see."],
  "state.loading": ["正在取数据…", "Loading…"], "state.failed": ["没取到数据", "Could not load"],
  "state.failed.p": ["这不代表没有事情在等你。上一次成功是 {t} UTC。", "This does not mean nothing waits on you. The last successful load was {t} UTC."],
  "state.retry": ["重试", "Retry"],
});
add({ // evidence peek
  "peek.label": ["证据", "Evidence"], "peek.fetched": ["代码取回的原始记录", "Raw record fetched by code"],
  "peek.graph_rule": ["关系图（规则生成，不是模型猜的）", "Relation graph (built by rules, not guessed by a model)"],
  "peek.model": ["模型的推断", "The model's inference"], "peek.checked": ["代码逐项核对", "Checked item by item by code"],
  "peek.next": ["换一条", "next"], "peek.close": ["关上", "Close"],
  "prov.code": ["代码核实", "verified by code"], "prov.model": ["模型推断", "inferred by a model"],
});
add({ // live
  "live.investigating": ["正在查", "Investigating"], "live.inPolicy": ["在过策略", "In policy check"], "live.doneAgo": ["{n} 分钟前完成", "Done {n} min ago"],
  "live.paused": ["停住了，等你", "Paused, waiting for you"], "live.planning": ["查完了，在出方案", "Done; writing the plan"],
  "live.steerPh": ["插一句话：比如「先看下游的超时」", "Say something: e.g. “check the downstream timeout first”"],
  "live.steerLabel": ["给 agent 补充一句", "A word for the agent"], "live.tell": ["告诉它", "Tell it"], "live.pause": ["先停一下", "Pause"], "live.resume": ["继续", "Resume"],
  "live.told": ["告诉它了，它会先做这件事", "Told. It will do that first."], "live.youSaid": ["你说：「{v}」。它调整了下一步", "You said: “{v}”. It changed its next step"],
});
add({ // world
  "world.now": ["现在", "Now"], "world.backTo": ["回到 {t} UTC", "Back at {t} UTC"], "world.abnormal": ["个资源不正常", "resources not normal"],
  "world.cause": ["← 之后出的事从这里开始", "← what followed starts here"], "world.scrub": ["拖动回到过去", "Drag to go back in time"],
  "world.time": ["时间", "Time"], "world.nowAt": ["现在 {t} UTC", "Now {t} UTC"], "world.ago": ["{t} UTC（{d}前）", "{t} UTC ({d} ago)"],
  "legend.critical": ["严重", "Critical"], "legend.waiting": ["在等你", "Waiting on you"], "legend.agent": ["agent 在处理", "An agent is on it"],
  "legend.change": ["有待批的变更", "A change awaits approval"], "legend.none": ["没有未结问题（不等于健康）", "No open issue (not the same as healthy)"],
  "node.generic": ["一个资源", "A resource"], "node.resource": ["资源", "Resource"], "node.open": ["有未结的问题", "has an open issue"],
  "node.noneShort": ["没有未结问题", "no open issue"],
  "node.none": ["没有未结的问题。这不等于健康，只是没有发现异常。", "No open issue. That is not the same as healthy: nothing abnormal was found."],
  "node.go": ["去处理", "Go decide"],
});
add({ // command bar
  "cmd.placeholder": ["说一句话，或输入 / 找命令、@ 找对象", "Say something, or type / for commands, @ for objects"], "cmd.label": ["指令", "Command"],
  "cmd.ask": ["问 agent：{q}", "Ask the agent: {q}"], "cmd.enter": ["回车", "Enter"],
  "cmd.decide": ["看待决的事", "See what waits on me"], "cmd.live": ["看 agent 现在在做什么", "See what agents are doing"],
  "cmd.world": ["看全景，拖时间", "See everything, scrub time"], "cmd.critical": ["只看严重的", "Critical only"], "cmd.all": ["全部", "Everything"],
  "cmd.criticalOn": ["只显示严重的。再输入「全部」恢复", "Showing critical only. Type “Everything” to undo"],
  "cmd.theme": ["切换昼 / 夜", "Switch day / night"], "cmd.keys": ["快捷键", "Keyboard shortcuts"],
  "cmd.reports": ["报告", "Reports"], "cmd.schedules": ["定时任务", "Schedules"], "cmd.skills": ["技能", "Skills"], "cmd.settings": ["设置", "Settings"],
  "cmd.reports.h": ["今天 1 份新的", "1 new today"], "cmd.schedules.h": ["1 个连续失败", "1 failing repeatedly"],
  "cmd.notDrawn": ["这一页还没有画（{stage} 阶段）；它会从这里进入", "Not drawn yet (stage {stage}); it will open from here"],
});
add({ // help
  "help.title": ["手不离键盘", "Hands on the keyboard"],
  "help.p": ["这是一份可以点的交互设计稿，数据是示例。它想验证一件事：把 900 多个问题，变成眼前的几个决定。", "A clickable interaction draft with sample data. It tests one idea: turn 900 issues into the few decisions in front of you."],
  "help.move": ["下一件 / 上一件", "next / previous"], "help.primary": ["这一页的主要动作（会改动基础设施的要按住）", "this page's main action (hold it when it changes infrastructure)"],
  "help.reject": ["退回并说明", "send back with a reason"], "help.ask": ["就这件事问 agent", "ask the agent about this"], "help.snooze": ["稍后再提醒", "remind me later"],
  "help.peek": ["看证据，← → 换一条", "peek at evidence, ← → to move"], "help.tick": ["验收时逐项打勾", "tick the next check"],
  "help.verdict": ["诊断：对 / 部分对 / 不对 / 再查", "diagnosis: right / partly / wrong / again"], "help.lens": ["待决 / 现场 / 全景", "decide / live / world"],
  "help.cmd": ["指令条（也可以直接问）", "the command bar (or just ask)"], "help.undo": ["5 秒内撤回", "undo within 5 seconds"], "help.theme": ["昼 / 夜", "day / night"],
  "help.prov": ["每句话都标明是哪一种。", "Every sentence says which one it is."], "help.ok": ["知道了", "Got it"],
});
add({ // the prototype's own switches
  "dev.title": ["原型开关", "Prototype switches"], "dev.note": ["这一块不属于产品。", "This panel is not part of the product."],
  "dev.data": ["数据状态", "Data state"], "dev.ready": ["有数据", "Ready"], "dev.loading": ["加载中", "Loading"], "dev.failed": ["失败", "Failed"], "dev.empty": ["空", "Empty"],
  "dev.role": ["身份", "Role"], "role.admin": ["管理员", "Admin"], "role.writer": ["读写", "Read-write"], "role.viewer": ["只读", "Read-only"],
  "dev.lang": ["语言", "Language"], "dev.theme": ["主题", "Theme"], "dev.reset": ["重置示例数据", "Reset sample data"],
  "dev.langNote": ["示例数据的英文到 D7 阶段再补。", "English sample data arrives in stage D7."],
});

add({ // added with the decide screen
  "snoozed": ["稍后再看", "snoozed"], "brief.label": ["这件事的简报", "The brief for this item"],
  "pos": ["{i} / {n}", "{i} / {n}"], "feed.agent": ["agent 在处理", "An agent is on it"],
});

NF.STR = {zh, en};
})();
