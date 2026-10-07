import { useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { useLocale } from "@/i18n/LocaleContext";
import { canConfirm } from "@/lib/approval";

interface Props {
  title: string;
  description?: string;
  confirmText: string;
  variant?: "default" | "destructive";
  required?: boolean;
  busy?: boolean;
  /** Shown inside the body; the dialog stays open. The caller clears it on the next confirm. */
  error?: string | null;
  maxLength?: number;
  /** Rendered in the body above the reason label (Task 6's claimed-approver input). */
  children?: ReactNode;
  /** An acknowledgement the confirm waits for (approvals, MVP-2.7.0 S3). */
  ack?: string;
  onConfirm: (reason: string) => void;
  onClose: () => void;
}

/** House-rule overlay: slideInRight + ESC. Captures a mandatory reason for approve / reject / cancel. */
export function ReasonDialog({
  title,
  description,
  confirmText,
  variant = "default",
  required = true,
  busy = false,
  error = null,
  maxLength = 2000,
  children,
  ack,
  onConfirm,
  onClose,
}: Props) {
  const { t } = useLocale();
  const [reason, setReason] = useState("");
  const [acked, setAcked] = useState(false);
  const ref = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    ref.current?.focus();
  }, []);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.stopPropagation(); // one ESC closes only this dialog, not the ContextPanel under it (F7)
      if (!busy) onClose(); // while busy, ESC does nothing
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [busy, onClose]);

  const close = () => {
    if (!busy) onClose();
  };
  const disabled = !canConfirm({ busy, required, reason, ack: !!ack, acked });
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="fixed inset-0 bg-black/40 backdrop-blur-sm" onClick={close} />
      <div className="relative bg-card border border-border rounded-xl shadow-2xl w-full max-w-md mx-4 animate-[slideInRight_0.2s_ease-out]">
        <div className="px-6 py-4 border-b border-border">
          <h3 className="text-base font-semibold text-foreground">{title}</h3>
          {description && <p className="text-sm text-muted-foreground mt-1">{description}</p>}
        </div>
        <div className="px-6 py-4">
          {children}
          <label className="block text-xs font-medium uppercase tracking-wider text-muted-foreground mb-1">
            {t("plans.reason")}{required && " *"}
          </label>
          <textarea ref={ref} value={reason} onChange={(e) => setReason(e.target.value)} rows={3} maxLength={maxLength}
            placeholder={t("plans.reasonPlaceholder")}
            className="w-full border border-border bg-background text-foreground rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50" />
          {error && <p role="alert" className="text-sm text-red-500 mt-2">{error}</p>}
          {ack && (
            <label className="mt-3 flex items-start gap-2 text-sm text-foreground">
              <input type="checkbox" checked={acked} onChange={(e) => setAcked(e.target.checked)} className="mt-0.5" />
              <span>{ack}</span>
            </label>
          )}
        </div>
        <div className="px-6 py-4 border-t border-border flex justify-end gap-2">
          <button onClick={close} disabled={busy} className="px-4 py-2 text-sm font-medium rounded-lg border border-border text-muted-foreground hover:bg-secondary transition-colors disabled:opacity-50">{t("common.cancel")}</button>
          <button onClick={() => onConfirm(reason.trim())} disabled={disabled}
            className={`px-4 py-2 text-sm font-medium rounded-lg text-white disabled:opacity-50 transition-colors ${variant === "destructive" ? "bg-red-600 hover:bg-red-700" : "bg-emerald-600 hover:bg-emerald-700"}`}>
            {busy ? "…" : confirmText}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
