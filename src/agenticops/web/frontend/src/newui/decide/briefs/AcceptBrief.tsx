import { useState } from "react";
import { useAcceptExecution } from "@/hooks/useFixExecutions";
import { useFixPlan } from "@/hooks/useFixPlans";
import { useIssueExecutions } from "@/hooks/useIssueExecutions";
import { parseItem } from "@/lib/inbox";
import { useNfT } from "../../i18n";
import { runToAccept } from "../../lib/briefs/accept";
import { Message, StateBlock } from "../../shell/StateBlock";
import { BriefFrame } from "../BriefFrame";
import { AcceptBody, useAcceptChecklist } from "../widgets/AcceptBody";
import { ReasonForm } from "../widgets/ReasonForm";
import { useBriefKeys, useDecision, type BriefProps } from "./briefContext";

/** A run that succeeded but that the code could not call «passed»: a person looks at the checks that have no result
 *  or a warning, ticks each, and accepts — or says what is wrong. The ticked checks go into the audit trail. */
export function AcceptBrief({ item, frame }: BriefProps) {
  const t = useNfT();
  const decide = useDecision(item);
  const issueId = parseItem(item.id)?.id ?? 0;
  const runsQ = useIssueExecutions(issueId);
  const run = runToAccept(runsQ.data);
  const planQ = useFixPlan(run?.fix_plan_id ?? 0);            // the run's own plan, not the issue's current one
  const accept = useAcceptExecution();
  const list = useAcceptChecklist(run, planQ.data ?? null);
  const [form, setForm] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const send = async (decision: "accepted" | "rejected", reason: string) => {
    if (!run) return;
    setError(null);
    setError(await decide(
      () => accept.mutateAsync({ id: run.id, decision, reason, ...(decision === "accepted" ? { confirmed_checks: list.confirmed() } : {}) }),
      t(decision === "accepted" ? "toast.accepted" : "toast.notAccepted", { ref: item.ref })));
  };
  const acceptNow = () => { if (list.ready && !accept.isPending) void send("accepted", list.reason()); };

  useBriefKeys({
    onKey: (key, _e, repeat) => {
      if (form || frame.readOnly || !run) return false;
      if (key === "a") { if (!repeat) acceptNow(); return true; }
      if (key === "x") { list.tickNext(); return true; }
      if (key === "r") { setError(null); setForm(true); return true; }
      return false;
    },
    onEscape: () => { if (!form) return false; setForm(false); return true; },
  });

  const n = list.vm?.toVerify.length ?? 0;
  const actions = form ? (
    <ReasonForm label={t("reject.label")} placeholder={t("fail.placeholder")} note={t("accept.rejectNote")} submit={t("act.rejectAccept")}
                busy={accept.isPending} error={error} onCancel={() => setForm(false)} onSubmit={(reason) => void send("rejected", reason)} />
  ) : (
    <>
      <button type="button" className="btn primary" disabled={!list.ready || accept.isPending} onClick={acceptNow}><span className="t">{t("act.accept")}</span><kbd>A</kbd></button>
      <button type="button" className="btn" disabled={!run || list.ready} onClick={list.tickNext}><span className="t">{t("act.tick")}</span><kbd>X</kbd></button>
      <button type="button" className="btn" disabled={!run} onClick={() => { setError(null); setForm(true); }}><span className="t">{t("act.rejectAccept")}</span><kbd>R</kbd></button>
      {error && <p className="note err wide" role="alert">{error}</p>}
    </>
  );
  return (
    <BriefFrame item={item} {...frame} ask={n > 0 ? t("ask.accept", { n }) : t("ask.accept.none")} actions={actions}>
      {runsQ.isPending ? <StateBlock kind="loading" />
        : runsQ.isError ? <StateBlock kind="failed" failKey="sec.failedLoad" onRetry={() => void runsQ.refetch()} />
        : !list.vm ? <Message big={t("accept.none")} />
        : <AcceptBody list={list} readOnly={frame.readOnly} item={item.id} now={frame.now} />}
    </BriefFrame>
  );
}
