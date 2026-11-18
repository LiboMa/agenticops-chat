import { useEffect, useRef } from "react";
import { useNfT } from "../i18n";

/** The keys that work today, in the order a person meets them. A stage that adds a key adds its row. */
const ROWS: [string[], string][] = [
  [["J", "K"], "help.move"],
  [["A"], "help.primary"],
  [["R"], "help.reject"],
  [["D"], "help.close"],
  [["X"], "help.tick"],
  [["Y", "P", "N", "F", "M"], "help.verdict"],
  [["Space"], "help.peek"],
  [["↵"], "help.story"],
  [["E"], "help.steer"],
  [["A"], "help.live"],
  [["F", "G", "L", "H", "V"], "help.world"],
  [["1", "2", "3"], "help.lens"],
  [["/"], "help.cmd"],
  [["T"], "help.theme"],
  [["?"], "help.helpKey"],
  [["Esc"], "help.esc"],
];

/** The keyboard list («?»). A dialog: it takes the focus, keeps it, and gives it back when it closes. */
export function Help({ onClose }: { onClose: () => void }) {
  const t = useNfT();
  const ok = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const before = document.activeElement as HTMLElement | null;
    ok.current?.focus();
    return () => before?.focus?.();
  }, []);
  return (
    <div className="overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="dialog" role="dialog" aria-modal="true" aria-label={t("keys.open")}
           onKeyDown={(e) => { if (e.key === "Tab") { e.preventDefault(); ok.current?.focus(); } }}>
        <h2>{t("help.title")}</h2>
        <p>{t("help.p")}</p>
        <div className="keys">
          {ROWS.map(([keys, label]) => (
            <div key={label}>{keys.map((k) => <kbd key={k}>{k}</kbd>)}<span>{t(label)}</span></div>
          ))}
        </div>
        <div style={{ textAlign: "right", marginTop: 14 }}>
          <button ref={ok} type="button" className="btn" onClick={onClose}><span className="t">{t("help.ok")}</span><kbd>Esc</kbd></button>
        </div>
      </div>
    </div>
  );
}
