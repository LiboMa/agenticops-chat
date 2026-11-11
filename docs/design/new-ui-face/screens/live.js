/* new-UI-face — the «现场» lens: what each agent is doing, step by step. A person can say a word or pause. */
(function(){
"use strict";
const NF = window.NF, $ = NF.$, S = NF.S, t = (...a) => NF.t(...a), tx = v => NF.tx(v), esc = NF.esc;

function render(){
  $("#rec").innerHTML = NF.runs.map(r => `<article class="run card" data-run="${r.id}"><header><b>${esc(tx(r.title))}</b><span class="state-t ${r.state === "wait" ? "wait" : r.state === "done" ? "done" : ""}">${NF.runState(r)}</span></header>
    <ol>${r.steps.map(s => `<li class="${s.find ? "find" : ""}">${s.act ? "" : NF.prov(!!s.find)}${esc(tx(s.t))}　<code>${esc(s.c)}</code></li>`).join("")}</ol>
    ${r.steer ? `<form class="steer" data-form="steer"><input class="field" placeholder="${t("live.steerPh")}" aria-label="${t("live.steerLabel")}"><button class="btn sm" type="submit"><span class="t">${t("live.tell")}</span></button><button class="btn sm" type="button" data-do="pause"><span class="t">${t(r.paused ? "live.resume" : "live.pause")}</span></button></form>` : ""}</article>`).join("");
}
NF.on.pause = () => {
  const r = NF.runs[0]; r.paused = !r.paused;
  if (r.paused){ r.prevKey = r.stateKey; r.stateKey = "live.paused"; } else r.stateKey = r.prevKey || "live.investigating";
  render();
};
NF.onSubmit.steer = form => {
  const i = form.querySelector("input"), v = i.value.trim(); if (!v) return;
  NF.runs[0].steps.push({t: t("live.youSaid", {v}), c: "steer", find: true}); render(); NF.notify(t("live.told"));
};
NF.screens.live = {
  render, refresh(){},
  init(){ setInterval(() => {                    // the sample diagnosis moves on while the lens is open
    const r = NF.runs[0]; if (S.lens !== "live" || !r.more || !r.more.length || r.paused) return;
    if (document.activeElement && document.activeElement.closest && document.activeElement.closest(".steer")) return;   // not while the person is typing
    r.steps.push(r.more.shift());
    if (!r.more.length){ r.state = "wait"; r.stateKey = "live.planning"; }
    render();
  }, 2600); },
};
})();
