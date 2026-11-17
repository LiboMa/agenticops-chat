import { useState } from "react";
import { useIssueFeedback } from "@/hooks/useAgentMemory";
import { useAnomalyRca } from "@/hooks/useAnomalyRca";
import { useSettings } from "@/hooks/useSettings";
import { useRcaFeedback } from "@/hooks/useSignals";
import { parseItem } from "@/lib/inbox";
import { choiceAvailable, noteRequired, remainingRequests, verdictRequests, type VerdictChoice, type VerdictRequests } from "@/lib/verdict";
import { useTriggerRca } from "../../hooks/useIssueDecisions";
import { useNfT } from "../../i18n";
import { causeVm, pct } from "../../lib/briefs/cause";
import { StateBlock } from "../../shell/StateBlock";
import { useShell } from "../../shell/shellContext";
import { BriefFrame } from "../BriefFrame";
import { Cause } from "../widgets/Cause";
import { ReasonForm } from "../widgets/ReasonForm";
import { errorText, useBriefKeys, useDecide, type BriefProps } from "./briefContext";

const CHOICES: [VerdictChoice, string][] = [["correct", "Y"], ["partial", "P"], ["rcaWrong", "N"], ["falsePositive", "F"]];

/** A diagnosis that did not pass the auto-fix gate: a person says whether it is right. The four answers are the
 *  product's own (lib/verdict) and go to the same two endpoints as the classic page's «Your verdict». */
export function ConfirmBrief({ item, frame }: BriefProps) {
  const t = useNfT();
  const { notify } = useShell();
  const { done, openPeek } = useDecide();
  const issueId = parseItem(item.id)?.id ?? 0;
  const rcaQ = useAnomalyRca(issueId);
  const settings = useSettings();
  const rcaFb = useRcaFeedback(issueId);
  const issueFb = useIssueFeedback();
  const rerun = useTriggerRca(issueId);
  const [asking, setAsking] = useState<VerdictChoice | null>(null);     // a choice that needs a reason: the box is open
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [remaining, setRemaining] = useState<{ req: VerdictRequests; choice: VerdictChoice } | null>(null);

  const rca = rcaQ.data;
  const gate = settings.data?.rca_min_confidence_for_autofix;
  const cause = causeVm(rca, gate);
  const gateNote = !cause ? null : cause.belowGate ? t("gate.note", { gate: pct(gate) }) : cause.critic === "refuted" ? t("gate.critic") : t("gate.manual");

  const finish = (choice: VerdictChoice) => {
    if (choice === "falsePositive") return done(t("toast.closed", { ref: item.ref }));          // the item is dismissed: on to the next
    // the item stays with you — as «generate the plan» after «right», as «diagnose again» after «wrong»
    notify(choice === "rcaWrong" ? t("toast.verdict", { ref: item.ref, v: t("verdict.rcaWrong") }) : t("toast.verdict.correct", { ref: item.ref }));
  };
  const send = async (req: VerdictRequests, choice: VerdictChoice) => {
    setBusy(true);
    setError(null);
    try {
      if (req.rcaFeedback) await rcaFb.mutateAsync(req.rcaFeedback);
    } catch (e) {
      setError(t("err.failed", { msg: errorText(e) }));
      setBusy(false);
      return;
    }
    try {
      if (req.issueFeedback) await issueFb.mutateAsync({ issueId, feedback: req.issueFeedback });
    } catch (e) {
      const rest = remainingRequests(req, "issueFeedback");       // the diagnosis verdict is saved: only the rest is retried
      setRemaining(rest ? { req: rest, choice } : null);
      setError(t(rest ? "err.partial" : "err.failed", { msg: errorText(e) }));
      setBusy(false);
      return;
    }
    setRemaining(null);
    setAsking(null);
    setBusy(false);
    finish(choice);
  };
  const choose = (choice: VerdictChoice) => {
    if (busy || frame.readOnly || !choiceAvailable(choice, rca)) return;
    setError(null);
    if (noteRequired(choice)) setAsking(choice); else void send(verdictRequests(choice, rca, ""), choice);
  };
  const again = async () => {
    if (rerun.isPending || frame.readOnly) return;
    setError(null);
    try { await rerun.mutateAsync(); notify(t("toast.sentRca", { ref: item.ref })); }
    catch (e) { setError(t("err.failed", { msg: errorText(e) })); }
  };

  useBriefKeys({
    onKey: (key) => {
      if (asking) return false;
      if (key === " " && cause?.evidence.length) { openPeek(cause.evidence, 0); return true; }
      const hit = CHOICES.find(([, k]) => k.toLowerCase() === key);
      if (hit) { choose(hit[0]); return true; }
      if (key === "m") { void again(); return true; }
      return false;
    },
    onEscape: () => { if (!asking) return false; setAsking(null); return true; },
  });

  const actions = asking ? (
    <ReasonForm label={t("reject.label")} placeholder={t(`verdict.ph.${asking}`)} note={t(`verdict.note.${asking}`)} submit={t("verdict.send")}
                busy={busy} error={error} onCancel={() => setAsking(null)}
                onSubmit={(reason) => void send(verdictRequests(asking, rca, reason), asking)} />
  ) : (
    <>
      <button type="button" className="btn" disabled={rerun.isPending} onClick={() => void again()}><span className="t">{t("verdict.rerun")}</span><kbd>M</kbd></button>
      {remaining && <button type="button" className="btn" disabled={busy} onClick={() => void send(remaining.req, remaining.choice)}><span className="t">{t("act.retrySend")}</span></button>}
      {error && <p className="note err wide" role="alert">{error}</p>}
    </>
  );

  return (
    <BriefFrame item={item} {...frame} ask={t("ask.confirm")} actions={actions}>
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
              <button key={c} type="button" className="choice" disabled={busy} onClick={() => choose(c)}><kbd>{k}</kbd>{t(`verdict.${c}`)}</button>
            ))}
          </div>
          <p className="note">{t("verdict.note")}</p>
        </div>
      )}
    </BriefFrame>
  );
}
