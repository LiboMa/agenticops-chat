import { Link } from "react-router-dom";
import { useLocale } from "@/i18n/LocaleContext";
import { reasonKey, safeRoute } from "@/lib/attention";
import { useNfT } from "../i18n";
import { BriefFrame } from "./BriefFrame";
import type { BriefProps } from "./briefs/briefContext";

/** The page for an item this interface has no brief of its own for (a row a newer server sends): what it waits for,
 *  which resource, and the classic page where it can be handled — never a blank. */
export function GenericBrief({ item, frame }: BriefProps) {
  const t = useNfT();
  const { t: classic } = useLocale();
  const res = item.resource;
  const route = safeRoute(item.route);
  return (
    <BriefFrame item={item} {...frame} readOnly={false} ask={t("generic.ask")}
                actions={route ? <Link className="btn primary" to={route}><span className="t">{t("generic.open")}</span></Link> : null}>
      <div className="sec">
        <h2>{t("generic.sec.what")}</h2>
        <p>{classic(reasonKey(item))}</p>
      </div>
      <div className="sec">
        <h2>{t("generic.sec.resource")}</h2>
        {res ? (
          <dl className="res">
            <dt>{res.type}</dt><dd>{res.name || res.resource_id}</dd>
            {res.name && <><dt>ID</dt><dd className="mono">{res.resource_id}</dd></>}
          </dl>
        ) : <p className="note">{t("generic.noResource")}</p>}
      </div>
    </BriefFrame>
  );
}
