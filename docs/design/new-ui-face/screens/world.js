/* new-UI-face — the «全景» lens: every resource on one map, with the last 24 hours on a scrubber. */
(function(){
"use strict";
const NF = window.NF, $ = NF.$, S = NF.S, t = (...a) => NF.t(...a), tx = v => NF.tx(v), esc = NF.esc;

function render(){
  const h = S.hoursAgo, abn = NF.sky.hot.filter(x => NF.sky.active(x)).length, narrow = innerWidth <= 760;
  const list = NF.store.events.filter(e => e.h >= h).sort((a, b) => a.h - b.h).slice(0, narrow ? 4 : 9);
  $("#happen").innerHTML = `<h2>${h === 0 ? t("world.now") : t("world.backTo", {t: NF.clockAt(h)})}</h2><div class="abn num">${abn}<small>${t("world.abnormal")}</small></div>
    <ul>${list.map(e => `<li class="${e.cause ? "cause" : ""}"><time>${NF.clockAt(e.h).replace(/^\S+ (?=\d)/, "")}</time><span>${esc(NF.eventText(e))}${e.cause ? "　" + t("world.cause") : ""}</span></li>`).join("")}</ul>`;
  $("#scrubT").textContent = t("world.scrub"); $("#scrub").setAttribute("aria-label", t("world.time"));
  $("#scrubLbl").textContent = h === 0 ? t("world.nowAt", {t: NF.clockAt(0)}) : t("world.ago", {t: NF.clockAt(h), d: h < 1 ? NF.fmtWait(Math.round(h * 60)) : NF.fmtWait(Math.round(h) * 60)});
  $("#legend").innerHTML = [["red", "legend.critical"], ["amber", "legend.waiting"], ["mint", "legend.agent"], ["violet", "legend.change"]].map(([c, k]) => `<span><i style="background:var(--${c})"></i>${t(k)}</span>`).join("")
    + `<span><i style="background:rgb(var(--star));opacity:.6"></i>${t("legend.none")}</span>`;
}
function nodeCard(n){
  const el = $("#nodecard"); if (!n){ el.hidden = true; return; }
  const h = NF.sky.hot.find(x => x.node === n), it = h && NF.store.get(h.ref), open = h && NF.sky.active(h);
  el.innerHTML = `<h3>${esc(n.name || t("node.generic"))}</h3><div style="color:var(--dim)">${esc(tx(NF.seed.clusters[n.cl].name))}</div>
    <p style="margin:8px 0 0">${NF.prov(true)}${open ? `${t("node.open")} <span class="num">${it ? it.ref : h.ref.replace(/^([IC])/, "$1#")}</span>${it ? "：" + esc(tx(it.title)) : ""}` : t("node.none")}</p>
    ${it && it.status === "waiting" ? `<div style="margin-top:10px"><button class="btn primary" data-do="openItem" data-id="${it.id}"><span class="t">${t("node.go")}</span></button></div>` : ""}`;
  el.hidden = false;
}
NF.on.openItem = el => { S.filter = "all"; S.cur = el.dataset.id; NF.setLens("decide"); };
NF.screens.world = {
  render(){ $("#scrub").value = 240 - S.hoursAgo * 10; $("#nodecard").hidden = true; render(); }, refresh: render,
  init(){
    const cv = $("#sky"), tip = $("#tip");
    $("#scrub").addEventListener("input", e => { S.hoursAgo = (240 - +e.target.value) / 10; render(); });
    cv.addEventListener("mousemove", e => {
      if (S.lens !== "world"){ tip.hidden = true; cv.style.cursor = "default"; return; }
      const n = NF.sky.pick(e.clientX, e.clientY); if (!n){ tip.hidden = true; cv.style.cursor = "default"; return; }
      const h = NF.sky.hot.find(x => x.node === n);
      tip.textContent = (n.name || t("node.resource")) + "　" + (h && NF.sky.active(h) ? t("node.open") : t("node.noneShort"));
      tip.style.left = e.clientX + 14 + "px"; tip.style.top = e.clientY + 12 + "px"; tip.hidden = false; cv.style.cursor = "pointer";
    });
    cv.addEventListener("click", e => { if (S.lens === "world") nodeCard(NF.sky.pick(e.clientX, e.clientY)); });
  },
};
})();
