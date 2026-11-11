/* new-UI-face — briefs for an issue that left the straight path: a failed run, a run that never started,
   a plan or a diagnosis that a person sent back, a diagnosis waiting for its plan, a run waiting to be closed. */
(function(){
"use strict";
const NF = window.NF, A = NF.actions, B = NF.briefParts, t = (...a) => NF.t(...a), tx = v => NF.tx(v), esc = NF.esc, prov = NF.prov;
const ok = (store, it, ...kinds) => !!it && kinds.includes(it.kind) && it.status === "waiting" && store.canDecide();
const who = by => by === "you" ? t("who.you") : by;

/* ── logic ─────────────────────────────────────────────────────────────── */
A.newPlan = (store, id) => {                              // failed run, rejected plan, confirmed diagnosis → a plan, then back for approval
  const it = store.get(id); if (!ok(store, it, "failed", "replan", "generate")) return false;
  return A.handOff(store, it, {key: "toast.sentPlan", vars: {ref: it.ref}}, it.kind === "replan" ? "agent.replanning" : "agent.planning", true);
};
A.rediagnose = (store, id) => {                           // does not come back in the prototype: a new diagnosis is the agent's
  const it = store.get(id); if (!ok(store, it, "failed", "rerun", "generate")) return false;
  return A.handOff(store, it, {key: "toast.sentRca", vars: {ref: it.ref}}, "agent.rediagnose", false);
};
A.retry = (store, id) => {                                // approved but never started: run it now
  const it = store.get(id); if (!ok(store, it, "not_started")) return false;
  store.act(id, {key: "toast.retry", vars: {ref: it.ref}}, {
    apply(){ it.status = "pending"; it.run = {step: 0, total: it.plan.steps.length, pending: true, done: false}; },
    revert(){ it.status = "waiting"; delete it.run; },
    commit(){ store.startRun(id); },
  });
  return true;
};
A.withdraw = (store, id, reason) => {
  const it = store.get(id); reason = (reason || "").trim(); if (!ok(store, it, "not_started") || !reason) return false;
  store.act(id, {key: "toast.withdrawn", vars: {ref: it.ref}}, { apply(){ it.status = "withdrawn"; it.myReason = reason; }, revert(){ it.status = "waiting"; delete it.myReason; }, commit(){} });
  return true;
};
A.resolve = (store, id) => {
  const it = store.get(id); if (!ok(store, it, "resolve")) return false;
  store.act(id, {key: "toast.resolved", vars: {ref: it.ref}}, { apply(){ it.status = "done"; }, revert(){ it.status = "waiting"; }, commit(){ store.log("decision", "event.resolved", {ref: it.ref}); } });
  return true;
};
A.recheck = (store, id) => {
  const it = store.get(id); if (!ok(store, it, "resolve") || it.situation !== "unverified") return false;
  return A.handOff(store, it, {key: "toast.sentCheck", vars: {ref: it.ref}}, "agent.rechecking", false);
};

/* ── drawing ───────────────────────────────────────────────────────────── */
B.runSteps = run => `<ol class="steps">${run.steps.map(s => `<li class="${s.status}"><span class="say">${esc(tx(s.say))}<span class="tier ${s.tier === "write" ? "w" : ""}">${t("tier." + s.tier)}</span></span>
  <code class="cmd">${esc(s.cmd)}</code>${s.error ? `<p class="note" style="color:var(--red);margin-top:4px">${prov(true)}${esc(tx(s.error))}</p>` : ""}</li>`).join("")}</ol>`;
B.cause = (it, low) => `<p>${prov(false)}${esc(tx(it.cause.text))} ${B.chips(it.cause.ev)}</p>${B.trust(it.cause, low)}`;
B.quote = (text, cite) => `<blockquote class="quote">${esc(tx(text))}<cite>${esc(cite)}</cite></blockquote>`;
B.checksAfter = it => `<ul class="checks">${it.checks.map((c, k) => `<li><span class="pc">pc-${k + 1}</span><span>${esc(tx(c))}</span><span class="st">${t("checks.after")}</span></li>`).join("")}</ul>`;

NF.briefs.failed = {
  ask: () => t("ask.failed"),
  body: it => { const r = it.lastRun; return `
    <div class="sec"><h2>${t("sec.failedStep")}</h2><p>${prov(true)}${esc(t("ran.failed", {run: r.id, n: r.failedAt, duration: tx(r.duration)}))}</p>${B.runSteps(r)}</div>
    <div class="sec"><h2>${t("sec.stateNow")}</h2><p>${prov(true)}${esc(tx(r.rollback))}</p></div>
    <div class="sec"><h2>${t("sec.itsReason")}</h2>${B.cause(it)}</div>`; },
  buttons: it => `<button class="btn primary" id="primary" data-do="primary"><span class="t">${t("act.newPlan")}</span><kbd>A</kbd></button>`
    + B.btn(t("act.rediagnose"), "M", 'data-do="alt" data-a="rediagnose"') + B.tail(it),
  primary: it => A.newPlan(NF.store, it.id),
  keys: { m: it => A.rediagnose(NF.store, it.id) },
};

NF.briefs.not_started = {
  hold: true,                                   // a retry runs the plan: the key must be held
  ask: () => t("ask.not_started"),
  body: it => `
    <div class="sec"><h2>${t("sec.whyNotStarted")}</h2><p>${prov(true)}${esc(tx(it.why))}</p></div>
    <div class="sec"><h2>${t("sec.approvedPlan")}　<span class="num" style="color:var(--dim)">${esc(t("plan.version", {label: tx(it.plan.label), v: it.plan.version}))}　${it.plan.hash}　${it.plan.risk}</span></h2>${B.steps(it.plan)}
      <p class="note">${prov(true)}${esc(t("approved.line", {by: who(it.approved.by), t: NF.clockAt(it.approved.h), hash: it.plan.hash}))}</p>
      <p class="note">${prov(true)}${esc(t("plan.note", {rollback: tx(it.plan.rollback)}))}</p></div>
    <div class="sec"><h2>${t("sec.done")}</h2>${B.checksAfter(it)}</div>`,
  buttons: it => `<button class="btn primary" id="primary" data-hold="1"><span class="fill"></span><span class="t">${t("act.retry")}</span><kbd>A</kbd></button>`
    + B.btn(t("act.withdraw"), "R", 'data-do="reject"') + B.tail(it),
  primary: it => A.retry(NF.store, it.id),
  reject: (it, reason) => A.withdraw(NF.store, it.id, reason), rejectLabel: "act.withdraw", rejectPlaceholder: "withdraw.placeholder",
};

NF.briefs.replan = {
  ask: () => t("ask.replan"),
  body: it => `
    <div class="sec"><h2>${t("sec.whoRejected")}</h2>${B.quote(it.rejection.text, t("rejected.cite", {by: who(it.rejection.by), t: NF.clockAt(it.rejection.h)}))}</div>
    <div class="sec"><h2>${t("sec.rejectedPlan", {v: it.plan.version})}　<span class="num" style="color:var(--dim)">${it.plan.hash}　${it.plan.risk}</span></h2>${B.steps(it.plan)}</div>
    <div class="sec"><h2>${t("sec.why")}</h2>${B.cause(it)}</div>`,
  buttons: it => `<button class="btn primary" id="primary" data-do="primary"><span class="t">${t("act.replan")}</span><kbd>A</kbd></button>` + B.tail(it),
  primary: it => A.newPlan(NF.store, it.id),
};

NF.briefs.rerun = {
  ask: () => t("ask.rerun"),
  body: it => `
    <div class="sec"><h2>${t("sec.yourVerdict")}</h2>${B.quote(it.verdict.text, t("verdict.cite", {by: who(it.verdict.by), v: t("verdict." + it.verdict.v), t: NF.clockAt(it.verdict.h)}))}</div>
    <div class="sec"><h2>${t("sec.rejectedRca")}</h2>${B.cause(it, true)}</div>`,
  buttons: it => `<button class="btn primary" id="primary" data-do="primary"><span class="t">${t("act.rediagnose")}</span><kbd>A</kbd></button>` + B.tail(it),
  primary: it => A.rediagnose(NF.store, it.id),
};

NF.briefs.generate = {
  ask: () => t("ask.generate"),
  body: it => `
    <div class="sec"><h2>${t("sec.confirmedRca")}</h2>${B.cause(it)}</div>
    <div class="sec"><h2>${t("sec.humanVerdict")}</h2>${B.quote(it.verdict.text, t("verdict.cite", {by: who(it.verdict.by), v: t("verdict." + it.verdict.v), t: NF.clockAt(it.verdict.h)}))}</div>`,
  buttons: it => `<button class="btn primary" id="primary" data-do="primary"><span class="t">${t("act.generate")}</span><kbd>A</kbd></button>`
    + B.btn(t("act.rediagnose"), "M", 'data-do="alt" data-a="rediagnose"') + B.tail(it),
  primary: it => A.newPlan(NF.store, it.id),
  keys: { m: it => A.rediagnose(NF.store, it.id) },
};

NF.briefs.resolve = {
  ask: it => t("ask.resolve." + it.situation),
  body: it => { const r = it.ran, old = it.situation === "unverified"; return `
    <div class="sec"><h2>${t("sec.ran")}</h2><p>${prov(true)}${esc(t(old ? "ran.old" : "ran.line", {run: r.run, steps: r.steps, duration: tx(r.duration)}))}</p>
      ${old ? `<p class="note">${prov(true)}${t("resolve.noVerdict")}</p>` : `<p class="note">${prov(true)}${esc(t("ran.bind", {plan: tx(r.plan), hash: r.hash}))}</p>`}</div>
    ${old ? "" : `<div class="sec"><h2>${t("sec.auto")}</h2><ul class="checks">${it.autoChecks.map(c => `<li><span class="pc">${c.pc}</span><span>${esc(tx(c.t))}</span><span class="st ok">${t("st.passed")}</span></li>`).join("")}</ul>
      <p class="note">${prov(true)}${t("resolve.autoOff")}</p></div>`}`; },
  buttons: it => `<button class="btn primary" id="primary" data-do="primary"><span class="t">${t("act.resolve")}</span><kbd>A</kbd></button>`
    + (it.situation === "unverified" ? B.btn(t("act.recheck"), "M", 'data-do="alt" data-a="recheck"') : "") + B.tail(it),
  primary: it => A.resolve(NF.store, it.id),
  keys: { m: it => A.recheck(NF.store, it.id) },
};
})();
