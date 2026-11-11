/* new-UI-face — the command bar: say a sentence to ask the agent, "/" for commands, "@" for objects.
   The answers are canned sample text (zh). */
(function(){
"use strict";
const NF = window.NF, $ = NF.$, $$ = NF.$$, S = NF.S, t = (...a) => NF.t(...a), tx = v => NF.tx(v), esc = NF.esc;
let sugg = [], sugIdx = 0, typing = null;

function commands(){
  const notDrawn = stage => () => NF.notify(t("cmd.notDrawn", {stage}));
  return [
    {k: t("cmd.decide"), h: "1", run: () => NF.setLens("decide")}, {k: t("cmd.live"), h: "2", run: () => NF.setLens("live")}, {k: t("cmd.world"), h: "3", run: () => NF.setLens("world")},
    {k: t("cmd.critical"), run: () => { S.onlyCritical = true; S.filter = "all"; S.cur = null; S.curIdx = 0; NF.setLens("decide"); NF.notify(t("cmd.criticalOn")); }},
    {k: t("cmd.all"), run: () => { S.onlyCritical = false; S.filter = "all"; NF.setLens("decide"); }},
    {k: t("cmd.theme"), h: "T", run: () => NF.setTheme(S.theme === "night" ? "day" : "night")}, {k: t("cmd.keys"), h: "?", run: () => NF.openHelp()},
    ...NF.store.waiting().map(i => ({k: `${i.ref}　${tx(i.title)}`, obj: true, h: t("need." + i.reason), run: () => { S.filter = "all"; S.onlyCritical = false; S.cur = i.id; NF.setLens("decide"); }})),
    {k: t("cmd.reports"), h: t("cmd.reports.h"), run: notDrawn("D5")}, {k: t("cmd.schedules"), h: t("cmd.schedules.h"), run: notDrawn("D5")},
    {k: t("cmd.skills"), run: notDrawn("D5")}, {k: t("cmd.settings"), run: notDrawn("D6")},
  ];
}
function show(){
  const cmd = $("#cmd"), v = cmd.value.trim(), q = v.replace(/^[\/@]/, "").toLowerCase(), el = $("#sugg");
  let list = commands().filter(c => !q || c.k.toLowerCase().includes(q));
  if (v.startsWith("@")) list = list.filter(c => c.obj);
  if (v && !v.startsWith("/")) list.unshift({k: t("cmd.ask", {q: v}), h: t("cmd.enter"), run: () => answer(v)});
  sugg = list.slice(0, 8); sugIdx = 0;
  if (!sugg.length || document.activeElement !== cmd){ el.hidden = true; return; }
  el.innerHTML = sugg.map((c, k) => `<button role="option" aria-selected="${k === 0}" data-do="sugg" data-s="${k}"><span>${esc(c.k)}</span>${c.h ? `<small>${esc(c.h)}</small>` : ""}</button>`).join("");
  el.hidden = false; NF.closeSheet();
}
function run(k){ const c = sugg[k]; if (!c) return; $("#sugg").hidden = true; const cmd = $("#cmd"); cmd.value = ""; cmd.blur(); c.run(); }
function answer(q){
  const el = $("#sheet"); clearInterval(typing);
  const about = /I#12|sg_web|22/.test(q);
  const text = about ? "sg_web 是今天 03:52 UTC 被部署流水线改的：它加了一条 22 端口对公网的规则，之后没有收回。直接的记录有两条（E1、E2），「为了调试」这一点是我推断的，没有记录能证明。"
    : "过去 24 小时有三件事值得你知道。其余 14 条信号我已经并到已有的问题里，没有打扰你。";
  const head = about ? ["时间 (UTC)", "发生了什么", "证据"] : ["编号", "什么事", "级别", "现在"];
  const rows = about ? [["03:52", "deploy-role 加了规则", "E1"], ["03:56", "扫描发现 22 端口对公网开放", "E2"], ["04:04", "诊断完成，出了方案 v2", "—"]]
    : [["I#12", "SSH 对公网开放", "严重", "等你批准"], ["I#37", "lambda-pay 错误率升高", "高", "我正在查"], ["I#8", "RDS 自动备份被关", "高", "等你批准"]];
  const more = about ? [["把 E1 给我看", "ev:E1"], ["打开 I#12", "item:I12"]] : [["为什么 sg_web 会被改？", "ask"], ["打开 I#12", "item:I12"]];
  el.innerHTML = `<div class="q0">${esc(q)}</div><div id="ans">${NF.prov(false)}<span></span></div>`; el.hidden = false;
  const out = $("#ans span"); let n = 0;
  const done = () => out.parentNode.insertAdjacentHTML("afterend", `<table class="grid" style="margin-top:10px"><tr>${head.map(h => `<th>${h}</th>`).join("")}</tr>${rows.map(r => `<tr>${r.map(c => `<td>${c}</td>`).join("")}</tr>`).join("")}</table>
    <div class="more">${more.map(m => `<button data-do="more" data-m="${m[1]}">${m[0]}</button>`).join("")}</div>`);
  typing = setInterval(() => { n += 3; out.textContent = text.slice(0, n); if (n >= text.length){ clearInterval(typing); done(); } }, 16);
}
NF.closeSheet = () => { clearInterval(typing); $("#sheet").hidden = true; };
NF.on.sugg = el => run(+el.dataset.s);
NF.on.more = el => {
  const m = el.dataset.m;
  if (m.startsWith("item:")){ NF.closeSheet(); S.filter = "all"; S.cur = m.slice(5); return NF.setLens("decide"); }
  if (m.startsWith("ev:")){ NF.closeSheet(); if (S.lens !== "decide"){ S.cur = "I12"; NF.setLens("decide"); } return NF.openPeek(m.slice(3)); }
  answer(el.textContent);
};
NF.screens.command = { init(){
  const cmd = $("#cmd");
  cmd.addEventListener("input", show); cmd.addEventListener("focus", show);
  cmd.addEventListener("blur", () => setTimeout(() => { $("#sugg").hidden = true; }, 120));
  cmd.addEventListener("keydown", e => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp"){ e.preventDefault(); if (!sugg.length) return;
      sugIdx = (sugIdx + (e.key === "ArrowDown" ? 1 : -1) + sugg.length) % sugg.length; $$("#sugg button").forEach((b, k) => b.setAttribute("aria-selected", k === sugIdx)); }
    else if (e.key === "Enter" && !e.isComposing && e.keyCode !== 229){ e.preventDefault(); if (sugg.length) run(sugIdx); }
  });
} };
})();
