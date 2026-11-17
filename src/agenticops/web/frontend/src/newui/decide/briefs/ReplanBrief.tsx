import { useState } from "react";
import { useAuth } from "@/hooks/useAuth";
import { useFixPlans } from "@/hooks/useFixPlans";
import { currentFixPlan } from "@/lib/issuePhases";
import { useNfT } from "../../i18n";
import { whoText } from "../../lib/activity";
import { utcStamp } from "../../lib/time";
import { StateBlock } from "../../shell/StateBlock";
import { BriefFrame } from "../BriefFrame";
import { AgentAtWork } from "../widgets/AgentAtWork";
import { CauseSection, useCause } from "../widgets/CauseSection";
import { PlanSection } from "../widgets/PlanSection";
import { Quote } from "../widgets/RunSteps";
import { useBriefKeys, useDecide, type BriefProps } from "./briefContext";
import { DismissForm, useAgentAsk } from "./shared";

/** A fix plan a person sent back (or withdrew after approving): the reason they gave, the plan it was, and the way
 *  to a new one — the agent asked for it is given that reason. */
export function ReplanBrief({ item, frame }: BriefProps) {
  const t = useNfT();
  const { user } = useAuth();
  const { openPeek } = useDecide();
  const agent = useAgentAsk(item);
  const source = useCause(agent.issueId);
  const plansQ = useFixPlans({ health_issue_id: agent.issueId, kind: "fix" });
  const [closing, setClosing] = useState(false);
  const plan = currentFixPlan(plansQ.data);
  const sentBack = plan && plan.status === "rejected" ? plan : null;
  const reason = sentBack?.rejection_reason?.trim() ?? "";

  useBriefKeys({
    onKey: (key, _e, repeat) => {
      if (closing) return false;
      if (key === " " && source.cause?.evidence.length) { openPeek(source.cause.evidence, 0); return true; }
      if (frame.readOnly) return false;
      if (key === "a") { if (!repeat) void agent.ask("plan"); return true; }
      if (key === "d") { agent.setError(null); setClosing(true); return true; }
      return false;
    },
    onEscape: () => { if (!closing) return false; setClosing(false); return true; },
  });

  const actions = closing ? <DismissForm item={item} onCancel={() => setClosing(false)} /> : (
    <>
      <button type="button" className="btn primary" disabled={agent.busy} onClick={() => void agent.ask("plan")}>
        <span className="t">{t(reason ? "act.replan" : "act.newPlan")}</span><kbd>A</kbd>
      </button>
      <span className="spacer" />
      <button type="button" className="btn quiet" onClick={() => setClosing(true)}><span className="t">{t("act.close")}</span><kbd>D</kbd></button>
      {agent.error && <p className="note err wide" role="alert">{agent.error}</p>}
    </>
  );
  return (
    <BriefFrame item={item} {...frame} ask={t("ask.replan")} actions={actions}>
      <AgentAtWork lane={agent.lane} now={frame.now} />
      {plansQ.isPending ? <StateBlock kind="loading" />
        : plansQ.isError ? <StateBlock kind="failed" failKey="sec.failedLoad" onRetry={() => void plansQ.refetch()} />
        : sentBack && (
          <>
            <div className="sec">
              <h2>{t("sec.whoRejected")}</h2>
              {reason ? (
                <>
                  <Quote text={reason} cite={t("rejected.cite", { by: whoText(sentBack.rejected_by, user?.email, t), t: utcStamp(sentBack.rejected_at) })} />
                  <p className="note">{t("replan.note")}</p>
                </>
              ) : <p className="note">{t("replan.noReason")}</p>}
            </div>
            <PlanSection plan={sentBack} heading={t("sec.rejectedPlan", { v: sentBack.plan_version || 1 })} kind="fix" rollback={false} />
          </>
        )}
      <CauseSection heading={t("sec.why")} source={source} />
    </BriefFrame>
  );
}
