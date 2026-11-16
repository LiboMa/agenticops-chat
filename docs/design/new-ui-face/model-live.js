/* new-UI-face — the «现场» lens without a screen: what is in flight, and what a person may do to it. No DOM.
   A lane = one piece of work: an approved plan being run, an agent doing what a decision asked for, or a sample
   background run. Rules that live here:
     · an execution follows the approved version: it can be stopped, never steered;
     · a word or a pause is for an agent that is still thinking (diagnosis, plan, review);
     · a read-only account watches and does nothing. */
(function(){
"use strict";
const NF = window.NF, t = (...a) => NF.t(...a), tx = v => NF.tx(v);
const NONE = () => ({steer: false, pause: false, stop: false, undo: false});
const AGENT_OF = {"agent.replanning": "sre", "agent.planning": "sre", "agent.rediagnose": "rca", "agent.rechecking": "executor", "agent.reviewing": "sre"};
const GROUP = {pending: "running", run: "running", stopping: "running", rollback: "running", paused: "waiting", wait: "waiting", done: "finished"};

NF.live = {
  agentOf: taskKey => AGENT_OF[taskKey] || "sre",

  /* Everything in flight or just finished, one lane each: {id, itemId, ref, agent, title, sub, state, label, step, total,
     steps: [{t, cmd, tier, find, act, you, status: done | now | todo | wait | held | skip}], can, group}. */
  lanes(store, runs){
    const may = store.canDecide(), out = [];
    store.items.forEach(it => {
      if (it.run && it.plan){                                  // an approved plan: «can still undo» → step by step → done
        const r = it.run, state = r.pending ? "pending" : r.done ? "done" : r.rollingBack ? "rollback" : r.stopping ? "stopping" : "run";
        const steps = it.plan.steps.map((s, k) => ({t: s.say, cmd: s.cmd, tier: s.tier, act: true,
          status: r.done || k < r.step ? "done" : r.rollingBack ? "skip" : k === r.step && !r.pending ? "now" : "todo"}));
        if (r.rollingBack) steps.push({t: t("live.rollbackStep", {rollback: tx(it.plan.rollback)}), cmd: "rollback", tier: "write", act: true, status: "now"});
        const can = NONE(); can.undo = may && state === "pending"; can.stop = may && state === "run";
        out.push({id: "x-" + it.id, itemId: it.id, ref: it.ref, agent: "executor", title: t("live.runOf", {ref: it.ref}), sub: tx(it.title), state, steps, can, group: GROUP[state],
          step: Math.min(r.step + 1, r.total), total: r.total,
          label: state === "pending" ? t("feed.pending") : state === "run" ? t("live.stepOf", {i: r.step + 1, n: r.total}) : state === "stopping" ? t("live.stopping")
               : state === "rollback" ? t("live.rollingBack") : t("feed.checked", {n: (it.checks || []).length})});
      } else if (it.agent){                                    // an agent doing what a decision asked for
        out.push({id: "a-" + it.id, itemId: it.id, ref: it.ref, agent: NF.live.agentOf(it.agent.taskKey), title: t(it.agent.taskKey), sub: it.ref + "　" + tx(it.title), state: "run",
          steps: [{t: t(it.agent.taskKey), cmd: "", act: true, status: "now"}], can: NONE(), group: "running", step: 1, total: 1, label: t("live.working")});
      }
    });
    runs.forEach(r => {
      const last = r.steps.length - 1, total = r.steps.length + (r.more ? r.more.length : 0), steerable = may && !!r.steer && (r.state === "run" || r.state === "paused");
      const steps = r.steps.map((s, k) => ({t: s.t, cmd: s.c, tier: s.tier, find: !!s.find, act: !!s.act, you: !!s.you,
        status: r.state === "done" || k < last ? "done" : r.state === "run" ? "now" : r.state === "paused" ? "held" : "wait"}));
      const can = NONE(); can.steer = steerable; can.pause = steerable;
      out.push({id: r.id, itemId: null, ref: r.ref || null, agent: r.agent, title: tx(r.title), sub: "", state: r.state, steps, can, group: GROUP[r.state], step: r.steps.length, total,
        progress: r.progress, startedMin: r.startedMin, agoMin: r.agoMin,
        label: r.stateKey ? t(r.stateKey, r.stateVars || {n: r.agoMin}) : r.progress != null ? r.progress + "%" : ""});
    });
    return out;
  },

  /* A word for an agent that is still thinking: your sentence joins the record, and it answers. */
  steer(store, run, text){
    text = (text || "").trim();
    if (!run || !run.steer || !text || !store.canDecide() || !(run.state === "run" || run.state === "paused")) return false;
    run.steps.push({t: text, you: true}, {t: run.ack || t("live.ack")});         // the answer is the model's own words: no command, no fact
    return true;
  },
  /* Pause / resume: the same button. */
  pause(store, run){
    if (!run || !run.steer || !store.canDecide()) return false;
    if (run.state === "run"){ run.state = "paused"; run.prevKey = run.stateKey; run.stateKey = "live.paused"; return true; }
    if (run.state === "paused"){ run.state = "run"; run.stateKey = run.prevKey || "live.investigating"; delete run.prevKey; return true; }
    return false;
  },
  /* One beat of the sample background runs. Returns whether anything changed. */
  tick(runs){
    let changed = false;
    runs.forEach(r => {
      if (r.state !== "run") return;
      if (r.more && r.more.length){
        r.steps.push(r.more.shift()); changed = true;
        if (!r.more.length && r.then) Object.assign(r, r.then);
      } else if (r.progress != null){
        r.progress = Math.min(100, r.progress + 4); changed = true;
        if (r.progress === 100){ r.state = "done"; r.stateKey = "live.doneAgo"; r.agoMin = 0; if (r.done) r.steps.push(r.done); }
      }
    });
    return changed;
  },
};

/* A stopped run: the steps done so far stay done, the rest never ran, the plan's rollback ran.
   An issue goes back to the queue as «the run did not finish»; a change ends as rolled_back (a redo is a new request). */
NF.afterStop = (store, it) => {
  const p = it.plan, done = it.run.step, secs = Math.round((done + 1) * NF.STEP_MS / 1000);
  if (it.entity === "change"){
    delete it.run; it.status = "done"; it.endState = "rolled_back"; it.rev++;
    store.log("decision", "event.stopped", {ref: it.ref}); store.notice("toast.stoppedChange", {ref: it.ref});
    return;
  }
  it.lastRun = { id: store.newRunId(), plan: `${tx(p.label)} v${p.version}`, hash: p.hash, duration: {zh: secs + " 秒", en: secs + " s"}, failedAt: done, stopped: true,
    steps: p.steps.map((s, k) => ({say: s.say, cmd: s.cmd, tier: s.tier, status: k < done ? "ok" : "skip"})),
    rollback: {zh: NF.STR.zh["run.rolledBack"].replace("{rollback}", NF.pick(p.rollback, "zh")), en: NF.STR.en["run.rolledBack"].replace("{rollback}", NF.pick(p.rollback, "en"))} };
  delete it.run;
  Object.assign(it, {kind: "failed", situation: "needsNewPlan", reason: "execution_failed", status: "waiting", waitMin: 0, snoozed: false, returned: "returned.stopped", rev: it.rev + 1});
  store.log("decision", "event.stopped", {ref: it.ref}); store.notice("toast.stopped", {ref: it.ref});
};
})();
