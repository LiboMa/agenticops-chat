import { useNfT } from "../i18n";

/** A decision that has been made and not sent yet: what it is, the time it has left, and «undo» (key Z). The bar
 *  runs down in the five seconds the decision waits; `due` restarts it for each new decision. */
export function PendingToast({ label, due, onUndo }: { label: string; due: number; onUndo: () => void }) {
  const t = useNfT();
  return (
    <div className="toast count" role="status" key={due}>
      <span className="spark" aria-hidden="true" />
      <span className="msg">{t("pend.line", { what: label })}</span>
      <button type="button" onClick={onUndo}>{t("pend.undo")}<kbd>Z</kbd></button>
      <i className="cd" aria-hidden="true" />
    </div>
  );
}
