import { useNfT } from "../../i18n";

/** The primary action of a brief that changes infrastructure: it must be held (pointer, Space / Enter on the button,
 *  or the A key — the brief feeds that one). The fill grows while it is held. */
export function HoldButton({ label, disabled, holding, hint, onDown, onUp, onCancel }: {
  label: string; disabled: boolean; holding: boolean; hint: boolean; onDown: (key?: string) => void; onUp: () => void; onCancel: () => void;
}) {
  const t = useNfT();
  const press = (e: React.KeyboardEvent) => { if ((e.key === " " || e.key === "Enter") && !e.repeat) { e.preventDefault(); onDown(e.key); } };
  const release = (e: React.KeyboardEvent) => { if (e.key === " " || e.key === "Enter") { e.preventDefault(); onUp(); } };
  return (
    <button type="button" className={`btn primary${holding ? " holding" : ""}`} disabled={disabled}
            onPointerDown={(e) => { if (e.button === 0) onDown(); }} onPointerUp={onUp} onPointerCancel={onCancel} onPointerLeave={onCancel}
            onKeyDown={press} onKeyUp={release} onBlur={onCancel} onContextMenu={(e) => e.preventDefault()}>
      <span className="fill" />
      <span className="t">{hint ? t("act.holdHint") : label}</span>
      <kbd>A</kbd>
    </button>
  );
}
