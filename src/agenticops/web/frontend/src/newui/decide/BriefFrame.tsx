import type { ReactNode } from "react";
import type { AttentionItem } from "@/lib/attention";
import { useNfT } from "../i18n";
import { toneOf } from "../lib/queue";
import { waitedText } from "./Queue";

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
  children: ReactNode;
}

/** One item's page: who it is, how long it has waited and where — then what is needed of you, the body, the actions. */
export function BriefFrame({ item, index, total, accountName, now, ask, actions, readOnly, children }: Props) {
  const t = useNfT();
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
        <span className="pos">{t("pos", { i: index + 1, n: total })}</span>
      </div>
      <h1>{item.title}</h1>
      <p className="ask"><b>{t("ask.lead")}</b>{ask}</p>
      {children}
      <div className="actions">{readOnly ? <span className="readonly-note">{t("readonly")}</span> : actions}</div>
    </>
  );
}
