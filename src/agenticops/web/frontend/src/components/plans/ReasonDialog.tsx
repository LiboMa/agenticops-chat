import { useEffect, useRef, useState, type ReactNode } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { useLocale } from "@/i18n/LocaleContext";
import { canConfirm } from "@/lib/approval";
import { returnFocusTo } from "@/lib/focusReturn";

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

/** House-rule overlay: slideInRight + ESC. Captures a mandatory reason for approve / reject / cancel. A Radix dialog
 *  (S2 leftover): Tab stays inside, and on close focus goes back to the element that opened it — Radix itself only
 *  refocuses a Dialog.Trigger (lib/focusReturn). One ESC closes only this dialog; while busy, nothing closes it. */
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
  // mounted on open: the element focused at the first render is the opener
  const openerRef = useRef<HTMLElement | null>(
    typeof document !== "undefined" && document.activeElement instanceof HTMLElement && document.activeElement !== document.body
      ? document.activeElement : null,
  );

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
  return (
    <Dialog.Root open onOpenChange={(open) => { if (!open) close(); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 grid place-items-center bg-black/40 px-4 backdrop-blur-sm">
          <Dialog.Content {...(description ? {} : { "aria-describedby": undefined })}
                          onOpenAutoFocus={(e) => { e.preventDefault(); ref.current?.focus(); }}
                          onCloseAutoFocus={(e) => returnFocusTo(openerRef.current, e)}
                          className="relative w-full max-w-md rounded-xl border border-border bg-card shadow-2xl animate-[slideInRight_0.2s_ease-out]">
            <div className="px-6 py-4 border-b border-border">
              <Dialog.Title className="text-base font-semibold text-foreground">{title}</Dialog.Title>
              {description && <Dialog.Description className="text-sm text-muted-foreground mt-1">{description}</Dialog.Description>}
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
              <button type="button" onClick={close} disabled={busy} className="px-4 py-2 text-sm font-medium rounded-lg border border-border text-muted-foreground hover:bg-secondary transition-colors disabled:opacity-50">{t("common.cancel")}</button>
              <button type="button" onClick={() => onConfirm(reason.trim())} disabled={disabled}
                className={`px-4 py-2 text-sm font-medium rounded-lg text-white disabled:opacity-50 transition-colors ${variant === "destructive" ? "bg-red-600 hover:bg-red-700" : "bg-emerald-600 hover:bg-emerald-700"}`}>
                {busy ? "…" : confirmText}
              </button>
            </div>
          </Dialog.Content>
        </Dialog.Overlay>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
