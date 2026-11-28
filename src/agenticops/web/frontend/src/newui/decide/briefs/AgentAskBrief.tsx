import { type ReactNode, useState } from "react";
import { useNfT } from "../../i18n";
import { BriefFrame } from "../BriefFrame";
import { LiveSteps } from "../../live/LiveSteps";
import { AgentAtWork } from "../widgets/AgentAtWork";
import { Prov } from "../widgets/Cause";
import { useCause } from "../widgets/CauseSection";
import { useBriefKeys, useDecide, type BriefProps } from "./briefContext";
import { DismissForm, useAgentAsk } from "./shared";

type Ask = "rca" | "plan";

/** What one of the «ask an agent» briefs says — the words come from the brief, so each keeps its own keys. */
export interface AgentAskSpec {
  /** the primary button and key A; `second` = one more button and key M */
  main: { ask: Ask; label: string };
  second?: { ask: Ask; label: string };
  /** the brief's one question */
  question: string;
  /** the agent's last run ended without a result: the section that says so, and the steps it left */
  stopped?: { heading: string; text: string; agent: "rca" | "sre" };
}

/** The body the briefs that ask an agent for work share (review of MVP-2.9.0, ④ — RerunBrief and GenerateBrief were
 *  two copies of it): the keys (A asks, M the second ask, D closes the issue, Space opens the evidence), the
 *  buttons, the agent already at work, the run that ended without a result; the brief's own sections come after. */
export function AgentAskBrief({ item, frame, spec, children }: BriefProps & {
  spec: AgentAskSpec;
  children: (ctx: { issueId: number; source: ReturnType<typeof useCause> }) => ReactNode;
}) {
  const t = useNfT();
  const { openPeek } = useDecide();
  const agent = useAgentAsk(item);
  const source = useCause(agent.issueId);
  const [closing, setClosing] = useState(false);
  const { main, second, stopped } = spec;

  useBriefKeys({
    onKey: (key, _e, repeat) => {
      if (closing) return false;
      if (key === " " && source.cause?.evidence.length) { openPeek(source.cause.evidence, 0); return true; }
      if (frame.readOnly) return false;
      if (key === "a") { if (!repeat) void agent.ask(main.ask); return true; }
      if (second && key === "m") { if (!repeat) void agent.ask(second.ask); return true; }
      if (key === "d") { agent.setError(null); setClosing(true); return true; }
      return false;
    },
    onEscape: () => { if (!closing) return false; setClosing(false); return true; },
  });

  const actions = closing ? <DismissForm item={item} onCancel={() => setClosing(false)} /> : (
    <>
      <button type="button" className="btn primary" disabled={agent.busy} onClick={() => void agent.ask(main.ask)}><span className="t">{main.label}</span><kbd>A</kbd></button>
      {second && <button type="button" className="btn" disabled={agent.busy} onClick={() => void agent.ask(second.ask)}><span className="t">{second.label}</span><kbd>M</kbd></button>}
      <span className="spacer" />
      <button type="button" className="btn quiet" onClick={() => setClosing(true)}><span className="t">{t("act.close")}</span><kbd>D</kbd></button>
      {agent.error && <p className="note err wide" role="alert">{agent.error}</p>}
    </>
  );
  return (
    <BriefFrame item={item} {...frame} ask={spec.question} actions={actions}>
      <AgentAtWork lane={agent.lane} now={frame.now} />
      {stopped && (
        <>
          <div className="sec">
            <h2>{stopped.heading}</h2>
            <p><Prov code />{stopped.text}</p>
          </div>
          {/* what the code recorded of that run, if it ran after steps began to be recorded */}
          <LiveSteps of={{ item: item.id, agent: stopped.agent, before: item.occurred_at }} live={false} now={frame.now} heading={t("steps.title.stopped")} />
        </>
      )}
      {children({ issueId: agent.issueId, source })}
    </BriefFrame>
  );
}
