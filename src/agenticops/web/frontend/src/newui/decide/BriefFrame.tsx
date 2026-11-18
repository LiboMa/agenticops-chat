import type { ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import type { AttentionItem } from "@/lib/attention";
import { useItemRefresh } from "../hooks/useItemData";
import { useNfT } from "../i18n";
import { toneOf } from "../lib/queue";
import { storyPath } from "../lib/story";
import { utcHm } from "../lib/time";
import type { Later } from "./briefs/briefContext";
import { waitedText } from "./Queue";
import { useAgentOn } from "./widgets/AgentAtWork";

interface Props {
  item: AttentionItem;
  /** where it stands in the list: "7 / 140" */
  index: number;
  total: number;
  accountName: string | null;
  now: number;
  /** the one sentence under the title: what is needed of you */
  ask: string;
  /** the action row; a read-only account gets a sentence instead */
  actions: ReactNode;
  readOnly: boolean;
  /** «later» (N14): put this item off / take that back. Absent where there is no queue to move it in */
  later?: Later;
  children: ReactNode;
}

/** One item's page: who it is, how long it has waited and where — then what is needed of you, the body, the actions. */
export function BriefFrame({ item, index, total, accountName, now, ask, actions, readOnly, later, children }: Props) {
  const t = useNfT();
  const location = useLocation();
  useItemRefresh(item.id, useAgentOn(item.id));
  const tone = toneOf(item);
  const sev = item.severity ? t(`sev.${item.severity}`) : item.entity.entity_type === "change_request"
    ? `${t("sev.change")}${item.risk_level ? ` ${item.risk_level}` : ""}` : "";
  const place = [accountName, item.region].filter(Boolean).join("　");
  return (
    <>
      <div className="meta">
        <span className="ref">{item.ref}</span>
        {sev && <span className={`sev ${tone}`}>{sev}</span>}
        <span>{waitedText(item.occurred_at, now, t)}</span>
        {place && <span>{place}</span>}
        <Link className="story-link" to={storyPath(item.id)} state={{ from: "decide", back: location.pathname + location.search }}>
          {t("act.story")}<kbd>↵</kbd>
        </Link>
        {later && !readOnly && (
          <button type="button" className="story-link" disabled={later.busy} aria-pressed={later.until !== null} onClick={later.toggle}>
            {t(later.until ? "act.unsnooze" : "act.snooze")}<kbd>S</kbd>
          </button>
        )}
        <span className="pos">{t("pos", { i: index + 1, n: total })}</span>
      </div>
      {later?.until && <p className="note later" role="status">{t("snoozed.until", { t: utcHm(later.until) })}</p>}
      <h1>{item.title}</h1>
      <p className="ask"><b>{t("ask.lead")}</b>{ask}</p>
      {children}
      <div className="actions">{readOnly ? <span className="readonly-note">{t("readonly")}</span> : actions}</div>
    </>
  );
}
