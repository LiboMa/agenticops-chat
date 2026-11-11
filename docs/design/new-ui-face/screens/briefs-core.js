/* new-UI-face — the three briefs of the first draft: approve, accept, confirm.
   Each brief = the logic (NF.actions, no DOM) + how it is drawn (NF.briefs[kind]). */
(function(){
"use strict";
const NF = window.NF, A = NF.actions, t = (...a) => NF.t(...a), tx = v => NF.tx(v), esc = NF.esc, prov = NF.prov;

/* ── logic ─────────────────────────────────────────────────────────────── */
const ok = (store, it, kind) => !!it && it.kind === kind && it.status === "waiting" && store.canDecide();

A.approve = (store, id) => {
  const it = store.get(id); if (!ok(store, it, "approve")) return false;
  store.act(id, {key: "toast.approved", vars: {ref: it.ref}}, {
    apply(){ it.status = "pending"; it.run = {step: 0, total: it.plan.steps.length, pending: true, done: false}; },
    revert(){ it.status = "waiting"; delete it.run; },
    commit(){ store.startRun(id); },
  });
  return true;
};
A.reject = (store, id, reason) => {                       // send a plan back with a reason
  const it = store.get(id); reason = (reason || "").trim();
  if (!ok(store, it, "approve") || !reason) return false;
  store.act(id, {key: "toast.rejected", vars: {ref: it.ref}}, {
    apply(){ it.status = "rejected"; it.rejection = reason; },
    revert(){ it.status = "waiting"; delete it.rejection; },
    commit(){ store.agentWork(id, "agent.replanning"); },
  });
  return true;
};
A.blankTicks = it => it.needChecks.map(() => false).concat(false);     // one box per check to look at + one overall
A.tick = (store, id, k) => {                               // k omitted = tick the next empty box
  const it = store.get(id); if (!ok(store, it, "accept")) return false;
  it.ticks = it.ticks || A.blankTicks(it);
  if (k === undefined){ k = it.ticks.indexOf(false); if (k < 0) return false; it.ticks[k] = true; }
  else it.ticks[k] = !it.ticks[k];
  it.rev++; store.emit(); return true;
};
A.canAccept = it => !!it.ticks && it.ticks.every(Boolean);
A.accept = (store, id) => {
  const it = store.get(id); if (!ok(store, it, "accept") || !A.canAccept(it)) return false;
  store.act(id, {key: "toast.accepted", vars: {ref: it.ref}}, {
    apply(){ it.status = "done"; }, revert(){ it.status = "waiting"; },
    commit(){ store.log("decision", "event.accepted", {ref: it.ref}); },
  });
  return true;
};
A.rejectAccept = (store, id, reason) => {
  const it = store.get(id); reason = (reason || "").trim();
  if (!ok(store, it, "accept") || !reason) return false;
  store.act(id, {key: "toast.notAccepted", vars: {ref: it.ref}}, {
    apply(){ it.status = "rejected"; it.rejection = reason; },
    revert(){ it.status = "waiting"; delete it.rejection; },
    commit(){ store.agentWork(id, "agent.rediagnose"); },
  });
  return true;
};
A.verdict = (store, id, v) => {
  const it = store.get(id); if (!ok(store, it, "confirm") || !["yes", "partial", "no", "more"].includes(v)) return false;
  store.act(id, {key: "toast.verdict", vars: {ref: it.ref, v: t("verdict." + v)}}, {
    apply(){ it.status = "done"; it.verdict = v; }, revert(){ it.status = "waiting"; delete it.verdict; }, commit(){},
  });
  return true;
};
A.snooze = (store, id) => {
  const it = store.get(id); if (!it || it.status !== "waiting" || !store.canDecide()) return false;
  it.waitMin = 0; it.snoozed = true; it.rev++; store.emit(); return true;
};

/* ── drawing ───────────────────────────────────────────────────────────── */
const B = NF.briefParts = {
  chips: ev => `<span style="white-space:nowrap">${ev.map(e => `<button class="ev" data-do="peek" data-ev="${e}">${e}</button>`).join("")}</span>`,
  pct: v => v == null ? "—" : Math.round(v * 100) + "%",
  btn: (label, key, attrs = "", cls = "") => `<button class="btn ${cls}" ${attrs}><span class="t">${label}</span>${key ? `<kbd>${key}</kbd>` : ""}</button>`,
  tail: () => B.btn(t("act.ask"), "E", 'data-do="ask"') + B.btn(t("act.snooze"), "S", 'data-do="snooze"'),
  trust: (c, low) => `<div class="trust">
    <div class="tile"><small>${prov(false)}${t("trust.self")}</small><b${low ? ' style="color:var(--amber)"' : ""}>${B.pct(c.self)}</b></div>
    <div class="tile"><small>${prov(false)}${t("trust.critic")}</small><b class="zh">${t("critic." + c.critic)}</b></div>
    <div class="tile"><small>${prov(true)}${t("trust.location")}</small><b class="zh">${t("location." + c.location)}</b></div></div>`,
  impactSvg: it => {
    const d = it.impact.deps, c = "var(--" + ({crit: "red", info: "violet"}[it.tone] || "amber") + ")", n = d.length;
    const pts = d.map((_, k) => [124, n === 1 ? 42 : 12 + k * (60 / (n - 1))]);
    return `<svg width="150" height="84" viewBox="0 0 150 84" aria-hidden="true">${pts.map(p => `<line x1="20" y1="42" x2="${p[0]}" y2="${p[1]}" stroke="${c}" stroke-opacity=".55"/>`).join("")}
      <circle cx="20" cy="42" r="6" fill="${c}"/><circle cx="20" cy="42" r="11" fill="none" stroke="${c}" stroke-opacity=".5"/>
      ${pts.map(p => `<circle cx="${p[0]}" cy="${p[1]}" r="4" fill="var(--chalk)" fill-opacity=".85"/>`).join("")}</svg>`;
  },
  steps: plan => `<ol class="steps">${plan.steps.map(s => `<li><span class="say">${esc(tx(s.say))}<span class="tier ${s.tier === "write" ? "w" : ""}">${t("tier." + s.tier)}</span></span><code class="cmd">${esc(s.cmd)}</code></li>`).join("")}</ol>`,
  planHead: p => `${t("sec.plan")}　<span class="num" style="color:var(--dim)">${esc(t("plan.version", {label: tx(p.label), v: p.version}))}　${p.hash}　${p.risk}</span>`,
};

NF.briefs.approve = {
  hold: true,                                   // approving runs the plan: the key must be held
  ask: () => t("ask.approve"),
  body: it => `
    <div class="sec"><h2>${t("sec.why")}</h2><p>${prov(false)}${esc(tx(it.cause.text))} ${B.chips(it.cause.ev)}</p>${B.trust(it.cause)}</div>
    <div class="sec"><h2>${B.planHead(it.plan)}</h2>${B.steps(it.plan)}
      <p class="note">${prov(true)}${esc(t("plan.note", {rollback: tx(it.plan.rollback)}))}</p></div>
    <div class="sec"><h2>${t("sec.impact")}</h2><div class="impact">${B.impactSvg(it)}<div>
      <div class="nums"><div><b>${it.impact.structural}</b>${t("impact.structural")}</div><div><b>${it.impact.potential}</b>${t("impact.potential")}</div><div><b>${it.impact.observed}</b>${t("impact.observed")}</div></div>
      <p class="note">${prov(true)}${esc(t("impact.note", {deps: it.impact.deps.join("、")}))}</p></div></div></div>
    <div class="sec"><h2>${t("sec.done")}</h2><ul class="checks">${it.checks.map((c, k) => `<li><span class="pc">pc-${k + 1}</span><span>${esc(tx(c))}</span><span class="st">${t("checks.after")}</span></li>`).join("")}</ul>
      <p class="note">${t("checks.note")}</p></div>`,
  buttons: () => `<button class="btn primary" id="primary" data-hold="1"><span class="fill"></span><span class="t">${t("act.approve")}</span><kbd>A</kbd></button>`
    + B.btn(t("act.reject"), "R", 'data-do="reject"') + B.tail(),
  primary: it => A.approve(NF.store, it.id),
  reject: (it, reason) => A.reject(NF.store, it.id, reason),
};

NF.briefs.accept = {
  ask: it => t("ask.accept", {n: it.needChecks.length}),
  body: it => {
    const tk = it.ticks || A.blankTicks(it), last = tk.length - 1;
    const box = (k, label) => `<button class="tickbox" role="checkbox" aria-checked="${tk[k]}" data-do="tick" data-k="${k}" aria-label="${esc(label)}">${tk[k] ? "✓" : ""}</button>`;
    return `
    <div class="sec"><h2>${t("sec.ran")}</h2><p>${prov(true)}${esc(t("ran.line", {run: it.ran.run, steps: it.ran.steps, duration: tx(it.ran.duration)}))} ${B.chips(it.ev)}</p>
      <p class="note">${prov(true)}${esc(t("ran.bind", {plan: tx(it.ran.plan), hash: it.ran.hash}))}</p></div>
    <div class="sec"><h2>${t("sec.auto")}</h2><ul class="checks">${it.autoChecks.map(c => `<li><span class="pc">${c.pc}</span><span>${esc(tx(c.t))}</span><span class="st ok">${t("st.passed")}</span></li>`).join("")}</ul></div>
    <div class="sec"><h2>${t("sec.need")}</h2><ul class="checks">${it.needChecks.map((c, k) => `<li>${box(k, t("accept.checked", {pc: c.pc}))}<span class="pc">${c.pc}</span><span>${esc(tx(c.t))}</span><span class="st need">${t("why." + c.why)}</span></li>`).join("")}
      <li>${box(last, t("accept.overall"))}<span class="pc"></span><span>${t("accept.overall")}</span></li></ul>
      <p class="note">${t("accept.note")}</p></div>`;
  },
  buttons: it => `<button class="btn primary" id="primary" data-do="primary" ${A.canAccept(it) ? "" : "disabled"}><span class="t">${t("act.accept")}</span><kbd>A</kbd></button>`
    + B.btn(t("act.tick"), "X", 'data-do="tickNext"') + B.btn(t("act.rejectAccept"), "R", 'data-do="reject"') + B.btn(t("act.ask"), "E", 'data-do="ask"'),
  primary: it => A.accept(NF.store, it.id),
  reject: (it, reason) => A.rejectAccept(NF.store, it.id, reason),
  keys: { x: it => A.tick(NF.store, it.id) },
};

NF.briefs.confirm = {
  ask: () => t("ask.confirm"),
  body: it => `
    <div class="sec"><h2>${t("sec.judgement")}</h2><p>${prov(false)}${esc(tx(it.cause.text))} ${B.chips(it.cause.ev)}</p>${B.trust(it.cause, it.cause.self < it.gate)}
      <p class="note">${prov(true)}${esc(t("gate.note", {gate: B.pct(it.gate)}))}</p></div>
    <div class="sec"><h2>${t("sec.verdict")}</h2><div class="choices">${[["yes", "Y"], ["partial", "P"], ["no", "N"], ["more", "M"]].map(([v, k]) =>
      `<button class="choice" data-do="verdict" data-v="${v}"><kbd>${k}</kbd>${t("verdict." + v)}</button>`).join("")}</div>
      <p class="note">${t("verdict.note")}</p></div>`,
  buttons: () => B.tail(),
  keys: { y: it => A.verdict(NF.store, it.id, "yes"), p: it => A.verdict(NF.store, it.id, "partial"),
          n: it => A.verdict(NF.store, it.id, "no"), m: it => A.verdict(NF.store, it.id, "more") },
};
})();
