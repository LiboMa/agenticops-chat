import { useState } from "react";
import { useNfT } from "../../i18n";
import { BriefFrame } from "../BriefFrame";
import { AgentAtWork } from "../widgets/AgentAtWork";
import { CauseSection, useCause } from "../widgets/CauseSection";
import { useBriefKeys, useDecide, type BriefProps } from "./briefContext";
import { DismissForm, useAgentAsk, VerdictQuote } from "./shared";

/** A diagnosis a person judged wrong — or an issue with no diagnosis at all: ask the agent to diagnose it (again). */
export function RerunBrief({ item, frame }: BriefProps) {
  const t = useNfT();
  const { openPeek } = useDecide();
  const agent = useAgentAsk(item);
  const source = useCause(agent.issueId);
  const [closing, setClosing] = useState(false);
  const missing = item.reason_detail === "rca_missing";

  useBriefKeys({
    onKey: (key, _e, repeat) => {
      if (closing) return false;
      if (key === " " && source.cause?.evidence.length) { openPeek(source.cause.evidence, 0); return true; }
      if (frame.readOnly) return false;
      if (key === "a") { if (!repeat) void agent.ask("rca"); return true; }
      if (key === "d") { agent.setError(null); setClosing(true); return true; }
      return false;
    },
    onEscape: () => { if (!closing) return false; setClosing(false); return true; },
  });

  const actions = closing ? <DismissForm item={item} onCancel={() => setClosing(false)} /> : (
    <>
      <button type="button" className="btn primary" disabled={agent.busy} onClick={() => void agent.ask("rca")}><span className="t">{t("act.rediagnose")}</span><kbd>A</kbd></button>
      <span className="spacer" />
      <button type="button" className="btn quiet" onClick={() => setClosing(true)}><span className="t">{t("act.close")}</span><kbd>D</kbd></button>
      {agent.error && <p className="note err wide" role="alert">{agent.error}</p>}
    </>
  );
  return (
    <BriefFrame item={item} {...frame} ask={t(missing ? "ask.rerun.missing" : "ask.rerun")} actions={actions}>
      <AgentAtWork lane={agent.lane} now={frame.now} />
      {!missing && (
        <div className="sec">
          <h2>{t("sec.humanVerdict")}</h2>
          <VerdictQuote issueId={agent.issueId} rcaId={source.rca?.id ?? null} />
          <p className="note">{t("rerun.note")}</p>
        </div>
      )}
      <CauseSection heading={t("sec.rejectedRca")} source={source} />
    </BriefFrame>
  );
}
