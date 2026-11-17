import type { ReactNode } from "react";
import { useNfT } from "../i18n";

/** The states of any data module, drawn one way everywhere: loading, and failed. A failure says what it does NOT
 *  mean on this screen (`failKey`) — a failed request is never «nothing there». Empty states are each screen's own. */
export function StateBlock({ kind, failKey = "state.failed.p", onRetry }:
    { kind: "loading" | "failed"; failKey?: string; onRetry?: () => void }) {
  const t = useNfT();
  if (kind === "loading") {
    return (
      <div className="state" role="status" aria-busy="true">
        <div className="skel" style={{ width: "60%", height: 22 }} />
        <div className="skel" style={{ width: "86%", marginTop: 14 }} />
        <div className="skel" style={{ width: "74%", marginTop: 8 }} />
        <p>{t("state.loading")}</p>
      </div>
    );
  }
  return (
    <div className="state failed" role="alert">
      <div className="big">{t("state.failed")}</div>
      <p>{t(failKey)}</p>
      {onRetry && <p><button type="button" className="btn" onClick={onRetry}><span className="t">{t("state.retry")}</span></button></p>}
    </div>
  );
}

/** A plain centred message: a headline, a sentence, and what to do next. */
export function Message({ big, children }: { big: string; children?: ReactNode }) {
  return <div className="state"><div className="big">{big}</div>{children}</div>;
}
