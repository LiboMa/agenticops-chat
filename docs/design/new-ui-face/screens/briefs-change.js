/* new-UI-face — briefs that only a change request has: a draft to send for review, and a review stuck on questions.
   A change waiting for approval, for a retry or for acceptance uses the same briefs as an issue. */
(function(){
"use strict";
const NF = window.NF, A = NF.actions, B = NF.briefParts, t = (...a) => NF.t(...a), tx = v => NF.tx(v), esc = NF.esc, prov = NF.prov;
const ok = (store, it, kind) => !!it && it.kind === kind && it.status === "waiting" && store.canDecide();
const who = by => by === "you" ? t("who.you") : by;

A.startReview = (store, id) => {
  const it = store.get(id); if (!ok(store, it, "start_review")) return false;
  return A.handOff(store, it, {key: "toast.sentReview", vars: {ref: it.ref}}, "agent.reviewing", true);
};
A.cancelChange = (store, id, reason) => {
  const it = store.get(id); reason = (reason || "").trim(); if (!ok(store, it, "start_review") || !reason) return false;
  store.act(id, {key: "toast.cancelled", vars: {ref: it.ref}}, { apply(){ it.status = "cancelled"; it.myReason = reason; }, revert(){ it.status = "waiting"; delete it.myReason; }, commit(){} });
  return true;
};
A.answer = (store, id, k, text) => { const it = store.get(id); if (!ok(store, it, "clarify")) return false; it.answers = it.answers || it.questions.map(() => ""); it.answers[k] = text; return true; };
A.canClarify = it => !!it.answers && it.answers.length === it.questions.length && it.answers.every(a => a.trim());
A.clarify = (store, id) => {
  const it = store.get(id); if (!ok(store, it, "clarify") || !A.canClarify(it)) return false;
  return A.handOff(store, it, {key: "toast.answered", vars: {ref: it.ref}}, "agent.reviewing", false);
};

const request = it => `<div class="sec"><h2>${t("sec.request")}</h2><p>${esc(tx(it.request.text))}</p>
  <p class="note">${esc(t("request.by", {by: who(it.requester)}))}　${esc(t("request.targets", {targets: tx(it.request.targets)}))}</p></div>`;

NF.briefs.start_review = {
  ask: () => t("ask.start_review"),
  body: it => `${request(it)}
    <div class="sec"><h2>${t("sec.proposed")}</h2>${B.steps(it.request)}<p class="note">${t("review.note")}</p></div>`,
  buttons: it => `<button class="btn primary" id="primary" data-do="primary"><span class="t">${t("act.startReview")}</span><kbd>A</kbd></button>`
    + B.btn(t("act.cancelChange"), "R", 'data-do="reject"') + B.tail(it),
  primary: it => A.startReview(NF.store, it.id),
  reject: (it, reason) => A.cancelChange(NF.store, it.id, reason), rejectLabel: "act.cancelChange", rejectPlaceholder: "cancel.placeholder",
};

NF.briefs.clarify = {
  ask: it => t("ask.clarify", {n: it.questions.length}),
  body: it => { const a = it.answers || []; return `${request(it)}
    <div class="sec"><h2>${t("sec.stuck")}</h2><p>${prov(false)}${esc(tx(it.stuck))}</p></div>
    <div class="sec"><h2>${t("sec.questions")}</h2>${it.questions.map((q, k) => `<p style="margin:${k ? 12 : 0}px 0 6px">${k + 1}. ${esc(tx(q))}</p>
      ${NF.store.canDecide() ? `<input class="field" data-answer="${k}" value="${esc(a[k] || "")}" placeholder="${t("clarify.ph")}" aria-label="${t("clarify.label", {n: k + 1})}">` : ""}`).join("")}</div>`; },
  buttons: it => `<button class="btn primary" id="primary" data-do="primary" ${A.canClarify(it) ? "" : "disabled"}><span class="t">${t("act.submitAnswers")}</span><kbd>A</kbd></button>` + B.tail(it),
  primary: it => A.clarify(NF.store, it.id),
};
/* typing an answer keeps the brief as it is: only the button's state changes */
document.addEventListener("input", e => {
  const el = e.target; if (!el.dataset || el.dataset.answer === undefined) return;
  const it = NF.current(); if (!it || it.kind !== "clarify") return;
  A.answer(NF.store, it.id, +el.dataset.answer, el.value);
  const btn = NF.$("#primary"); if (btn) btn.disabled = !A.canClarify(it);
});
})();
