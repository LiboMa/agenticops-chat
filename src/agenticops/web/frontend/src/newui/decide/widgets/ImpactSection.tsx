import { useGraphFocus } from "@/hooks/useGraphFocus";
import type { FocusSubject } from "@/lib/localGraph";
import { useNfT } from "../../i18n";
import { Prov } from "./Cause";

/** «What it touches»: the three blast-radius numbers of the relation graph around the item's resource — connected
 *  directly, possibly affected, already in trouble. The numbers are the API's; an item with no resource on the graph
 *  says so instead of showing zeros. */
export function ImpactSection({ subject, tone }: { subject: FocusSubject; tone: "red" | "amber" | "violet" }) {
  const t = useNfT();
  const q = useGraphFocus(subject);
  const focus = q.data;
  const fan = focus ? Math.min(focus.blast.structural, 6) : 0;
  return (
    <div className="sec">
      <h2>{t("sec.impact")}</h2>
      {q.isPending ? <div className="skel" style={{ height: 54 }} />
        : q.isError || !focus ? <p className="note err">{t("sec.failedLoad")}</p>
        : focus.anchor.status !== "anchored" ? <p className="note">{t("impact.unanchored")}</p>
        : (
          <div className="impact">
            <svg width="150" height="84" viewBox="0 0 150 84" role="img" aria-label={t("impact.fan")}>
              {Array.from({ length: fan }, (_, k) => {
                const y = fan === 1 ? 42 : 12 + k * (60 / (fan - 1));
                return <g key={k}><line x1="20" y1="42" x2="124" y2={y} stroke={`var(--${tone})`} strokeOpacity=".55" /><circle cx="124" cy={y} r="4" fill="var(--chalk)" fillOpacity=".85" /></g>;
              })}
              <circle cx="20" cy="42" r="6" fill={`var(--${tone})`} /><circle cx="20" cy="42" r="11" fill="none" stroke={`var(--${tone})`} strokeOpacity=".5" />
            </svg>
            <div>
              <div className="nums">
                <div><b>{focus.blast.structural}</b>{t("impact.structural")}</div>
                <div><b>{focus.blast.potential}</b>{t("impact.potential")}</div>
                <div><b>{focus.blast.observed}</b>{t("impact.observed")}</div>
              </div>
              <p className="note"><Prov code />{t("impact.note")}{focus.blast.truncated ? ` ${t("impact.truncated")}` : ""}</p>
            </div>
          </div>
        )}
    </div>
  );
}
