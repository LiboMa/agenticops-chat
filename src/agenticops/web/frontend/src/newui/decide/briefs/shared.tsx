import { useState } from "react";
import { useAuth } from "@/hooks/useAuth";
import { useIssueTimeline } from "@/hooks/useIssueTimeline";
import type { AttentionItem } from "@/lib/attention";
import { parseItem } from "@/lib/inbox";
import { useDismissIssue, useTriggerPlan, useTriggerRca } from "../../hooks/useIssueDecisions";
import { useNfT } from "../../i18n";
import { whoText } from "../../lib/activity";
import { humanVerdict, noteWasCut } from "../../lib/briefs/verdict";
import { utcStamp } from "../../lib/time";
import { useShell } from "../../shell/shellContext";
import { triggerError, useAgentOn } from "../widgets/AgentAtWork";
import { ReasonForm } from "../widgets/ReasonForm";
import { Quote } from "../widgets/RunSteps";
import { useDecision } from "./briefContext";

/** The reason box for dismissing an issue: the reason is kept with the status change; the note under the box says
 *  what else a dismissal does. */
export function DismissForm({ item, onCancel }: { item: AttentionItem; onCancel: () => void }) {
  const t = useNfT();
  const decide = useDecision(item);
  const dismiss = useDismissIssue(parseItem(item.id)?.id ?? 0);
  const [error, setError] = useState<string | null>(null);
  return (
    <ReasonForm label={t("close.label")} placeholder={t("close.placeholder")} note={t("close.note")} submit={t("act.close")}
                busy={dismiss.isPending} error={error} onCancel={onCancel}
                onSubmit={async (reason) => {
                  setError(null);
                  setError(await decide(() => dismiss.mutateAsync(reason), t("toast.closed", { ref: item.ref }), undefined, t("pend.dismiss")));
                }} />
  );
}

/** Asking an agent for a diagnosis or a plan from a brief. `lane` is the agent already on this item (the server's
 *  record): while there is one, nothing can be asked again — here, in another tab, or by someone else. */
export function useAgentAsk(item: AttentionItem) {
  const t = useNfT();
  const { notify, defer } = useShell();
  const issueId = parseItem(item.id)?.id ?? 0;
  const [waiting, setWaiting] = useState(false);       // asked, and still inside its undo window (N13)
  const lane = useAgentOn(item.id);
  const rca = useTriggerRca(issueId);
  const plan = useTriggerPlan(issueId);
  const [error, setError] = useState<string | null>(null);
  // an agent within its time limit keeps the item; one past it does not (N11) — asking again takes the item over,
  // and the old run is recorded as abandoned
  const busy = waiting || rca.isPending || plan.isPending || (!!lane && !lane.overdue);
  const send = async (what: "rca" | "plan") => {
    setWaiting(false);
    try {
      await (what === "rca" ? rca : plan).mutateAsync();
      notify(t(what === "rca" ? "toast.sentRca" : "toast.sentPlan", { ref: item.ref }));
    } catch (e) {
      const text = triggerError(e, t);
      setError(text);
      notify(`${item.ref}　${text}`);               // the brief may be gone by now: a refusal is always said
    }
  };
  const ask = async (what: "rca" | "plan") => {
    if (busy) return;
    setError(null);
    setWaiting(true);
    defer({ label: `${item.ref}：${t(what === "rca" ? "pend.rca" : "pend.plan")}`, send: () => void send(what), undo: () => setWaiting(false) });
  };
  return { issueId, lane, busy, error, setError, ask };
}

/** What a person made of the issue's diagnosis, quoted from the timeline: who, what, when, and their note. */
export function VerdictQuote({ issueId, rcaId }: { issueId: number; rcaId: number | null }) {
  const t = useNfT();
  const { user } = useAuth();
  const timeline = useIssueTimeline(issueId);
  const v = humanVerdict(timeline.data, rcaId);
  if (timeline.isPending) return <div className="skel" style={{ height: 40 }} />;
  if (!v) return <p className="note">{t("verdict.none")}</p>;
  const cite = t("verdict.cite", { by: whoText(v.by, user?.email, t), v: t(`verdict.word.${v.verdict}`), t: utcStamp(v.at) });
  return <Quote text={(v.note || "—") + (noteWasCut(v.note) ? t("verdict.cut") : "")} cite={cite} />;
}
