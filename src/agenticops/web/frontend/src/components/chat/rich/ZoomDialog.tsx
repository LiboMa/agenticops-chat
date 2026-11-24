import { useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { useLocale } from "@/i18n/LocaleContext";

interface Props {
  title: string;
  onClose: () => void;
  /** false = no zoom controls (a chart re-lays itself out; a flowchart is scaled) */
  zoomable?: boolean;
  children: ReactNode;
}

const STEPS = [0.5, 0.75, 1, 1.25, 1.5, 2, 3];

/** A chart or flowchart, enlarged (house rule: slides in, ESC closes). A portal: chat rows are positioned with
 *  transform (virtualized), which would make `fixed` relative to the row. Full screen below 768px. */
export function ZoomDialog({ title, onClose, zoomable = true, children }: Props) {
  const { t } = useLocale();
  const [step, setStep] = useState(2);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    box.current?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  const btn = "rounded px-2 py-1 text-sm text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-40";
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 md:p-6" onClick={onClose}>
      <div ref={box} tabIndex={-1} role="dialog" aria-modal="true" aria-label={title} onClick={(e) => e.stopPropagation()}
           className="flex h-full w-full flex-col bg-background shadow-xl outline-none animate-[slideInRight_0.2s_ease-out] md:h-auto md:max-h-[90vh] md:max-w-5xl md:rounded-xl">
        <div className="flex items-center gap-1 border-b border-border px-3 py-2">
          <span className="min-w-0 flex-1 truncate text-sm font-medium text-foreground">{title}</span>
          {zoomable && (
            <>
              <button type="button" className={btn} disabled={step === 0} onClick={() => setStep((s) => s - 1)}
                      aria-label={t("chat.rich.zoomOut")} title={t("chat.rich.zoomOut")}>−</button>
              <button type="button" className={btn} onClick={() => setStep(2)} title={t("chat.rich.zoomFit")}>
                {Math.round(STEPS[step] * 100)}%
              </button>
              <button type="button" className={btn} disabled={step === STEPS.length - 1} onClick={() => setStep((s) => s + 1)}
                      aria-label={t("chat.rich.zoomIn")} title={t("chat.rich.zoomIn")}>+</button>
            </>
          )}
          <button type="button" className={btn} onClick={onClose} aria-label={t("chat.rich.close")}>✕</button>
        </div>
        <div className="min-h-0 flex-1 overflow-auto p-4">
          {zoomable
            ? <div className="aiops-zoom" style={{ width: `${STEPS[step] * 100}%` }}>{children}</div>
            : children}
        </div>
      </div>
    </div>,
    document.body,
  );
}
