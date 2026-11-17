import { useRef, useState } from "react";
import { useNfT } from "../../i18n";

/** The one reason box of a brief, in place of its action row: every «no» needs a reason. Enter sends, Esc closes
 *  (the brief's own Escape handler does that). An empty reason is not sent; the box says so. */
export function ReasonForm({ label, placeholder, note, submit, busy, error, onSubmit, onCancel }: {
  label: string; placeholder: string; note?: string; submit: string; busy: boolean; error: string | null;
  onSubmit: (reason: string) => void; onCancel: () => void;
}) {
  const t = useNfT();
  const [value, setValue] = useState("");
  const [missing, setMissing] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  return (
    <form className="reason" onSubmit={(e) => {
      e.preventDefault();
      const reason = value.trim();
      if (!reason) { setMissing(true); input.current?.focus(); return; }
      onSubmit(reason);
    }}>
      <input ref={input} className="field" autoFocus value={value} maxLength={2000} aria-label={label} aria-invalid={missing}
             placeholder={missing ? t("reject.required") : placeholder}
             onChange={(e) => { setValue(e.target.value); setMissing(false); }} />
      <button type="submit" className="btn primary" disabled={busy}><span className="t">{submit}</span><kbd>↵</kbd></button>
      <button type="button" className="btn" onClick={onCancel}><span className="t">{t("act.cancel")}</span><kbd>Esc</kbd></button>
      {note && <p className="note">{note}</p>}
      {error && <p className="note err" role="alert">{error}</p>}
    </form>
  );
}
