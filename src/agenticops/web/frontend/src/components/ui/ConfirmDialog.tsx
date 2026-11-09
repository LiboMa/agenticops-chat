import { useEffect, useId, useRef, useCallback, useState } from "react";
import { createPortal } from "react-dom";
import { useLocale } from "@/i18n/LocaleContext";

interface ConfirmDialogProps {
  message: string;
  title?: string;
  confirmText?: string;
  cancelText?: string;
  variant?: "default" | "destructive";
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmDialog({
  message,
  title,
  confirmText = "Confirm",
  cancelText = "Cancel",
  variant = "default",
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const cancelRef = useRef<HTMLButtonElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);
  // MVP-2.8.0 S2 rework: a modal alert dialog — Tab stays on its two buttons, and focus goes back to whatever had it
  // when the dialog opened (it fell to <body>; the E2E found it on the user management page's confirmations)
  const openerRef = useRef<HTMLElement | null>(
    typeof document !== "undefined" && document.activeElement instanceof HTMLElement && document.activeElement !== document.body
      ? document.activeElement : null,
  );
  const ids = useId();

  useEffect(() => {
    cancelRef.current?.focus();
    const opener = openerRef.current;
    return () => { if (opener?.isConnected) opener.focus(); };
  }, []);

  const keepTab = (e: React.KeyboardEvent) => {
    if (e.key !== "Tab") return;
    e.preventDefault();
    (document.activeElement === cancelRef.current ? confirmRef.current : cancelRef.current)?.focus();
  };

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.stopPropagation(); // one ESC closes only this dialog, not the panel under it (as ReasonDialog, F7)
      onCancel();
    };
    window.addEventListener("keydown", handler, true);
    return () => window.removeEventListener("keydown", handler, true);
  }, [onCancel]);

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="fixed inset-0 bg-black/50 backdrop-blur-sm" onClick={onCancel} />
      <div role="alertdialog" aria-modal="true" aria-labelledby={title ? `${ids}-t` : undefined} aria-describedby={`${ids}-m`}
           onKeyDown={keepTab}
           className="relative bg-card border border-border rounded-lg shadow-lg p-6 max-w-sm w-full mx-4 animate-in fade-in zoom-in-95 duration-150">
        {title && (
          <h3 id={`${ids}-t`} className="text-base font-semibold text-foreground mb-1">{title}</h3>
        )}
        <p id={`${ids}-m`} className="text-sm text-muted-foreground mb-6 [overflow-wrap:anywhere]">{message}</p>
        <div className="flex justify-end gap-2">
          <button
            ref={cancelRef}
            onClick={onCancel}
            className="px-4 py-2 text-sm font-medium rounded-lg border border-border text-muted-foreground bg-background hover:bg-secondary transition-colors"
          >
            {cancelText}
          </button>
          <button
            ref={confirmRef}
            onClick={onConfirm}
            className={`px-4 py-2 text-sm font-medium rounded-lg transition-colors ${
              variant === "destructive"
                ? "bg-red-600 text-white hover:bg-red-700"
                : "bg-primary text-primary-foreground hover:bg-primary/90"
            }`}
          >
            {confirmText}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}

interface ConfirmOptions {
  title?: string;
  confirmText?: string;
  cancelText?: string;
  variant?: "default" | "destructive";
}

export function useConfirm() {
  const { t } = useLocale();   // the buttons in the page's language unless a caller names them (it read «Cancel» in zh)
  const [state, setState] = useState<(ConfirmOptions & { message: string }) | null>(null);
  const resolveRef = useRef<(v: boolean) => void>();

  const confirm = useCallback((message: string, options?: ConfirmOptions): Promise<boolean> => {
    return new Promise<boolean>((resolve) => {
      resolveRef.current = resolve;
      setState({ message, ...options });
    });
  }, []);

  const handleConfirm = useCallback(() => {
    resolveRef.current?.(true);
    setState(null);
  }, []);

  const handleCancel = useCallback(() => {
    resolveRef.current?.(false);
    setState(null);
  }, []);

  const dialog = state ? (
    <ConfirmDialog
      message={state.message}
      title={state.title}
      confirmText={state.confirmText ?? t("common.confirm")}
      cancelText={state.cancelText ?? t("common.cancel")}
      variant={state.variant}
      onConfirm={handleConfirm}
      onCancel={handleCancel}
    />
  ) : null;

  return { confirm, dialog };
}
