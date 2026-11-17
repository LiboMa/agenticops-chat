import { useState } from "react";
import { useNfT } from "../../i18n";
import { pct, type CauseVm } from "../../lib/briefs/cause";
import { useDecide } from "../briefs/briefContext";

const LONG = 420;

/** A filled diamond = fetched or checked by code; a hollow one = inferred by a model. */
export function Prov({ code }: { code: boolean }) {
  const t = useNfT();
  return <span className={`prov ${code ? "code" : "model"}`} title={t(code ? "prov.code" : "prov.model")} />;
}

/** The diagnosis: what the model concluded, the evidence it cites (each opens beside the brief), and how far to trust
 *  it — the model's own confidence, the second model's review, the code's check of the location. */
export function Cause({ cause, gateNote }: { cause: CauseVm; gateNote?: string | null }) {
  const t = useNfT();
  const { openPeek } = useDecide();
  const long = cause.text.length > LONG;          // a real diagnosis can run to a page: six lines first, all of it on request
  const [open, setOpen] = useState(false);
  return (
    <>
      <p className={long && !open ? "clamp" : undefined}><Prov code={false} />{cause.text}</p>
      {long && <p><button type="button" className="more-btn" aria-expanded={open} onClick={() => setOpen(!open)}>{t(open ? "cause.less" : "cause.more")}</button></p>}
      {cause.evidence.length > 0 && (
        <p style={{ marginTop: 6 }}>
          {cause.evidence.map((e, i) => <button key={e.label} type="button" className="ev" onClick={() => openPeek(cause.evidence, i)}>{e.label}</button>)}
        </p>
      )}
      <div className="trust">
        <div className="tile"><small><Prov code={false} />{t("trust.self")}</small><b style={cause.belowGate ? { color: "var(--amber)" } : undefined}>{pct(cause.self)}</b></div>
        <div className="tile"><small><Prov code={false} />{t("trust.critic")}</small><b className="zh">{t(`critic.${cause.critic ?? "none"}`)}</b></div>
        <div className="tile"><small><Prov code />{t("trust.location")}</small><b className="zh">{t(`location.${cause.location ?? "none"}`)}</b></div>
      </div>
      {cause.evidenceGrounded !== null && <p className="note"><Prov code />{t(cause.evidenceGrounded ? "ev.grounded" : "ev.ungrounded")}</p>}
      {gateNote && <p className="note"><Prov code />{gateNote}</p>}
    </>
  );
}
