import { useState } from "react";
import { ApiError } from "@/api/client";
import { useSettings } from "@/hooks/useSettings";
import { parseItem } from "@/lib/inbox";
import { choiceAvailable, noteRequired, remainingRequests, verdictRequests, type VerdictChoice, type VerdictRequests } from "@/lib/verdict";
import { useIssueVerdict, useRcaVerdict } from "../../hooks/useIssueDecisions";
import { useFreshRca } from "../../hooks/useItemData";
import { useNfT } from "../../i18n";
import { causeVm, pct } from "../../lib/briefs/cause";
import { StateBlock } from "../../shell/StateBlock";
import { useShell } from "../../shell/shellContext";
import { BriefFrame } from "../BriefFrame";
import { AgentAtWork } from "../widgets/AgentAtWork";
import { Cause } from "../widgets/Cause";
import { ReasonForm } from "../widgets/ReasonForm";
import { errorText, useBriefKeys, useDecide, type BriefProps } from "./briefContext";
import { useAgentAsk } from "./shared";

const CHOICES: [VerdictChoice, string][] = [["correct", "Y"], ["partial", "P"], ["rcaWrong", "N"], ["falsePositive", "F"]];

/** A diagnosis that did not pass the auto-fix gate: a person says whether it is right. The four answers are the
 *  product's own (lib/verdict) and go to the same two endpoints as the classic page's «Your verdict».
 *  The verdict is about the diagnosis ON THE PAGE: it is read again when the brief opens (never from a cache — after
 *  «diagnose again» the cache held the old one), the choices are not armed while that read is in flight, and the
 *  request names the diagnosis so the server refuses it when a newer one exists. */
export function ConfirmBrief({ item, frame }: BriefProps) {
  const t = useNfT();
  const { notify, defer } = useShell();
  const { done, failed, openPeek } = useDecide();
  const issueId = parseItem(item.id)?.id ?? 0;
  const rcaQ = useFreshRca(issueId);
  const settings = useSettings();
  const rcaFb = useRcaVerdict(issueId);
  const issueFb = useIssueVerdict(issueId);
  const agent = useAgentAsk(item);
  const [asking, setAsking] = useState<VerdictChoice | null>(null);     // a choice that needs a reason: the box is open
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [remaining, setRemaining] = useState<{ req: VerdictRequests; choice: VerdictChoice } | null>(null);

  const rca = rcaQ.data;
  const fresh = rcaQ.isSuccess && !rcaQ.isFetching;                    // the server's answer to this page, nothing newer on its way
  const gate = settings.data?.rca_min_confidence_for_autofix;
  const cause = causeVm(rca, gate);
  const gateNote = !cause ? null : cause.belowGate ? t("gate.note", { gate: pct(gate) }) : cause.critic === "refuted" ? t("gate.critic") : t("gate.manual");

  const finish = (choice: VerdictChoice) => {
    if (choice === "falsePositive") return done(item, t("toast.closed", { ref: item.ref }));    // the item is dismissed: on to the next
    // the item stays with you — as «generate the plan» after «right», as «diagnose again» after «wrong»
    notify(choice === "rcaWrong" ? t("toast.verdict", { ref: item.ref, v: t("verdict.rcaWrong") }) : t("toast.verdict.correct", { ref: item.ref }));
  };
  const send = async (req: VerdictRequests, choice: VerdictChoice) => {
    setBusy(true);
    setError(null);
    try {
      if (req.rcaFeedback && rca) await rcaFb.mutateAsync({ ...req.rcaFeedback, rca_id: rca.id });
    } catch (e) {
      // a newer diagnosis exists: nothing was recorded; the page re-reads it (the mutation settles into a refresh)
      const text = e instanceof ApiError && e.code === "rca_changed" ? t("err.rcaChanged") : t("err.failed", { msg: errorText(e) });
      setError(text);
      failed(item, text);
      setBusy(false);
      return;
    }
    try {
      if (req.issueFeedback) await issueFb.mutateAsync(req.issueFeedback);
    } catch (e) {
      const rest = remainingRequests(req, "issueFeedback");       // the diagnosis verdict is saved: only the rest is retried
      setRemaining(rest ? { req: rest, choice } : null);
      const text = t(rest ? "err.partial" : "err.failed", { msg: errorText(e) });
      setError(text);
      // the saved verdict changes the item's situation, so this brief is about to be replaced: say it where it stays
      if (rest) notify(`${item.ref}　${text}`); else failed(item, text);
      setBusy(false);
      return;
    }
    setRemaining(null);
    setAsking(null);
    setBusy(false);
    finish(choice);
  };
  // A verdict shows at once and is sent after the undo window (N13). It is the verdict on the diagnosis that was
  // on the page when it was given: `send` is this render's, with this render's diagnosis.
  const later = (req: VerdictRequests, choice: VerdictChoice) => {
    setBusy(true);
    setError(null);
    defer({ label: `${item.ref}：${t("pend.verdict", { v: t(`verdict.${choice}`) })}`, send: () => void send(req, choice), undo: () => setBusy(false) });
  };
  const choose = (choice: VerdictChoice) => {
    if (busy || frame.readOnly || !fresh || !choiceAvailable(choice, rca)) return;
    setError(null);
    if (noteRequired(choice)) setAsking(choice); else later(verdictRequests(choice, rca, ""), choice);
  };
  const again = () => { if (!frame.readOnly) void agent.ask("rca"); };

  useBriefKeys({
    onKey: (key) => {
      if (asking) return false;
      if (key === " " && cause?.evidence.length) { openPeek(cause.evidence, 0); return true; }
      const hit = CHOICES.find(([, k]) => k.toLowerCase() === key);
      if (hit) { choose(hit[0]); return true; }
      if (key === "m") { again(); return true; }
      return false;
    },
    onEscape: () => { if (!asking) return false; setAsking(null); return true; },
  });

  const actions = asking ? (
    <ReasonForm label={t("reject.label")} placeholder={t(`verdict.ph.${asking}`)} note={t(`verdict.note.${asking}`)} submit={t("verdict.send")}
                busy={busy} error={error} onCancel={() => setAsking(null)}
                onSubmit={(reason) => later(verdictRequests(asking, rca, reason), asking)} />
  ) : (
    <>
      <button type="button" className="btn" disabled={agent.busy} onClick={again}><span className="t">{t("verdict.rerun")}</span><kbd>M</kbd></button>
      {remaining && <button type="button" className="btn" disabled={busy} onClick={() => void send(remaining.req, remaining.choice)}><span className="t">{t("act.retrySend")}</span></button>}
      {(error ?? agent.error) && <p className="note err wide" role="alert">{error ?? agent.error}</p>}
    </>
  );

  return (
    <BriefFrame item={item} {...frame} ask={t("ask.confirm")} actions={actions}>
      <AgentAtWork lane={agent.lane} now={frame.now} />
      <div className="sec">
        <h2>{t("sec.judgement")}</h2>
        {rcaQ.isPending ? <StateBlock kind="loading" />
          : rcaQ.isError ? <StateBlock kind="failed" failKey="sec.failedLoad" onRetry={() => void rcaQ.refetch()} />
          : cause ? <Cause cause={cause} gateNote={gateNote} /> : <p className="note">{t("cause.none")}</p>}
      </div>
      {!frame.readOnly && cause && (
        <div className="sec">
          <h2>{t("sec.verdict")}</h2>
          <div className="choices">
            {CHOICES.filter(([c]) => choiceAvailable(c, rca)).map(([c, k]) => (
              <button key={c} type="button" className="choice" disabled={busy || !fresh} onClick={() => choose(c)}><kbd>{k}</kbd>{t(`verdict.${c}`)}</button>
            ))}
          </div>
          <p className="note">{t("verdict.note")}</p>
        </div>
      )}
    </BriefFrame>
  );
}
